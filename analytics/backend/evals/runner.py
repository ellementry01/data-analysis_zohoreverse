"""Evaluation runner for the assistants.

An eval set is a YAML file in evals/sets/. Each case asks one question and states what a correct answer contains:

    - id: stock-value
      dashboard: stock                          # ask that dashboard's assistant (omit for the Ask page)
      screen_state: {filters: [{id: category, value: [Decor]}]}   # optional; defaults are the dashboard's own
      question: What is our stock worth at cost?
      expect:                                   # where the right number comes from, computed at run time:
        widget: Stock value at cost             #   a widget of the dashboard, with the same filters, or
        # sql: SELECT ...                       #   a read-only SQL statement, or
        # spec: {measures: [...]}               #   a QuerySpec through the governed query endpoint
        row: COD                                # optional: the row whose first dimension contains this text
        column: rto_rate                        # optional: which measure column (default: the first measure)
        top: true                               # optional: the row with the largest value; its label must be named
        label: product_name                     # optional: which dimension column is the label for `top`
      must_mention: [[website, site]]           # every item must appear (an item may be a list = any of)
      must_not_mention: []
      check_invented: true                      # default: every number in the answer must come from its data

Numbers are matched with rounding in mind: "₹3.86 Cr" matches 3,86,12,345 and "7.8%" matches 0.0784.

The default engine is the offline semantic engine, which costs nothing. --live uses Claude and needs EVAL_LIVE_OK=1
(live calls cost money and need the owner's OK).
"""
from __future__ import annotations

import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

SETS_DIR = Path(__file__).parent / "sets"
from app.services.agent.numbers import DATES as _DATES  # noqa: E402  (shared with the assistant's own check)
from app.services.agent.numbers import Num, matches as _matches, number_tokens, parse_numbers, result_numbers, ungrounded  # noqa: E402,F401


class Transport:
    """POST/GET JSON against the app (HTTP by default; tests pass an in-process client)."""

    def __init__(self, base: str, user: str | None = None):
        self.base, self.user = base.rstrip("/"), user

    def _req(self, method: str, path: str, body: dict | None = None):
        headers = {"Content-Type": "application/json"}
        if self.user:
            headers["X-User-Email"] = self.user
        import os

        token = os.environ.get("ELLEMENTRY_API_TOKEN", "").strip()   # needed once company sign-in is on
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            raise EvalError(f"{path}: HTTP {e.code}: {e.read().decode(errors='replace')[:300]}") from e

    def post(self, path: str, body: dict) -> dict:
        return self._req("POST", path, body)

    def get(self, path: str):
        return self._req("GET", path)

    def delete(self, path: str):
        return self._req("DELETE", path)


class EvalError(RuntimeError):
    pass


@dataclass
class Expected:
    value: float | None = None
    label: str | None = None


@dataclass
class CaseResult:
    id: str
    passed: bool
    expected: float | None = None
    expected_label: str | None = None
    found: list[float] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    engine: str | None = None
    model: str | None = None
    cost_inr: float = 0.0
    seconds: float = 0.0
    answer: str = ""


def load_set(name_or_path: str) -> list[dict]:
    import yaml

    p = Path(name_or_path)
    if not p.suffix:
        p = SETS_DIR / f"{name_or_path}.yaml"
    cases = yaml.safe_load(p.read_text(encoding="utf-8")) or []
    ids = [c.get("id") for c in cases]
    if any(not i for i in ids) or len(ids) != len(set(ids)):
        raise EvalError(f"{p.name}: every case needs a unique id")
    return cases


# ----------------------------------------------------------------------------------------------- numbers

def _numeric_cells(res: dict, column: str | None = None) -> list[float]:
    cols = [c.get("name") or c.get("label") for c in res.get("columns") or []]
    vals = []
    for row in res.get("rows") or []:
        for i, v in enumerate(row):
            if column and i < len(cols) and cols[i] != column:
                continue
            if isinstance(v, bool):
                continue
            if isinstance(v, (int, float)) and not (isinstance(v, float) and math.isnan(v)):
                vals.append(float(v))
            elif isinstance(v, str):
                try:
                    vals.append(float(v))
                except ValueError:
                    pass
    return vals


def allowed_numbers(answer: dict, question: str = "") -> list[float]:
    """Every number an answer may quote: the cells, labels, totals and shares of its result and of every step the
    assistant took, plus numbers already in the question or the answer's assumptions and warnings."""
    allowed = result_numbers(answer.get("columns") or [], answer.get("rows") or [])
    for st in answer.get("steps") or []:
        allowed += result_numbers(st.get("columns") or [], st.get("rows") or [])
        allowed += parse_numbers(" ".join(str(x) for x in st.get("notes") or []))
    for extra in [question, *(answer.get("assumptions") or []), *(answer.get("warnings") or [])]:
        allowed += parse_numbers(str(extra))
    allowed += parse_numbers(json.dumps(answer.get("comparison") or {}))
    return allowed


def invented_numbers(answer: dict, question: str = "") -> list[str]:
    return ungrounded(answer.get("text") or "", allowed_numbers(answer, question))


# ----------------------------------------------------------------------------------------------- expectations

def _dashboard(t: Transport, ws: int, key: str) -> dict:
    return t.get(f"/api/workspaces/{ws}/dashboards/key/{urllib.parse.quote(key)}")


def _screen_filters(dash: dict, screen: dict | None) -> list[dict]:
    sent = {f["id"]: f.get("value") for f in (screen or {}).get("filters") or []}
    return [{"field": f["field"], "type": f["type"], "value": sent.get(f["id"], f.get("value"))} for f in dash.get("filters") or []]


def _pick(res: dict, expect: dict) -> Expected:
    cols = res.get("columns") or []
    rows = res.get("rows") or []
    if not rows:
        raise EvalError("the expected-value query returned no rows")
    names = [c.get("name") for c in cols]
    meas = [i for i, c in enumerate(cols) if c.get("role") == "measure"] or \
           [i for i, v in enumerate(rows[0]) if isinstance(v, (int, float)) and not isinstance(v, bool)]
    dims = [i for i, c in enumerate(cols) if c.get("role") == "dimension"]
    mi = names.index(expect["column"]) if expect.get("column") in names else (meas[0] if meas else 0)
    li = names.index(expect["label"]) if expect.get("label") in names else (dims[0] if dims else None)
    if expect.get("row") is not None:
        want = str(expect["row"]).lower()
        row = next((r for r in rows if li is not None and want in str(r[li]).lower()), None)
        if row is None:
            raise EvalError(f"no row matching '{expect['row']}' in the expected-value result")
        return Expected(float(row[mi]), str(row[li]))
    if expect.get("top"):
        num = [r for r in rows if isinstance(r[mi], (int, float))]
        row = max(num, key=lambda r: r[mi])
        return Expected(float(row[mi]), str(row[li]) if li is not None else None)
    v = rows[0][mi]
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise EvalError("the expected-value query returned no number")
    return Expected(float(v), None)


def expected_value(t: Transport, ws: int, case: dict) -> Expected:
    expect = case.get("expect") or {}
    if "widget" in expect:
        dash = _dashboard(t, ws, case["dashboard"])
        w = next((x for x in dash["widgets"] if x["title"] == expect["widget"]), None)
        if not w:
            raise EvalError(f"widget '{expect['widget']}' is not on dashboard '{case['dashboard']}'")
        res = t.post(f"/api/workspaces/{ws}/dashboards/{dash['id']}/widgets/{w['id']}/data",
                     {"filters": _screen_filters(dash, case.get("screen_state"))})
    elif "sql" in expect:
        res = t.post(f"/api/workspaces/{ws}/sql", {"sql": expect["sql"]})
    elif "spec" in expect:
        res = t.post(f"/api/workspaces/{ws}/query", expect["spec"])
    else:
        return Expected()
    return _pick(res, expect)


# ----------------------------------------------------------------------------------------------- scoring

_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december"]


def label_variants(label: str) -> list[str]:
    """Ways an answer may name a label: as is, and for a month start date ("2025-10-01") also "october 2025",
    "oct 2025" and "2025-10"."""
    low = str(label).lower()
    out = [low]
    m = re.match(r"^(\d{4})-(\d{2})(?:-01)?(?:[t ].*)?$", low)
    if m:
        y, mo = m.group(1), int(m.group(2))
        name = _MONTHS[mo - 1]
        out += [f"{name} {y}", f"{name[:3]} {y}", f"{name[:3]}-{y[2:]}", f"{y}-{m.group(2)}"]
    return out


def score(case: dict, answer: dict, expected: Expected | float | None, context: list[float] | None = None) -> CaseResult:
    """context: numbers the user could see when asking (the dashboard's widgets with the same filters, its description
    and widget titles); quoting them is not inventing."""
    if not isinstance(expected, Expected):
        expected = Expected(expected)
    r = CaseResult(id=case["id"], passed=True, expected=expected.value, expected_label=expected.label,
                   engine=answer.get("engine"), model=answer.get("model"), answer=(answer.get("text") or "")[:500])
    usage = answer.get("usage") or {}
    r.cost_inr = float(usage.get("cost_inr") or 0)
    if answer.get("type") == "error":
        r.problems.append(f"error answer: {answer.get('text', '')[:200]}")
    text = " ".join(str(answer.get(k) or "") for k in ("text", "title"))
    low = text.lower()
    if expected.value is not None:
        tol = float((case.get("expect") or {}).get("tolerance", 0.005))
        tokens = number_tokens(text)
        cells = _numeric_cells(answer)
        r.found = (cells + [v for n in tokens for v in n.values])[:20]
        in_cells = any(abs(c - expected.value) <= max(abs(expected.value) * tol, 1e-9) for c in cells)
        in_text = any(_matches(n, expected.value, tol) for n in tokens)
        if not (in_cells or in_text):
            r.problems.append(f"expected {expected.value:g} not found in the answer")
    if expected.label and (case.get("expect") or {}).get("top"):
        named = (case.get("expect") or {}).get("label_match")  # a distinctive part of a long label is enough
        if not any(alt in low for alt in label_variants(expected.label) + ([str(named).lower()] if named else [])):
            r.problems.append(f"does not name '{expected.label}'")
    for item in case.get("must_mention") or []:
        options = item if isinstance(item, list) else [item]
        hay = low + " " + " ".join(answer.get("assumptions") or []).lower()
        if not any(str(o).lower() in hay for o in options):
            r.problems.append(f"does not mention {' / '.join(map(str, options))}")
    for item in case.get("must_not_mention") or []:
        if str(item).lower() in low:
            r.problems.append(f"mentions '{item}', which it must not")
    if case.get("check_invented", True) and answer.get("type") == "answer":
        bad = ungrounded(answer.get("text") or "", allowed_numbers(answer, case.get("question", "")) + (context or []))
        if bad:
            r.problems.append(f"numbers not found in the data: {', '.join(bad[:5])}")
    r.passed = not r.problems
    return r


_screen_cache: dict[str, list[float]] = {}


def screen_numbers(t: Transport, ws: int, case: dict) -> list[float]:
    """Every number on the dashboard as the user saw it: each widget computed with the case's filters, plus the
    description, widget titles and filter values. Computed independently of the assistant."""
    key = json.dumps([ws, case["dashboard"], case.get("screen_state")], sort_keys=True, default=str)
    if key in _screen_cache:
        return _screen_cache[key]
    dash = _dashboard(t, ws, case["dashboard"])
    nums = parse_numbers(dash.get("description") or "") + parse_numbers(" ".join(w["title"] for w in dash["widgets"]))
    nums += parse_numbers(json.dumps(dash.get("filters") or [], default=str))
    for w in dash["widgets"]:
        try:
            res = t.post(f"/api/workspaces/{ws}/dashboards/{dash['id']}/widgets/{w['id']}/data",
                         {"filters": _screen_filters(dash, case.get("screen_state"))})
            nums += result_numbers(res.get("columns") or [], res.get("rows") or [])
        except EvalError:
            pass
    _screen_cache[key] = nums
    return nums


def run_case(t: Transport, ws: int, case: dict, engine: str) -> CaseResult:
    started = time.monotonic()
    try:
        expected = expected_value(t, ws, case)
        body = {"question": case["question"], "engine": engine}
        context = screen_numbers(t, ws, case) if case.get("dashboard") else []
        if case.get("dashboard"):
            body["screen_state"] = case.get("screen_state") or {}
            answer = t.post(f"/api/workspaces/{ws}/dashboards/key/{urllib.parse.quote(case['dashboard'])}/assistant/ask", body)
        else:
            answer = t.post(f"/api/workspaces/{ws}/assistant/ask", body)
        issues = []
        if case.get("check_issue_codes") and case.get("dashboard"):
            issues = t.get(f"/api/workspaces/{ws}/dashboards/key/{urllib.parse.quote(case['dashboard'])}/insights")["issues"]
            # numbers quoted from the issue register ("99-100% discount") are sourced, not invented
            context = context + parse_numbers(" ".join(f"{i['title']} {i['note']} {i['what_is_needed']}" for i in issues))
        r = score(case, answer, expected, context)
        if case.get("check_issue_codes") and case.get("dashboard"):
            # Phase 5: an answer may cite only issues the register has for this dashboard
            known = {i["code"] for i in issues}
            cited = set(re.findall(r"\b[A-Z]{1,4}-\d{1,5}\b", answer.get("text") or ""))
            if cited - known:
                r.problems.append(f"cites issues not recorded for this dashboard: {', '.join(sorted(cited - known))}")
                r.passed = False
        if answer.get("conversation_id") and hasattr(t, "delete"):
            try:  # eval threads must not clutter the user's own conversation lists
                t.delete(f"/api/workspaces/{ws}/conversations/{answer['conversation_id']}")
            except EvalError:
                pass
    except EvalError as e:
        r = CaseResult(id=case["id"], passed=False, problems=[str(e)])
    r.seconds = round(time.monotonic() - started, 2)
    return r


# ----------------------------------------------------------------------------------------------- memory stories
# A story (Phase 4) is several steps, each in a NEW conversation unless it says same_conversation: true:
#
#   - id: mem-last-year
#     story:
#       - remember: [{name: pref, text: "...", kind: preference, scope: global}]   # set up memories (status: retired
#                                                                                   #  to set one up already retired)
#       - dashboard: sales-channels
#         question: Remember that I compare with the same period last year
#         name: pref                       # the memory this answer saves is called `pref` in later steps
#         expect_saved: {status: active, kind: preference}
#         reject_proposals: true           # reject what this answer offered to remember (a "No" on the card)
#       - dashboard: executive-overview
#         question: How are net sales this financial year?
#         expect_used: [pref]              # the answer cites these memories
#         expect_not_used: [other]
#         expect_last_year: "2025-04"      # a step compared with last year (compare=previous_year, or a range from here)
#         must_mention: [[last year, previous year]]
#
# Everything a story creates (memories, conversations) is deleted afterwards. Stories need Claude (--live).

def _step_specs(answer: dict) -> list[dict]:
    out = []
    for s in answer.get("steps") or []:
        spec = s.get("spec") or ((s.get("input") or {}).get("spec") if isinstance(s.get("input"), dict) else None)
        if isinstance(spec, dict):
            out.append(spec)
    if isinstance(answer.get("spec"), dict):
        out.append(answer["spec"])
    return out


def _compared_last_year(answer: dict, prefix: str) -> bool:
    for spec in _step_specs(answer):
        if spec.get("compare") == "previous_year":
            return True
        tr = spec.get("time_range")
        if isinstance(tr, dict) and str(tr.get("from") or "").startswith(str(prefix)):
            return True
    return False


def run_story(t: Transport, ws: int, case: dict, engine: str) -> CaseResult:
    r = CaseResult(id=case["id"], passed=True)
    names: dict[str, int] = {}
    made: list[int] = []
    convs: list[int] = []
    root = f"/api/workspaces/{ws}"
    try:
        for i, step in enumerate(case["story"], 1):
            tag = f"step {i}"
            for mm in step.get("remember") or []:
                body = {k: mm[k] for k in ("text", "kind", "scope", "rationale", "visibility") if k in mm}
                x = t.post(f"{root}/memory", body)
                made.append(x["id"])
                if mm.get("name"):
                    names[mm["name"]] = x["id"]
                if mm.get("status") == "retired":
                    t.post(f"{root}/memory/{x['id']}/retire", {})
            if not step.get("question"):
                continue
            body = {"question": step["question"], "engine": engine, "screen_state": step.get("screen_state") or {},
                    "conversation_id": convs[-1] if step.get("same_conversation") and convs else None}
            answer = t.post(f"{root}/dashboards/key/{urllib.parse.quote(step['dashboard'])}/assistant/ask", body)
            if answer.get("conversation_id") and answer["conversation_id"] not in convs:
                convs.append(answer["conversation_id"])
            r.cost_inr += float((answer.get("usage") or {}).get("cost_inr") or 0)
            r.engine, r.model = answer.get("engine"), answer.get("model")
            r.answer = (answer.get("text") or "")[:500]
            saved = answer.get("memories_saved") or []
            made += [x["id"] for x in saved if x["id"] not in made]
            if step.get("name") and saved:
                names[step["name"]] = saved[0]["id"]
            used = {x["id"] for x in answer.get("memories_used") or []}
            want = step.get("expect_saved")
            if want and not any(all(x.get(k) == v for k, v in want.items()) for x in saved):
                r.problems.append(f"{tag}: nothing saved like {want} (saved: {[(x['status'], x['kind']) for x in saved]})")
            for n in step.get("expect_used") or []:
                if names.get(n) not in used:
                    r.problems.append(f"{tag}: did not use memory '{n}'")
            for n in step.get("expect_not_used") or []:
                if names.get(n) in used:
                    r.problems.append(f"{tag}: used memory '{n}', which it must not")
            if step.get("expect_last_year") and not _compared_last_year(answer, step["expect_last_year"]):
                r.problems.append(f"{tag}: no step compared with last year")
            if step.get("reject_proposals"):
                for p in t.get(f"{root}/memory/proposals"):
                    if p["source"].get("conversation_id") == answer.get("conversation_id"):
                        t.post(f"{root}/memory/{p['id']}/reject", {})
            checked = score({"id": case["id"], "question": step["question"], "must_mention": step.get("must_mention"),
                             "must_not_mention": step.get("must_not_mention"),
                             "check_invented": step.get("check_invented", True)}, answer, None,
                            screen_numbers(t, ws, {"dashboard": step["dashboard"], "screen_state": step.get("screen_state")}))
            r.problems += [f"{tag}: {p}" for p in checked.problems]
    except EvalError as e:
        r.problems.append(str(e))
    finally:
        for mid in made:          # leave the owner's memory and chat lists as they were
            try:
                t.delete(f"{root}/memory/{mid}")
            except EvalError:
                pass
        for cid in convs:
            try:
                t.delete(f"{root}/conversations/{cid}")
            except EvalError:
                pass
    r.passed = not r.problems
    return r


def run_set(t: Transport, ws: int, cases: list[dict], engine: str = "semantic") -> list[CaseResult]:
    out = []
    for c in cases:
        if c.get("story"):
            started = time.monotonic()
            res = run_story(t, ws, c, engine)
            res.seconds = round(time.monotonic() - started, 2)
            out.append(res)
        else:
            out.append(run_case(t, ws, c, engine))
    return out


def summary(results: list[CaseResult]) -> dict:
    n = len(results)
    numeric = [r for r in results if r.expected is not None]
    return {"cases": n, "passed": sum(r.passed for r in results),
            "numbers_correct": sum(not any(p.startswith("expected ") for p in r.problems) for r in numeric),
            "numeric_cases": len(numeric),
            "invented": sum(any(p.startswith("numbers not found") for p in r.problems) for r in results),
            "cost_inr": round(sum(r.cost_inr for r in results), 2),
            "median_seconds": sorted(r.seconds for r in results)[n // 2] if n else 0}


def report(results: list[CaseResult]) -> str:
    lines = []
    for r in results:
        mark = "PASS" if r.passed else "FAIL"
        extra = f" [{r.engine}{' ' + r.model if r.model else ''}, {r.seconds}s, Rs {r.cost_inr:.2f}]"
        lines.append(f"{mark}  {r.id}{extra}")
        lines += [f"      - {p}" for p in r.problems]
    s = summary(results)
    lines.append(f"\n{s['passed']}/{s['cases']} passed ({s['passed'] / max(s['cases'], 1):.0%}); "
                 f"correct numbers {s['numbers_correct']}/{s['numeric_cases']}; answers with invented numbers {s['invented']}; "
                 f"estimated cost Rs {s['cost_inr']:.2f}; median {s['median_seconds']}s")
    return "\n".join(lines)
