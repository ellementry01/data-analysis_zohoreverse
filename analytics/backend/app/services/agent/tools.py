"""The tools a dashboard assistant can call (Phase 2). All of them only read.

Every number comes through the same guarded path as the dashboards: QuerySpec -> query_engine -> validate_select ->
run_readonly. A tool sees only its workspace's data and dashboards. Results go to the model already formatted for
display (₹ Cr/L, %) together with exact totals and shares, so it quotes rather than calculates. Each call returns:
  * content: what the model reads (compact JSON text)
  * data:    the full result for the answer card (columns, rows, spec, SQL) when the tool ran a query
  * numbers: every number the answer may quote from this call (cells, labels, totals, shares)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date

from pydantic import ValidationError
from sqlalchemy.orm import Session

from ... import models as m
from ..analytics import QueryExecutionError, QueryError, UnsafeSQLError, run_spec
from ..catalog import Catalog
from ..dashboards import apply_dashboard_filters
from ..spec import Dimension, QuerySpec
from . import context as actx
from .numbers import parse_numbers, result_numbers

log = logging.getLogger(__name__)

MAX_ROWS_TO_MODEL = 50


class ToolError(Exception):
    """A problem the model can fix (bad input, unknown name): returned to it as an error result."""


@dataclass
class ToolContext:
    db: Session
    ws: m.Workspace
    cat: Catalog
    user: str
    today: date | None = None
    scope: object = None                 # assistant.AnswerScope (dashboard), or None
    dashboard: m.Dashboard | None = None
    # Phase 4 memory: on when ASSISTANT_MEMORY is; `explicit` is decided by code from the USER's own words
    memory_on: bool = False
    explicit: bool = False
    conversation_id: int | None = None
    message_id: int | None = None        # the user's question being answered
    question: str = ""
    saved: list = field(default_factory=list)      # memories propose_memory created in this answer
    found: list = field(default_factory=list)      # memories search_memory returned (may be cited)


@dataclass
class ToolOutcome:
    content: str
    ok: bool = True
    label: str = ""
    data: dict | None = None
    numbers: list[float] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# ----------------------------------------------------------------------------------------------- definitions

_FILTERS_SCHEMA = {"type": "array", "description": "Dashboard filter values to use instead of the ones on screen, as [{id, value}]; "
                   "ids are the [id ...] shown under FILTERS. Omit to use the screen's values.",
                   "items": {"type": "object", "properties": {"id": {"type": "string"}, "value": {}}, "required": ["id"]}}

TOOLS = [
    {"name": "run_query",
     "description": "Run a QuerySpec (the JSON format in the system prompt) through the governed semantic layer and get the "
                    "result. Use it for any number, breakdown, comparison or trend. On a dashboard, the dashboard's filters "
                    "in force are applied automatically unless the spec sets its own time_range or filters the same field; "
                    "the result's notes say which were applied. Prefer metrics. Returns at most 50 rows to you, formatted for "
                    "display, with exact totals and shares in 'facts'.",
     "input_schema": {"type": "object", "properties": {
         "spec": {"type": "object", "description": "The QuerySpec."},
         "title": {"type": "string", "description": "A short title for this result, e.g. 'Late shipments by courier, Oct 2025'."}},
         "required": ["spec"]}},
    {"name": "get_widget_data",
     "description": "Get the numbers of one widget of a dashboard exactly as the dashboard computes them, with the screen's "
                    "filters (or the ones you pass) and an optional drill-down into one value of the widget's first dimension.",
     "input_schema": {"type": "object", "properties": {
         "dashboard_key": {"type": "string", "description": "The dashboard key; omit for the current dashboard."},
         "widget": {"type": "string", "description": "The widget's title (as quoted under WIDGETS) or its widget id."},
         "filters": _FILTERS_SCHEMA,
         "drill": {"type": "array", "description": "Drill-down steps [{field, value}] on the widget's own dimensions.",
                   "items": {"type": "object", "properties": {"field": {"type": "string"}, "value": {}}, "required": ["field", "value"]}}},
         "required": ["widget"]}},
    {"name": "describe_metric",
     "description": "The governed definition of a metric: formula, business rules, date column, whether it is stock-like, "
                    "format, whether higher is better, and its description.",
     "input_schema": {"type": "object", "properties": {"name": {"type": "string", "description": "Metric name, e.g. rto_rate."}},
                      "required": ["name"]}},
    {"name": "list_values",
     "description": "Distinct values of a field (at most 50), optionally only those containing a search text. Use it to find "
                    "the exact spelling of a location, channel, category or product before filtering on it.",
     "input_schema": {"type": "object", "properties": {
         "field": {"type": "string", "description": "<dataset>.<column>, e.g. locations.location_name."},
         "search": {"type": "string", "description": "Optional text the values must contain (case-insensitive)."}},
         "required": ["field"]}},
    {"name": "get_dashboard_context",
     "description": "The description of another dashboard of this workspace (its caveats, filters, widgets, metric definitions "
                    "and data dates). The current dashboard is already in the system prompt.",
     "input_schema": {"type": "object", "properties": {"dashboard_key": {"type": "string"}}, "required": ["dashboard_key"]}},
    {"name": "get_data_issues",
     "description": "Known data issues that affect a dashboard, metric or dataset (from the issue register).",
     "input_schema": {"type": "object", "properties": {
         "about": {"type": "string", "description": "A dashboard key, metric name or dataset name; omit for the current dashboard."}}}},
]
MEMORY_TOOLS = [
    {"name": "search_memory",
     "description": "Search what you remember for this user beyond the memories already shown: their preferences, facts, "
                    "decisions (with reasons and dates) and open questions, plus team facts. Use it when the user asks "
                    "what they decided or said before, or when a past decision may matter.",
     "input_schema": {"type": "object", "properties": {"query": {"type": "string", "description": "Words to look for."}},
                      "required": ["query"]}},
    {"name": "propose_memory",
     "description": "Save something for future conversations: call it when the user asks you to remember something, "
                    "states a preference for how numbers are shown or compared, a business fact, or a decision with its "
                    "reason. Whether it is saved at once or offered to the user for approval is decided by the app. One "
                    "short sentence in the user's terms; never numbers from answers (they change).",
     "input_schema": {"type": "object", "properties": {
         "text": {"type": "string", "description": "What to remember, one sentence."},
         "kind": {"type": "string", "enum": ["preference", "fact", "decision", "caveat", "open_question"]},
         "scope": {"type": "string", "enum": ["this_dashboard", "global"],
                   "description": "this_dashboard if it only matters here, else global."},
         "rationale": {"type": "string", "description": "For a decision: the reason the user gave."},
         "share_with_team": {"type": "boolean", "description": "True only for a business fact everyone should know."}},
         "required": ["text", "kind", "scope"]}},
]
TOOL_NAMES = [t["name"] for t in TOOLS + MEMORY_TOOLS]
MAX_SAVES_PER_ANSWER = 3


def tools_for(ctx: "ToolContext") -> list[dict]:
    return TOOLS + MEMORY_TOOLS if ctx.memory_on else TOOLS


# ----------------------------------------------------------------------------------------------- helpers

def _result_for_model(res: dict, title: str, notes: list[str]) -> tuple[str, list[float]]:
    from ..nlq.claude import _display, _facts

    cols = res.get("columns") or []
    rows = res.get("rows") or []
    shown_rows, shown_facts = _display(cols, rows[:MAX_ROWS_TO_MODEL], _facts(cols, rows))
    body = {"title": title, "columns": [c.get("label") or c.get("name") for c in cols], "rows": shown_rows,
            "row_count": len(rows), "facts": shown_facts}
    if len(rows) > MAX_ROWS_TO_MODEL:
        body["note_rows"] = f"Only the first {MAX_ROWS_TO_MODEL} of {len(rows)} rows are shown; facts cover all rows."
    if res.get("truncated"):
        body["truncated"] = "The query hit the row limit; totals cover the rows returned only."
    if notes:
        body["notes"] = notes
    warn = res.get("warnings") or []
    if warn:
        body["warnings"] = warn
    if res.get("comparison"):
        body["comparison"] = res["comparison"].get("note") or res["comparison"]
    numbers = result_numbers(cols, rows) + parse_numbers(" ".join(notes + warn))
    return json.dumps(body, default=str, ensure_ascii=False), numbers


def _data(res: dict, title: str, spec: QuerySpec | None) -> dict:
    keys = ("columns", "rows", "row_count", "truncated", "sql", "warnings", "insights", "date_range", "comparison")
    return {"title": title, "spec": spec.model_dump() if spec else None, **{k: res.get(k) for k in keys}}


def _dashboard(ctx: ToolContext, key: str | None) -> m.Dashboard:
    if not key or (ctx.dashboard is not None and key == ctx.dashboard.key):
        if ctx.dashboard is None:
            raise ToolError("There is no current dashboard; pass dashboard_key.")
        return ctx.dashboard
    d = ctx.db.query(m.Dashboard).filter_by(workspace_id=ctx.ws.id, key=str(key)).one_or_none()
    if not d or not can_see_dashboard(ctx, d):
        from ..permissions import visible_dashboards

        keys = [x.key for x in visible_dashboards(ctx.db, ctx.ws)]
        raise ToolError(f"No dashboard with key '{key}'. Keys: {', '.join(sorted(keys))}")
    return d


def can_see_dashboard(ctx: ToolContext, d: m.Dashboard) -> bool:
    """The same check as the dashboard routes: the assistant never sees more than the person asking."""
    from ..permissions import can_see_dashboard as allowed

    return allowed(ctx.db, ctx.ws, d)


# ----------------------------------------------------------------------------------------------- the tools

def run_query(ctx: ToolContext, spec: dict, title: str = "") -> ToolOutcome:
    from ..nlq.assistant import _assign_aliases, _run_scoped

    if not isinstance(spec, dict):
        raise ToolError("spec must be a JSON object (a QuerySpec).")
    try:
        qs = QuerySpec.model_validate(spec)
    except ValidationError as e:
        raise ToolError(f"Invalid QuerySpec: {e.errors()[0].get('loc')} {e.errors()[0].get('msg')}") from e
    _assign_aliases(qs)
    try:
        res, qs, notes = _run_scoped(ctx.db, ctx.cat, qs, ctx.user, ctx.today, ctx.scope)
    except (QueryError, QueryExecutionError, UnsafeSQLError, ValueError) as e:
        raise ToolError(f"The query failed: {str(e).splitlines()[0][:300]}") from e
    title = (title or "Query result")[:200]
    content, numbers = _result_for_model(res, title, notes)
    return ToolOutcome(content, label=title, data=_data(res, title, qs), numbers=numbers, notes=notes)


def get_widget_data(ctx: ToolContext, widget: str, dashboard_key: str | None = None, filters: list | None = None,
                    drill: list | None = None) -> ToolOutcome:
    d = _dashboard(ctx, dashboard_key)
    if not can_see_dashboard(ctx, d):
        raise ToolError("You can't see that dashboard.")
    w = next((x for x in d.widgets if x.title.lower() == str(widget).strip().lower() or str(x.id) == str(widget).strip()), None)
    if not w:
        raise ToolError(f"No widget '{widget}' on '{d.name}'. Widgets: " + "; ".join(x.title for x in d.widgets))
    if filters is None and ctx.scope is not None and ctx.dashboard is not None and d.id == ctx.dashboard.id:
        screen_filters = ctx.scope.screen_json.get("filters") or []
    else:
        screen_filters = filters or []
    raw = {"filters": screen_filters, "drill": {str(w.id): drill} if drill else {}}
    try:
        screen = actx.validate_screen(d, raw)
    except actx.ScreenStateError as e:
        raise ToolError(str(e)) from e
    spec = apply_dashboard_filters(QuerySpec.model_validate(w.spec), screen.filters)
    if w.id in screen.drill:
        spec.filters = spec.filters + screen.drill[w.id]
        nxt = ((w.options or {}).get("drill_path") or [None])[len(screen.drill[w.id]) - 1]
        if nxt:
            spec.dimensions, spec.sort, spec.limit = [Dimension(field=nxt)], [], None
    try:
        res = run_spec(ctx.db, ctx.cat, spec, ctx.user, source="dashboard", today=ctx.today)
    except (QueryError, QueryExecutionError, UnsafeSQLError) as e:
        raise ToolError(f"The widget could not be computed: {str(e).splitlines()[0][:300]}") from e
    in_force = "; ".join(f"{f.get('label') or f['id']} = {actx.describe_range(f.get('value')) if f['type'] == 'date_range' else (actx._value_text(f['value']) if actx.filter_is_set(f.get('value')) else 'All')}"
                         for f in screen.filters)
    notes = [f"{d.name} / {w.title}" + (f" with {in_force}" if in_force else "")]
    if drill:
        notes.append("Drilled into " + " > ".join(str(s.get("value")) for s in drill if isinstance(s, dict)))
    title = f"{w.title}" + (f" ({d.name})" if ctx.dashboard is None or d.id != ctx.dashboard.id else "")
    content, numbers = _result_for_model(res, title, notes)
    return ToolOutcome(content, label=title, data=_data(res, title, spec), numbers=numbers, notes=notes)


def describe_metric(ctx: ToolContext, name: str) -> ToolOutcome:
    mt = ctx.cat.metrics.get(str(name))
    if not mt:
        close = [n for n in ctx.cat.metrics if str(name).lower() in n.lower() or str(name).lower() in (ctx.cat.metrics[n].label or "").lower()]
        raise ToolError(f"No metric '{name}'." + (f" Did you mean: {', '.join(close[:8])}?" if close else ""))
    ds = ctx.cat.datasets.get(mt.dataset_id) if mt.dataset_id else None
    body = {"name": mt.name, "label": mt.label, "kind": mt.kind, "formula": mt.expression, "dataset": ds.slug if ds else None,
            "rules": [f"{f['column']} {f.get('op', 'eq')} {f.get('value')}" for f in mt.filters or []],
            "date_column": mt.time_column, "stock_like": bool(mt.semi_additive), "format": mt.format,
            "higher_is_better": bool(mt.higher_is_better), "synonyms": mt.synonyms or [], "description": mt.description or ""}
    text = json.dumps(body, ensure_ascii=False)
    return ToolOutcome(text, label=f"Definition of {mt.label}", numbers=parse_numbers(text))


def list_values(ctx: ToolContext, field: str, search: str | None = None) -> ToolOutcome:
    try:
        res = run_spec(ctx.db, ctx.cat, QuerySpec(dimensions=[Dimension(field=str(field))], limit=500), ctx.user,
                       source="ai", today=ctx.today)
    except (QueryError, QueryExecutionError, UnsafeSQLError, ValidationError, ValueError) as e:
        raise ToolError(f"Can't list values of '{field}': {str(e).splitlines()[0][:200]}") from e
    vals = [r[0] for r in res.get("rows") or [] if r and r[0] is not None]
    if search:
        vals = [v for v in vals if str(search).lower() in str(v).lower()]
    text = json.dumps({"field": field, "values": vals[:50], "more": max(0, len(vals) - 50)}, default=str, ensure_ascii=False)
    return ToolOutcome(text, label=f"Values of {field}", numbers=parse_numbers(" ".join(map(str, vals[:50]))))


def get_dashboard_context(ctx: ToolContext, dashboard_key: str) -> ToolOutcome:
    d = _dashboard(ctx, dashboard_key)
    if not can_see_dashboard(ctx, d):
        raise ToolError("You can't see that dashboard.")
    pack = actx.build_dashboard_pack(ctx.db, d, ctx.cat)
    return ToolOutcome(pack, label=f"About the {d.name} dashboard", numbers=parse_numbers(pack))


def get_data_issues(ctx: ToolContext, about: str | None = None) -> ToolOutcome:
    # The issue register arrives in Phase 5; until then the dashboard descriptions carry the known caveats.
    text = json.dumps({"issues": [], "note": "No issue register yet: rely on the caveats in the dashboard description."})
    return ToolOutcome(text, label="Known data issues")


def search_memory(ctx: ToolContext, query: str) -> ToolOutcome:
    from .. import memory

    found = memory.search(ctx.db, ctx.ws, ctx.user, str(query))
    ctx.found += [x for x in found if x not in ctx.found]
    text = json.dumps({"memories": [memory.describe(x, ctx.user)[2:] for x in found]
                       or "Nothing remembered about that."}, ensure_ascii=False)
    return ToolOutcome(text, label=f"Searching memory for “{str(query)[:60]}”", numbers=parse_numbers(text))


def propose_memory(ctx: ToolContext, text: str, kind: str, scope: str = "global", rationale: str = "",
                   share_with_team: bool = False) -> ToolOutcome:
    from .. import memory

    if len(ctx.saved) >= MAX_SAVES_PER_ANSWER:
        raise ToolError("At most 3 memories per answer.")
    # saved at once only when the user's own words asked for it; anything else waits for their approval
    status = "active" if ctx.explicit else "proposed"
    try:
        mem_scope = memory.resolve_scope(ctx.ws, ctx.db, scope, ctx.scope.dashboard_key if ctx.scope else None)
        mem, created = memory.save(ctx.db, ctx.ws, ctx.user, str(text), str(kind), mem_scope, str(rationale or ""),
                                   origin="explicit" if ctx.explicit else "inferred", status=status, cat=ctx.cat,
                                   conversation_id=ctx.conversation_id, message_id=ctx.message_id,
                                   excerpt=ctx.question, share=bool(share_with_team))
    except memory.MemoryInputError as e:
        raise ToolError(str(e)) from e
    from .. import audit

    audit.record(ctx.user, "memory_saved" if mem.status == "active" else "memory_proposed", ctx.ws.id, f"memory:{mem.id}",
                 {"kind": mem.kind, "scope": mem.scope, "origin": mem.origin, "created": created})
    if mem not in ctx.saved:
        ctx.saved.append(mem)
    said = ("Saved to memory" if mem.status == "active" else "Offered to the user to approve") if created \
        else "Already remembered"
    body = {"result": said, "memory_id": mem.id, "status": mem.status}
    if mem.share_status == "pending":
        body["team"] = "Suggested as a team fact: a workspace admin approves it."
    return ToolOutcome(json.dumps(body), label=f"Remembering: {mem.text[:60]}")


_IMPL = {"run_query": run_query, "get_widget_data": get_widget_data, "describe_metric": describe_metric,
         "list_values": list_values, "get_dashboard_context": get_dashboard_context, "get_data_issues": get_data_issues,
         "search_memory": search_memory, "propose_memory": propose_memory}
_ARGS = {"run_query": {"spec", "title"}, "get_widget_data": {"widget", "dashboard_key", "filters", "drill"},
         "describe_metric": {"name"}, "list_values": {"field", "search"}, "get_dashboard_context": {"dashboard_key"},
         "get_data_issues": {"about"}, "search_memory": {"query"},
         "propose_memory": {"text", "kind", "scope", "rationale", "share_with_team"}}
_MEMORY_TOOLS = {"search_memory", "propose_memory"}


def execute(ctx: ToolContext, name: str, args) -> ToolOutcome:
    """Run one tool call. Problems the model can fix come back as an error result; nothing here raises."""
    if name not in _IMPL or (name in _MEMORY_TOOLS and not ctx.memory_on):
        return ToolOutcome(f"Unknown tool '{name}'. Tools: {', '.join(TOOL_NAMES)}", ok=False, label=name)
    if not isinstance(args, dict):
        return ToolOutcome("Tool input must be a JSON object.", ok=False, label=name)
    clean = {k: v for k, v in args.items() if k in _ARGS[name]}
    try:
        return _IMPL[name](ctx, **clean)
    except ToolError as e:
        return ToolOutcome(str(e), ok=False, label=name)
    except TypeError as e:  # a required argument is missing
        return ToolOutcome(f"Bad input for {name}: {e}", ok=False, label=name)
    except Exception as e:  # noqa: BLE001  (never let one tool crash the answer)
        log.exception("tool %s failed", name)
        ctx.db.rollback()
        return ToolOutcome(f"{name} failed: {str(e).splitlines()[0][:200]}", ok=False, label=name)
