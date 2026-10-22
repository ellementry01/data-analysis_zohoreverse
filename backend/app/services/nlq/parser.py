"""Deterministic natural-language -> QuerySpec interpreter (works offline, no LLM required).

The interpreter is deliberately conservative: when it cannot map words to the semantic model it asks
for clarification instead of guessing, and every assumption it makes is reported back to the user.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..catalog import Catalog
from ..spec import Dimension, Filter, Measure, QuerySpec, SortBy
from .vocab import Entry, Vocab, is_id_column, label_column, norm_word, tokenize

NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
             "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "a": 1, "an": 1}
NUM = r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty|thirty)"
MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
DIM_CUES = {"by", "per", "each", "every", "across", "which", "what", "wise", "breakdown", "split", "among", "between", "where"}
CHART_WORDS = {"pie": "pie", "donut": "donut", "doughnut": "donut", "bar": "bar", "column": "bar", "line": "line",
               "area": "area", "table": "table", "scatter": "scatter", "heatmap": "heatmap", "heat map": "heatmap",
               "stacked": "stacked_bar", "kpi": "kpi", "number": "kpi", "pivot": "pivot"}


@dataclass
class Interpretation:
    kind: str  # query | trend_compare | dashboard | clarify | help | chitchat
    spec: QuerySpec | None = None
    chart: str | None = None
    title: str = ""
    assumptions: list[str] = field(default_factory=list)
    clarification: str = ""
    suggestions: list[str] = field(default_factory=list)
    widgets: list[tuple[str, QuerySpec, str | None]] = field(default_factory=list)
    post_filter: dict | None = None


def _num(s: str) -> int:
    return int(s) if s.isdigit() else NUM_WORDS.get(s, 1)


# ----------------------------------------------------------------------------------------------- time

def parse_time(low: str) -> tuple[object | None, str | None, list[tuple[int, int]], list[str]]:
    rng, grain, spans, notes = None, None, [], []

    def take(m):
        spans.append(m.span())

    pats = [
        (rf"\b(?:in|over|during|for)?\s*(?:the\s+)?(?:last|past|previous|prior|trailing)\s+{NUM}\s+(day|week|month|quarter|year)s?\b",
         lambda m: {"last": _num(m.group(1)), "unit": m.group(2) + "s"}),
        (r"\b(?:in\s+|for\s+|during\s+)?(?:the\s+)?(?:last|previous|past)\s+(day|week|month|quarter|year)\b",
         lambda m: {"day": "yesterday", "week": "last_week", "month": "last_month", "quarter": "last_quarter", "year": "last_year"}[m.group(1)]),
        (r"\b(?:in\s+|for\s+|during\s+)?(?:this|current)\s+(week|month|quarter|year)\b",
         lambda m: f"this_{m.group(1)}"),
        (r"\b(?:year to date|ytd)\b", lambda m: "year_to_date"),
        (r"\btoday\b", lambda m: "today"),
        (r"\byesterday\b", lambda m: "yesterday"),
        (r"\b(?:in|for|during)?\s*(" + "|".join(MONTHS) + r")\s+(\d{4})\b", lambda m: _month_range(m.group(1), int(m.group(2)))),
        (r"\bfrom\s+(\d{4}-\d{2}-\d{2})\s+(?:to|until|till|-)\s+(\d{4}-\d{2}-\d{2})\b", lambda m: {"from": m.group(1), "to": m.group(2)}),
        (r"\b(?:in|for|during)\s+(?:the\s+year\s+)?(20\d{2})\b", lambda m: {"from": f"{m.group(1)}-01-01", "to": f"{m.group(1)}-12-31"}),
        (r"\b(?:all time|ever|overall)\b", lambda m: None),
    ]
    for pat, fn in pats:
        m = re.search(pat, low)
        if m and rng is None:
            rng = fn(m)
            take(m)
    grains = [(r"\b(daily|per day|by day|each day|day by day|day wise|day-wise)\b", "day"),
              (r"\b(weekly|per week|by week|each week|week on week|week over week|wow)\b", "week"),
              (r"\b(monthly|per month|by month|each month|month on month|month over month|mom|month wise|month-wise|every month)\b", "month"),
              (r"\b(quarterly|per quarter|by quarter|each quarter|qoq)\b", "quarter"),
              (r"\b(yearly|annually|annual|per year|by year|each year|year on year|yoy|year wise)\b", "year")]
    for pat, g in grains:
        m = re.search(pat, low)
        if m:
            grain = g
            take(m)
            break
    if grain is None and re.search(r"\b(trend|trends|over time|time series|timeline|trajectory|movement over)\b", low):
        grain = "auto"
        m = re.search(r"\b(over time|time series|timeline)\b", low)
        if m:
            take(m)
    return rng, grain, spans, notes


def _month_range(name: str, year: int) -> dict:
    mth = MONTHS.index(name) + 1
    end_month, end_year = (mth % 12) + 1, year + (1 if mth == 12 else 0)
    from datetime import date, timedelta
    last = date(end_year, end_month, 1) - timedelta(days=1)
    return {"from": f"{year}-{mth:02d}-01", "to": last.isoformat()}


def _range_months(rng) -> int:
    if isinstance(rng, dict) and "last" in rng:
        u = rng.get("unit", "months")
        n = rng["last"]
        return n * {"days": 0, "weeks": 0, "months": 1, "quarters": 3, "years": 12}.get(u, 1) if not u.startswith(("day", "week")) else 0
    if isinstance(rng, str):
        return {"last_year": 12, "this_year": 12, "year_to_date": 6, "last_quarter": 3, "this_quarter": 3,
                "last_6_months": 6, "last_12_months": 12, "last_3_months": 3}.get(rng, 0)
    if isinstance(rng, dict) and "from" in rng:
        try:
            a, b = rng["from"][:7], rng["to"][:7]
            return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:7]) - int(a[5:7]) + 1
        except (TypeError, ValueError):
            return 0
    return 0


# ----------------------------------------------------------------------------------------------- matching

@dataclass
class Match:
    start: int
    end: int
    phrase: str
    entries: list[Entry]
    cue_dim: bool = False
    agg: str | None = None


def match_tokens(tokens: list[str], vocab: Vocab) -> list[Match]:
    used = [False] * len(tokens)
    out: list[Match] = []
    for n in range(min(vocab.max_len, 6), 0, -1):
        for i in range(0, len(tokens) - n + 1):
            if any(used[i:i + n]):
                continue
            ph = " ".join(tokens[i:i + n])
            if ph in vocab.entries:
                out.append(Match(i, i + n, ph, vocab.entries[ph]))
                for k in range(i, i + n):
                    used[k] = True
    out.sort(key=lambda m: m.start)
    for mt in out:
        before = tokens[max(0, mt.start - 3):mt.start]
        mt.cue_dim = any(t in DIM_CUES for t in before[-2:]) or (mt.end < len(tokens) and tokens[mt.end] == "wise")
        b = " ".join(before)
        if re.search(r"\b(average|avg|mean)\b", b):
            mt.agg = "avg"
        elif re.search(r"\b(number of|count of|how many|count|no of)\b", b) or (before[-2:] == ["how", "many"]):
            mt.agg = "count"
        elif re.search(r"\b(distinct|unique)\b", b):
            mt.agg = "count_distinct"
        elif re.search(r"\b(max|maximum|largest single|biggest single)\b", b):
            mt.agg = "max"
        elif re.search(r"\b(min|minimum|smallest single)\b", b):
            mt.agg = "min"
    return out


# ----------------------------------------------------------------------------------------------- parse

def interpret(question: str, cat: Catalog, vocab: Vocab, prev: QuerySpec | None = None) -> Interpretation:
    low = " " + re.sub(r"\s+", " ", question.lower()).strip() + " "
    stripped = low.strip(" ?.!")
    if re.fullmatch(r"(hi|hello|hey|thanks|thank you|ok|okay|cool|great|good (morning|afternoon|evening))[ !.]*", stripped):
        return Interpretation("chitchat")
    if re.search(r"\b(what can (you|i) (do|ask)|help me|^help$|what questions)\b", stripped):
        return Interpretation("help", suggestions=suggest_questions(cat))

    if re.search(r"\b(create|build|make|generate|set up|design)\b.*\bdashboard\b", low):
        return _dashboard(question, low, cat, vocab)

    chart = None
    for word, ct in CHART_WORDS.items():
        if re.search(rf"\b(as|in|into|show (?:it|this) as|use)\s+(a\s+|an\s+)?{word}\b|\b{word}\s+chart\b", low):
            chart = ct
            break

    # comparison phrases are removed before time parsing so "this year vs last year" keeps "this year" as the range
    compare = None
    cmp_year = re.search(r"\b(vs\.?|versus|compared (to|with)|against)\s+(the\s+)?(same period\s+)?last year\b|\byear over year\b|\byoy\b", low)
    cmp_prev = re.search(r"\b(vs\.?|versus|compared (to|with)|against)\s+(the\s+)?(previous|prior|last) (period|month|quarter|week)\b|\bperiod over period\b", low)
    time_text = low
    if cmp_year:
        compare = "previous_year"
        time_text = low[:cmp_year.start()] + " " * (cmp_year.end() - cmp_year.start()) + low[cmp_year.end():]
    elif cmp_prev:
        compare = "previous_period"
        time_text = low[:cmp_prev.start()] + " " * (cmp_prev.end() - cmp_prev.start()) + low[cmp_prev.end():]
    elif re.search(r"\b(growth|change|grew|growing)\b", low):
        compare = "previous_period"
    rng, grain, spans, _ = parse_time(time_text)
    if cmp_year:
        spans.append(cmp_year.span())
    if cmp_prev:
        spans.append(cmp_prev.span())

    top_n, direction = None, None
    m = re.search(rf"\b(top|bottom|best|worst|first)\s+{NUM}\b", low)
    if m:
        top_n = _num(m.group(2))
        direction = "asc" if m.group(1) in ("bottom", "worst") else "desc"
        spans.append(m.span())
    elif re.search(r"\b(highest|most|best|largest|biggest|top|maximum|leading|greatest|max)\b", low):
        direction = "desc"
    elif re.search(r"\b(lowest|least|worst|smallest|fewest|bottom|minimum|min|poorest)\b", low):
        direction = "asc"

    trend_pair = re.search(r"\b(declin\w*|decreas\w*|falling|dropping|shrinking|reducing)\b.*\b(but|while|and|with|yet)\b.*\b(increas\w*|rising|growing|ris\w*|building)\b", low) \
        or re.search(r"\b(increas\w*|rising|growing)\b.*\b(but|while|and|with|yet)\b.*\b(declin\w*|decreas\w*|falling|dropping)\b", low)

    # remove time phrases before vocabulary matching
    text_for_vocab = low
    for a, b in sorted(spans, reverse=True):
        text_for_vocab = text_for_vocab[:a] + " " + text_for_vocab[b:]
    tokens = tokenize(text_for_vocab)
    matches = match_tokens(tokens, vocab)

    assumptions: list[str] = []
    measures: list[Measure] = []
    measure_pos: list[int] = []
    dim_cands: list[tuple[Match, list[tuple[int, str]]]] = []
    value_filters: dict[tuple[int, str], list[str]] = {}
    value_matches: list[tuple[Match, list[Entry]]] = []
    dataset_hints: list[int] = []
    time_field: str | None = None

    for mt in matches:
        kinds = {e.kind for e in mt.entries}
        metric_e = [e for e in mt.entries if e.kind == "metric"]
        col_e = [e for e in mt.entries if e.kind == "column"]
        val_e = [e for e in mt.entries if e.kind == "value"]
        ds_e = [e for e in mt.entries if e.kind == "dataset"]

        if metric_e and not (mt.cue_dim and (col_e or ds_e)):
            name = metric_e[0].metric
            if not any(x.metric == name for x in measures):
                measures.append(Measure(metric=name))
                measure_pos.append(mt.start)
            continue
        counting = mt.agg in ("count", "count_distinct") and not mt.cue_dim
        if counting and ds_e:  # "how many locations" -> rows of the Locations dataset
            ds = cat.datasets[ds_e[0].dataset_id]
            measures.append(Measure(field=f"{ds.slug}.*", agg="count", label=f"Number of {ds.name}"))
            measure_pos.append(mt.start)
            continue
        if val_e and not counting and not (mt.cue_dim and (col_e or ds_e)) and not (col_e and any(cat.datasets[e.dataset_id].columns[e.column].type in ("integer", "decimal") for e in col_e)):
            value_matches.append((mt, val_e))  # resolved once the measures (and their datasets) are known
            continue
        if col_e:
            numeric = [e for e in col_e if cat.datasets[e.dataset_id].columns[e.column].type in ("integer", "decimal") and not is_id_column(e.column)]
            dates = [e for e in col_e if cat.datasets[e.dataset_id].columns[e.column].type in ("date", "datetime")]
            if numeric and not mt.cue_dim:
                e = numeric[0]
                ds = cat.datasets[e.dataset_id]
                agg = mt.agg if mt.agg in ("avg", "count", "count_distinct", "min", "max") else "sum"
                measures.append(Measure(field=f"{ds.slug}.{e.column}", agg=agg))
                measure_pos.append(mt.start)
                continue
            if dates:
                e = dates[0]
                time_field = f"{cat.datasets[e.dataset_id].slug}.{e.column}"
                grain = grain or "month"
                continue
            if mt.agg in ("count", "count_distinct") and not mt.cue_dim:
                e = col_e[0]
                measures.append(Measure(field=f"{cat.datasets[e.dataset_id].slug}.{e.column}", agg="count_distinct"))
                measure_pos.append(mt.start)
                continue
            cands = [(e.dataset_id, e.column) for e in col_e]
            for e in ds_e:
                lc = label_column(cat.datasets[e.dataset_id])
                if lc:
                    cands.append((e.dataset_id, lc))
            dim_cands.append((mt, cands))
            continue
        if ds_e:
            e = ds_e[0]
            ds = cat.datasets[e.dataset_id]
            if mt.agg in ("count", "count_distinct") and not mt.cue_dim:
                measures.append(Measure(field=f"{ds.slug}.*", agg="count", label=f"Number of {ds.name}"))
                measure_pos.append(mt.start)
            elif mt.cue_dim or "which" in tokens[max(0, mt.start - 2):mt.start]:
                lc = label_column(ds)
                if lc:
                    dim_cands.append((mt, [(ds.id, lc)]))
            else:
                dataset_hints.append(ds.id)

    # ---- trend comparison: "declining X but increasing Y"
    if trend_pair and len(measures) >= 2:
        first_word = trend_pair.group(1)
        dir_first = "down" if re.match(r"declin|decreas|fall|drop|shrink|reduc", first_word) else "up"
        bases = _bases(cat, measures)
        dims = _resolve_dims(cat, dim_cands, bases, assumptions)
        if not dims:
            ent = _default_entity(cat, bases)
            if ent:
                dims = [Dimension(field=ent)]
                assumptions.append(f"Compared per {cat.resolve_field(ent)[1].label}")
        rng2 = rng or "last_3_months"
        if not rng:
            assumptions.append("Compared the last 3 complete months with the 3 months before")
        spec = QuerySpec(dimensions=dims, measures=measures[:2], time_range=rng2, compare="previous_period",
                         limit=500, apply_rules=True)
        return Interpretation("trend_compare", spec=spec, chart=chart, assumptions=assumptions,
                              post_filter={"first": dir_first, "second": "up" if dir_first == "down" else "down"},
                              title=question.strip().rstrip("?"))

    # ---- follow-up handling
    followup = prev is not None and (not measures or re.match(r"^\s*(and|what about|how about|now|only|just|instead|also|same|then|but|ok|okay|show (it|that|this)|break|split|by|for|filter|exclude|remove|drop)\b", low.strip()))
    has_signal = bool(matches) or rng is not None or grain is not None or chart is not None or top_n is not None or compare is not None \
        or bool(re.search(r"\b(remove|without|drop|clear) (the )?filter", low))  # "remove the filter" is handled in the merge below
    if not measures and prev is not None and prev.measures and (has_signal or followup and not re.search(r"\b(weather|joke|who are you|your name)\b", low)):
        if not has_signal and not re.match(r"^\s*(and|what about|how about|same|again|repeat|refresh)\b", low.strip()):
            return Interpretation("clarify", clarification="I couldn't relate that to the data in this workspace.", suggestions=suggest_questions(cat))
        measures = list(prev.measures)
        assumptions.append("Continuing from the previous question")
    if not measures:
        if dataset_hints:
            ds = cat.datasets[dataset_hints[0]]
            measures.append(Measure(field=f"{ds.slug}.*", agg="count", label=f"Number of {ds.name}"))
            assumptions.append(f"Counted rows of {ds.name} (no measure was mentioned)")
        elif dim_cands or value_matches:
            return Interpretation("clarify", clarification="Which measure should I calculate?",
                                  suggestions=_metric_suggestions(cat))
        else:
            return Interpretation("clarify", clarification=(
                "I couldn't match that question to the data in this workspace. Try naming a metric or column "
                "(for example one of the metrics below), or add synonyms in the Semantic layer."),
                suggestions=_metric_suggestions(cat))

    bases = _bases(cat, measures)
    dims = _resolve_dims(cat, dim_cands, bases, assumptions)
    for mt, entries in value_matches:
        # the column on (or reachable from) the measures' data wins; glossary entries (weight 3) break ties
        e = max(entries, key=lambda x: (_reach_score(cat, x.dataset_id, x.column, bases) * 10
                                        + (5 if x.dataset_id in bases else 0) + x.weight))
        value_filters.setdefault((e.dataset_id, e.column), []).append(e.value)

    # value filters: "compare Shopify and Amazon" -> filter + split by that column
    filters: list[Filter] = []
    auto_dims: set[str] = set()  # dimensions added only because several values were named
    for (ds_id, col), vals in value_filters.items():
        ref = f"{cat.datasets[ds_id].slug}.{col}"
        filters.append(Filter(field=ref, op="in", value=list(dict.fromkeys(vals))))
        is_compare = len(vals) > 1 or re.search(r"\b(compare|vs|versus|against|split)\b", low)
        if is_compare and len(vals) > 1 and not any(d.field == ref for d in dims):
            dims.append(Dimension(field=ref))
            auto_dims.add(ref)

    want_time = grain is not None or (
        re.search(r"\b(compare|vs|versus|over|trend)\b", low) and _range_months(rng) >= 3
    ) or (len([m for m in measures]) >= 2 and re.search(r"\b(compare|vs|versus|against|with)\b", low) and not dims)
    if want_time and not any(d.field == "@time" or (d.grain is not None) for d in dims):
        g = grain if grain and grain != "auto" else ("day" if _range_months(rng) == 0 and rng else "month")
        if time_field:
            dims.insert(0, Dimension(field=time_field, grain=g))
        else:
            dims.insert(0, Dimension(field="@time", grain=g))

    # follow-up merge
    if followup and prev is not None:
        if not dims and not re.search(r"\b(total|overall|in total)\b", low):
            dims = list(prev.dimensions)
        elif re.search(r"\balso\b", low):
            dims = list(prev.dimensions) + [d for d in dims if d.field not in {p.field for p in prev.dimensions}]
        new_fields = {f.field for f in filters}
        if re.search(r"\b(remove|without|drop|clear) (the )?filter", low):
            prev_filters = []
        else:
            prev_filters = [f for f in prev.filters if f.field not in new_fields]
        filters = prev_filters + filters
        if rng is None:
            rng = prev.time_range
        compare = compare or prev.compare
        time_field = time_field or prev.time_field
        if top_n is None and direction is None and prev.limit and prev.sort:
            top_n, direction = prev.limit, prev.sort[0].dir

    # exclusions: "excluding X" / "except X" -> NOT IN on the best related column, and never a positive filter
    for m2 in re.finditer(r"\b(excluding|except|without|exclude|not|other than)\s+([a-z0-9 &\-]+?)(?=$|[,.?]| and | by | in | for | over | this | last )", low + " "):
        phrase = " ".join(tokenize(m2.group(2)))
        cands = [e for e in vocab.entries.get(phrase, []) if e.kind == "value"]
        if not cands:
            continue
        e = max(cands, key=lambda x: (_reach_score(cat, x.dataset_id, x.column, bases) * 10 + (5 if x.dataset_id in bases else 0) + x.weight))
        vals = {c.value for c in cands}
        cleaned = []
        for f in filters:
            if f.op == "in" and isinstance(f.value, list):
                rest = [v for v in f.value if v not in vals]
                if not rest:  # keep a breakdown the user asked for ("by channel excluding amazon")
                    dims = [d for d in dims if d.field != f.field or d.field not in auto_dims]
                    continue
                f = Filter(field=f.field, op="in", value=rest)
            cleaned.append(f)
        filters = cleaned + [Filter(field=f"{cat.datasets[e.dataset_id].slug}.{e.column}", op="not_in", value=[e.value])]

    sort, limit = [], None
    if direction and (dims or top_n):
        non_time = [d for d in dims if d.field != "@time" and not d.grain]
        if non_time:
            sort = [SortBy(field="__first_measure__", dir=direction)]
            limit = top_n or 10
    elif top_n:
        limit = top_n

    spec = QuerySpec(dimensions=dims, measures=measures, filters=filters, time_range=rng, time_field=time_field,
                     compare=compare if not any(d.grain or d.field == "@time" for d in dims) or compare == "previous_year" else compare,
                     sort=sort, limit=limit)
    title = question.strip().rstrip("?")
    return Interpretation("query", spec=spec, chart=chart, assumptions=assumptions, title=title)


def _bases(cat: Catalog, measures: list[Measure]) -> list[int]:
    out = []
    for ms in measures:
        if ms.metric:
            mt = cat.metrics.get(ms.metric)
            if mt and mt.kind == "composite":
                for n in re.findall(r"\{([a-z_][a-z0-9_]*)\}", mt.expression):
                    sub = cat.metrics.get(n)
                    if sub and sub.dataset_id:
                        out.append(sub.dataset_id)
            elif mt and mt.dataset_id:
                out.append(mt.dataset_id)
        elif ms.field:
            slug = ms.field.split(".")[0]
            ds = cat.by_slug.get(slug)
            if ds:
                out.append(ds.id)
    return list(dict.fromkeys(out))


def _reach_score(cat: Catalog, ds_id: int, col: str, bases: list[int]) -> float:
    score = 0.0
    for b in bases:
        paths = cat.parent_paths(b)
        if ds_id in paths:
            score += 2 - 0.1 * len(paths[ds_id])
        elif col in cat.datasets[b].columns:
            score += 1
    return score


def _resolve_dims(cat: Catalog, dim_cands, bases: list[int], assumptions: list[str]) -> list[Dimension]:
    dims: list[Dimension] = []
    for mt, cands in dim_cands:
        best, best_s = None, -1e9
        for ds_id, col in dict.fromkeys(cands):
            c = cat.datasets[ds_id].columns.get(col)
            if not c:
                continue
            s = _reach_score(cat, ds_id, col, bases) * 10
            if c.type == "text" and not is_id_column(col):
                s += 3
            if is_id_column(col):
                # an id on the fact: prefer the related dataset's name column if reachable
                s -= 2
            if s > best_s:
                best, best_s = (ds_id, col), s
        if best is None:
            continue
        ds_id, col = best
        if bases and _reach_score(cat, ds_id, col, bases) == 0:
            assumptions.append(f"'{mt.phrase}' is not related to the measure's data; define a relationship to break it down")
        ref = f"{cat.datasets[ds_id].slug}.{col}"
        if not any(d.field == ref for d in dims):
            dims.append(Dimension(field=ref))
    return dims


def _default_entity(cat: Catalog, bases: list[int]) -> str | None:
    """Pick a 'product'-like entity reachable from every base (used when the question names none)."""
    best, best_s = None, 0.0
    for ds in cat.datasets.values():
        if any(ds.id == b for b in bases):
            continue
        lc = label_column(ds)
        if not lc:
            continue
        s = sum(1 for b in bases if ds.id in cat.parent_paths(b))
        if "product" in ds.slug:
            s += 0.5
        if s > best_s:
            best, best_s = f"{ds.slug}.{lc}", s
    return best


def _metric_suggestions(cat: Catalog) -> list[str]:
    return [mt.label for mt in list(cat.metrics.values())[:8]] or [
        f"{c.label} ({ds.name})" for ds in cat.datasets.values() for c in ds.columns.values()
        if c.type in ("integer", "decimal") and not is_id_column(c.name)][:8]


def suggest_questions(cat: Catalog) -> list[str]:
    out = []
    metrics = list(cat.metrics.values())
    if metrics:
        m0 = metrics[0]
        out.append(f"What was {m0.label.lower()} last month?")
        out.append(f"Show {m0.label.lower()} by month for the last 12 months")
    dims = []
    for ds in cat.datasets.values():
        lc = label_column(ds)
        if lc and ds.kind != "query_table":
            dims.append((ds, lc))
    if metrics and dims:
        out.append(f"Top 5 {dims[0][0].name.lower()} by {metrics[0].label.lower()}")
    if len(metrics) > 1:
        out.append(f"Compare {metrics[0].label.lower()} with {metrics[1].label.lower()} over the last 6 months")
    if not out:
        for ds in list(cat.datasets.values())[:3]:
            out.append(f"How many {ds.name.lower()} are there?")
    return out


def _dashboard(question: str, low: str, cat: Catalog, vocab: Vocab) -> Interpretation:
    rng, grain, spans, _ = parse_time(low)
    tokens = tokenize(low)
    matches = match_tokens(tokens, vocab)
    widgets = []
    assumptions = []
    g = grain if grain and grain != "auto" else "month"
    seen = set()
    for mt in matches:
        metric_e = [e for e in mt.entries if e.kind == "metric"]
        col_e = [e for e in mt.entries if e.kind == "column" and cat.datasets[e.dataset_id].columns[e.column].type in ("integer", "decimal") and not is_id_column(e.column)]
        if metric_e:
            e = metric_e[0]
            if e.metric in seen:
                continue
            seen.add(e.metric)
            label = cat.metrics[e.metric].label
            ms = Measure(metric=e.metric)
        elif col_e:
            e = col_e[0]
            key = (e.dataset_id, e.column)
            if key in seen:
                continue
            seen.add(key)
            label = cat.datasets[e.dataset_id].columns[e.column].label
            ms = Measure(field=f"{cat.datasets[e.dataset_id].slug}.{e.column}", agg="sum")
        else:
            continue
        r = rng or "last_12_months"
        widgets.append((f"{label} by {g}", QuerySpec(dimensions=[Dimension(field="@time", grain=g)], measures=[ms], time_range=r), "line"))
        widgets.append((f"{label}", QuerySpec(measures=[ms], time_range=r, compare="previous_period"), "kpi"))
    if not rng:
        assumptions.append("Used the last 12 months")
    if not widgets:
        return Interpretation("clarify", clarification="Which metrics should the dashboard show?", suggestions=_metric_suggestions(cat))
    # KPI cards first, then trend charts
    widgets.sort(key=lambda w: 0 if w[2] == "kpi" else 1)
    name = re.sub(r"^(please\s+)?(create|build|make|generate|set up|design)\s+(me\s+)?(a|an)?\s*", "", question.strip(), flags=re.I).rstrip("?.")
    return Interpretation("dashboard", widgets=widgets, title=name[:1].upper() + name[1:] if name else "AI dashboard", assumptions=assumptions)
