"""Conversational analytics orchestration.

Pipeline: interpret (semantic engine first, optional LLM fallback / preference) -> compile/validate ->
read-only execution -> chart choice -> explanation grounded in the returned rows -> persist conversation.
The assistant never reports numbers that did not come back from the database.
"""
from __future__ import annotations

import logging
from datetime import date

from sqlalchemy.orm import Session

from ... import models as m
from ..analytics import fmt, insights, run_spec, suggest_chart
from ..catalog import Catalog, load_catalog
from ..executor import QueryExecutionError, log_query, run_readonly
from ..naming import slugify
from ..query_engine import QueryError
from ..spec import QuerySpec
from ..sql_safety import UnsafeSQLError, validate_select
from . import claude, llm
from .parser import Interpretation, interpret, suggest_questions
from .vocab import build_vocab, value_index

log = logging.getLogger(__name__)
STORE_ROWS = 500


def _assign_aliases(spec: QuerySpec) -> None:
    used: set[str] = set()
    for ms in spec.measures:
        if not ms.alias:
            base = ms.metric or (ms.field.replace(".*", "_count").split(".")[-1] + ("" if ms.field.endswith(".*") else f"_{ms.agg}"))
            a = slugify(base, "m")
            i = 2
            while a in used:
                a = f"{slugify(base, 'm')}_{i}"
                i += 1
            ms.alias = a
        used.add(ms.alias)
    for s in spec.sort:
        if s.field == "__first_measure__" and spec.measures:
            s.field = spec.measures[0].alias


def _prev_spec(conv: m.Conversation | None) -> QuerySpec | None:
    if not conv:
        return None
    for msg in reversed(conv.messages):
        if msg.role == "assistant" and (msg.payload or {}).get("spec"):
            try:
                return QuerySpec.model_validate(msg.payload["spec"])
            except Exception:
                return None
    return None


def _history(conv: m.Conversation | None) -> list[dict]:
    out = []
    if not conv:
        return out
    for msg in conv.messages[-8:]:
        content = msg.content
        if msg.role == "assistant" and (msg.payload or {}).get("sql"):
            content += f"\nSQL used: {msg.payload['sql'][:1500]}"
        out.append({"role": msg.role, "content": content})
    return out


def _rules_note(cat: Catalog, spec: QuerySpec) -> list[str]:
    from .parser import _bases

    notes = []
    if not spec.apply_rules:
        return notes
    for b in _bases(cat, spec.measures):
        for r in cat.rules.get(b, []):
            notes.append(f"Business rule applied on {cat.datasets[b].name}: {r.name}")
    for ms in spec.measures:
        mt = cat.metrics.get(ms.metric) if ms.metric else None
        if mt and mt.filters:
            conds = ", ".join(f"{f['column']} {f.get('op', 'eq').replace('_', ' ')} {f.get('value')}" for f in mt.filters)
            notes.append(f"{mt.label} counts only rows where {conds}")
    return notes


def template_explanation(title: str, result: dict, assumptions: list[str]) -> str:
    cols, rows = result["columns"], result["rows"]
    if not rows:
        return "The query ran successfully but returned no rows for this question and its filters."
    dims = [c for c in cols if c["role"] == "dimension"]
    meas = [c for c in cols if c["role"] == "measure" and not c.get("compare_of")]
    period = f" ({result['date_range'][0]} to {result['date_range'][1]})" if result.get("date_range") else " (all available data)"
    if meas and all(r[cols.index(c)] is None for r in rows for c in meas):
        return ("There is no data for this" + period.rstrip() + ". The query ran correctly, but the underlying dataset has no "
                "matching rows — check that the source data has been loaded and synced.")
    parts = []
    if not dims and meas:
        vals = [f"{c['label']}: {fmt(rows[0][cols.index(c)], c.get('format'))}" for c in meas]
        parts.append("; ".join(vals) + period + ".")
        comp = [c for c in cols if c["name"].endswith("__change_pct")]
        for c in comp:
            v = rows[0][cols.index(c)]
            prev = next((x for x in cols if x["name"] == c["name"].replace("__change_pct", "__prev")), None)
            if v is not None and prev:
                parts.append(f"That is {'up' if v >= 0 else 'down'} {abs(v):.1%} from {fmt(rows[0][cols.index(prev)], prev.get('format'))} in the previous period ({result.get('comparison', {}).get('previous_range', '')}).")
    else:
        parts.append(f"{len(rows)} row{'s' if len(rows) != 1 else ''}{period}.")
        for ins in result.get("insights", [])[:6]:
            parts.append(ins["text"])
    if result.get("truncated"):
        parts.append("Results were truncated to the row limit.")
    return " ".join(parts)


def _trend_filter(result: dict, post: dict) -> dict:
    cols = result["columns"]
    meas = [c for c in cols if c["role"] == "measure" and not c.get("compare_of")]
    if len(meas) < 2:
        return result
    ch = {c["compare_of"]: cols.index(c) for c in cols if c["name"].endswith("__change_pct")}
    pv = {c["compare_of"]: cols.index(c) for c in cols if c["name"].endswith("__prev")}
    a, b = meas[0], meas[1]
    ia, ib = cols.index(a), cols.index(b)

    def direction(cur, prev, want):
        if cur is None or prev is None:
            return False
        return cur < prev if want == "down" else cur > prev

    kept = [r for r in result["rows"] if direction(r[ia], r[pv[a["name"]]], post["first"]) and direction(r[ib], r[pv[b["name"]]], post["second"])]
    kept.sort(key=lambda r: (r[ch[a["name"]]] if r[ch[a["name"]]] is not None else 0))
    result = {**result, "rows": kept, "row_count": len(kept)}
    result["insights"] = [{"type": "filter", "text":
                           f"{len(kept)} item(s) where {a['label']} is {'down' if post['first'] == 'down' else 'up'} and "
                           f"{b['label']} is {'up' if post['second'] == 'up' else 'down'} versus the previous period "
                           f"({result.get('comparison', {}).get('previous_range', '')} → {result.get('comparison', {}).get('current_range', '')})."}]
    return result


def answer(db: Session, ws: m.Workspace, user: str, question: str, conversation_id: int | None = None,
           engine: str = "auto", today: date | None = None) -> dict:
    question = (question or "").strip()
    if not question:
        raise ValueError("Ask a question")
    conv = db.get(m.Conversation, conversation_id) if conversation_id else None
    if conv and (conv.workspace_id != ws.id or conv.user_email != user):  # never continue someone else's conversation
        conv = None
    if not conv:
        conv = m.Conversation(workspace_id=ws.id, title=question[:200], user_email=user)
        db.add(conv)
        db.flush()
    prev = _prev_spec(conv)
    history = _history(conv)
    conv.messages.append(m.Message(role="user", content=question))
    db.commit()
    conv_id = conv.id

    cat = load_catalog(db, ws)
    payload: dict = {"engine": None}
    try:
        payload = _answer(db, ws, cat, user, question, prev, history, engine, today)
    except Exception as e:  # never leave the user without a truthful message
        log.exception("assistant failure")
        db.rollback()
        conv = db.get(m.Conversation, conv_id)
        payload = {"type": "error", "text": f"Sorry, I could not answer that: {str(e).splitlines()[0]}", "engine": payload.get("engine")}
    stored = {**payload}
    if "rows" in stored:
        stored["rows"] = stored["rows"][:STORE_ROWS]
    msg = m.Message(role="assistant", content=payload.get("text", ""), payload=stored)
    conv.messages.append(msg)
    db.commit()
    return {**payload, "conversation_id": conv.id, "message_id": msg.id}


def _answer(db, ws, cat, user, question, prev, history, engine, today) -> dict:
    if not cat.datasets:
        return {"type": "clarify", "text": "This workspace has no data yet. Import a file or connect a database first.", "engine": "semantic"}
    values = value_index(cat)
    vocab = build_vocab(cat, values)

    if claude.enabled() and engine in ("auto", "llm"):
        interp = interpret(question, cat, vocab, prev)  # cheap: intent detection + routing hints
        if interp.kind in ("chitchat", "help"):
            return {"type": "help", "engine": "semantic", "text": "Ask me about your data, for example:" if interp.kind == "help"
                    else "Hi! Ask me a question about your data.", "suggestions": suggest_questions(cat)}
        if interp.kind == "dashboard":
            return _make_dashboard(db, ws, cat, user, interp, today)
        try:
            return _run_claude(db, cat, user, question, history, values, today, interp)
        except claude.ClaudeUnavailable as e:
            log.warning("Claude unavailable, answering offline: %s", e)
            note = f"The AI model is unavailable right now ({str(e)[:120]}), so this was answered by the offline engine."
            if interp.kind in ("query", "trend_compare"):
                try:
                    out = _run_semantic(db, cat, user, question, interp, today, use_llm_text=False)
                    out["assumptions"] = [note] + out.get("assumptions", [])
                    return out
                except (QueryError, QueryExecutionError, UnsafeSQLError):
                    pass
            return {"type": "clarify", "engine": "semantic", "text": note + " " + (interp.clarification or ""),
                    "suggestions": interp.suggestions or suggest_questions(cat)}

    use_llm = llm.enabled() and engine in ("auto", "llm")

    interp: Interpretation | None = None
    if engine != "llm" or not use_llm:
        interp = interpret(question, cat, vocab, prev)
        if interp.kind in ("chitchat", "help"):
            return {"type": "help", "engine": "semantic", "text": "Ask me about your data, for example:" if interp.kind == "help"
                    else "Hi! Ask me a question about your data.", "suggestions": suggest_questions(cat)}
        if interp.kind == "dashboard":
            return _make_dashboard(db, ws, cat, user, interp, today)
        if interp.kind in ("query", "trend_compare"):
            try:
                return _run_semantic(db, cat, user, question, interp, today)
            except (QueryError, QueryExecutionError, UnsafeSQLError) as e:
                if not use_llm:
                    return {"type": "clarify", "engine": "semantic", "text": f"I understood the question but could not run it: {e}",
                            "spec": interp.spec.model_dump() if interp.spec else None, "assumptions": interp.assumptions}
        elif not use_llm:
            return {"type": "clarify", "engine": "semantic", "text": interp.clarification, "suggestions": interp.suggestions}
    return _run_llm(db, cat, user, question, history, values, today, fallback=interp)


def _run_claude(db, cat, user, question, history, values, today, interp: Interpretation) -> dict:
    """Claude plans the query (spec preferred, SQL as fallback); Haiku first unless the question is complex,
    with a single escalation to Sonnet when a plan fails validation or execution."""
    from .parser import _bases

    spec_hint = interp.spec if interp.kind in ("query", "trend_compare") else None
    r = claude.route(question, measures=len(spec_hint.measures) if spec_hint else 0,
                     dimensions=len(spec_hint.dimensions) if spec_hint else 0,
                     datasets=len(_bases(cat, spec_hint.measures)) if spec_hint else 0)
    feedback, last_err = None, None
    usage_total: dict = {}
    allowed = {d.slug for d in cat.datasets.values()}
    for attempt in range(2):
        try:
            p = claude.plan(cat, question, history, values, r, feedback)
        except claude.ClaudeError as e:
            last_err = str(e)
            if attempt == 0:
                feedback, r = str(e), (claude.escalate(r, "invalid plan") if r.tier == "simple" else r)
                continue
            break
        for k, v in p.usage.items():
            usage_total[k] = usage_total.get(k, 0) + v
        meta = {"engine": "claude", "model": p.model, "model_label": claude.label(p.model), "routing": r.reasons,
                "escalated": r.escalated, "usage": usage_total}
        if p.kind == "clarify":
            # Haiku asking for clarification on something the offline engine could already map is worth one Sonnet look.
            if attempt == 0 and r.tier == "simple" and interp.kind in ("query", "trend_compare"):
                feedback, r = "You asked for clarification, but the question maps to the schema; plan it if at all possible.", \
                    claude.escalate(r, "clarification on an answerable question")
                continue
            return {"type": "clarify", "text": p.clarification or "Could you clarify the question?",
                    "suggestions": suggest_questions(cat), **meta}
        try:
            if p.kind == "spec":
                spec = QuerySpec.model_validate(p.spec)
                _assign_aliases(spec)
                result = run_spec(db, cat, spec, user, source="ai", today=today)
                assumptions = p.assumptions + _rules_note(cat, spec)
                spec_out = spec.model_dump()
            else:
                safe = validate_select(p.sql, cat.schema, allowed, row_limit=None)
                res = run_readonly(f"SELECT * FROM ({safe}) _ai LIMIT 500", {}, cat.schema)
                log_query(db, cat.workspace_id, user, "ai", safe, "ok", duration_ms=res.duration_ms, row_count=res.row_count)
                columns = _infer_columns(res.columns, res.rows)
                result = {"columns": columns, "rows": res.rows, "row_count": res.row_count, "truncated": res.truncated,
                          "sql": safe, "warnings": [], "date_range": None, "duration_ms": res.duration_ms,
                          "insights": insights(columns, res.rows)}
                assumptions, spec_out = p.assumptions, None
        except (ValueError, QueryError, QueryExecutionError, UnsafeSQLError) as e:
            msg = str(e).splitlines()[0][:400]
            if p.kind == "sql":
                log_query(db, cat.workspace_id, user, "ai", p.sql, "rejected" if isinstance(e, UnsafeSQLError) else "error", msg)
            last_err = msg
            if attempt == 0:
                feedback = f"{'Spec' if p.kind == 'spec' else 'SQL'} failed: {msg}"
                if r.tier == "simple":
                    r = claude.escalate(r, "plan failed validation")
                continue
            break
        try:
            text = claude.explain(question, result["columns"], result["rows"], assumptions)
        except (claude.ClaudeError, claude.ClaudeUnavailable):
            text = template_explanation(p.title, result, assumptions)
        chart = p.chart or suggest_chart(result["columns"], result["rows"])
        if not p.chart and chart in ("pie", "donut") and spec_out and spec_out.get("limit"):
            chart = "bar"
        return {"type": "answer", "title": p.title, "chart_type": chart, "text": text, "assumptions": assumptions,
                "spec": spec_out, **{k: result.get(k) for k in ("columns", "rows", "row_count", "truncated", "sql", "warnings",
                                                                 "insights", "date_range", "duration_ms")},
                "comparison": result.get("comparison"), **meta}
    return {"type": "error", "engine": "claude", "model": r.model, "model_label": claude.label(r.model), "routing": r.reasons,
            "escalated": r.escalated, "text": f"I couldn't build a valid query for that ({last_err}). Try rephrasing, "
                                             f"or name the metric and breakdown you want."}


def _run_semantic(db, cat, user, question, interp: Interpretation, today, use_llm_text: bool = True) -> dict:
    spec = interp.spec
    _assign_aliases(spec)
    result = run_spec(db, cat, spec, user, source="ai", today=today)
    if interp.kind == "trend_compare":
        result = _trend_filter(result, interp.post_filter)
    chart = interp.chart or (suggest_chart(result["columns"], result["rows"]) if interp.kind == "query" else "table")
    if not interp.chart and chart in ("pie", "donut") and spec.limit:
        chart = "bar"  # a top-N list is not a whole, so shares would mislead
    if interp.kind == "trend_compare":
        chart = interp.chart or "table"
    assumptions = interp.assumptions + _rules_note(cat, spec)
    text = None
    if use_llm_text and llm.enabled():
        try:
            text = llm.explain(question, result["columns"], result["rows"], assumptions)
        except llm.LLMError:
            text = None
    text = text or template_explanation(interp.title, result, assumptions)
    return {"type": "answer", "engine": "semantic", "title": interp.title, "chart_type": chart, "spec": spec.model_dump(),
            "text": text, "assumptions": assumptions, **{k: result[k] for k in (
                "columns", "rows", "row_count", "truncated", "sql", "warnings", "insights", "date_range", "duration_ms")},
            "comparison": result.get("comparison")}


def _run_llm(db, cat, user, question, history, values, today, fallback: Interpretation | None) -> dict:
    allowed = {d.slug for d in cat.datasets.values()}
    feedback = None
    last_err = None
    for attempt in range(2):
        try:
            out = llm.generate_sql(cat, question, history, values, feedback)
        except llm.LLMError as e:
            last_err = str(e)
            break
        if out.get("type") == "clarify" or not out.get("sql"):
            return {"type": "clarify", "engine": "llm", "text": out.get("clarification") or "Could you clarify the question?",
                    "suggestions": suggest_questions(cat)}
        sql = out["sql"]
        try:
            safe = validate_select(sql, cat.schema, allowed, row_limit=None)
            res = run_readonly(f"SELECT * FROM ({safe}) _ai LIMIT 500", {}, cat.schema)
        except UnsafeSQLError as e:
            log_query(db, cat.workspace_id, user, "ai", sql, "rejected", str(e))
            feedback, last_err = f"Rejected by the safety validator: {e}", str(e)
            continue
        except QueryExecutionError as e:
            log_query(db, cat.workspace_id, user, "ai", sql, "error", str(e))
            feedback, last_err = str(e), str(e)
            continue
        log_query(db, cat.workspace_id, user, "ai", safe, "ok", duration_ms=res.duration_ms, row_count=res.row_count)
        columns = _infer_columns(res.columns, res.rows)
        result = {"columns": columns, "rows": res.rows, "row_count": res.row_count, "truncated": res.truncated,
                  "sql": safe, "warnings": [], "date_range": None, "duration_ms": res.duration_ms}
        result["insights"] = insights(columns, res.rows)
        assumptions = list(out.get("assumptions") or [])
        try:
            text = llm.explain(question, columns, res.rows, assumptions)
        except llm.LLMError:
            text = template_explanation(out.get("title", question), result, assumptions)
        chart = out.get("chart") or suggest_chart(columns, res.rows)
        return {"type": "answer", "engine": "llm", "title": out.get("title") or question, "chart_type": chart, "text": text,
                "assumptions": assumptions, "spec": None, **result}
    msg = f"The AI model could not produce a valid query ({last_err})."
    if fallback and fallback.kind == "clarify":
        return {"type": "clarify", "engine": "semantic", "text": fallback.clarification + " " + msg, "suggestions": fallback.suggestions}
    return {"type": "error", "engine": "llm", "text": msg}


def _infer_columns(names: list[str], rows: list[list]) -> list[dict]:
    cols = []
    for i, n in enumerate(names):
        vals = [r[i] for r in rows if r[i] is not None]
        is_num = bool(vals) and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals)
        is_date = bool(vals) and all(isinstance(v, str) and len(v) >= 10 and v[4] == "-" and v[7] == "-" for v in vals[:20])
        role = "measure" if is_num and not n.endswith(("_id", "year")) else "dimension"
        cols.append({"name": n, "label": n.replace("_", " ").capitalize(), "role": role,
                     "type": "decimal" if is_num else "date" if is_date else "text", "format": "number"})
    if cols and all(c["role"] == "measure" for c in cols) and len(rows) > 1:
        cols[0]["role"] = "dimension"
    return cols


def _make_dashboard(db, ws, cat, user, interp: Interpretation, today) -> dict:
    dash = m.Dashboard(workspace_id=ws.id, name=interp.title[:200] or "AI dashboard",
                       description="Created by the AI assistant",
                       filters=[{"id": "date", "type": "date_range", "label": "Date range", "field": "@time", "value": None}])
    x_kpi, y = 0, 0
    built = []
    errors = []
    kpis = [w for w in interp.widgets if w[2] == "kpi"]
    charts = [w for w in interp.widgets if w[2] != "kpi"]
    for i, (title, spec, chart) in enumerate(kpis):
        _assign_aliases(spec)
        try:
            run_spec(db, cat, spec, user, source="ai", today=today)  # validate before saving
        except (QueryError, QueryExecutionError, UnsafeSQLError) as e:
            errors.append(f"{title}: {e}")
            continue
        dash.widgets.append(m.DashboardWidget(title=title, chart_type=chart, spec=spec.model_dump(),
                                              layout={"x": (x_kpi % 4) * 3, "y": 0, "w": 3, "h": 2}))
        x_kpi += 1
        built.append(title)
    y = 2
    for i, (title, spec, chart) in enumerate(charts):
        _assign_aliases(spec)
        try:
            run_spec(db, cat, spec, user, source="ai", today=today)
        except (QueryError, QueryExecutionError, UnsafeSQLError) as e:
            errors.append(f"{title}: {e}")
            continue
        dash.widgets.append(m.DashboardWidget(title=title, chart_type=chart, spec=spec.model_dump(),
                                              layout={"x": (i % 2) * 6, "y": y + (i // 2) * 4, "w": 6, "h": 4}))
        built.append(title)
    if not dash.widgets:
        return {"type": "error", "engine": "semantic", "text": "I could not build any widget: " + "; ".join(errors)}
    db.add(dash)
    db.flush()
    text = f"Created dashboard '{dash.name}' with {len(dash.widgets)} widgets: {', '.join(built)}."
    if errors:
        text += " Skipped: " + "; ".join(errors)
    if interp.assumptions:
        text += " (" + "; ".join(interp.assumptions) + ")"
    return {"type": "dashboard", "engine": "semantic", "text": text, "dashboard_id": dash.id, "title": dash.name,
            "assumptions": interp.assumptions}
