"""Optional OpenAI-compatible LLM integration (chat/completions)."""
from __future__ import annotations

import json
import re
from datetime import date

import httpx

from ...config import get_settings, today as _today
from ..catalog import Catalog
from .vocab import is_id_column

_transport: httpx.BaseTransport | None = None  # tests inject a MockTransport


class LLMError(RuntimeError):
    pass


def enabled() -> bool:
    s = get_settings()
    return bool(s.llm_base_url)


def chat(messages: list[dict], json_mode: bool = True, temperature: float = 0.0) -> str:
    s = get_settings()
    if not s.llm_base_url:
        raise LLMError("No LLM configured (set LLM_BASE_URL / LLM_API_KEY / LLM_MODEL)")
    headers = {"Content-Type": "application/json"}
    if s.llm_api_key:
        headers["Authorization"] = f"Bearer {s.llm_api_key}"
    body = {"model": s.llm_model, "messages": messages, "temperature": temperature}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    url = s.llm_base_url.rstrip("/") + "/chat/completions"
    try:
        with httpx.Client(timeout=s.llm_timeout_s, transport=_transport) as client:
            r = client.post(url, headers=headers, json=body)
            if r.status_code == 400 and json_mode:  # some servers lack response_format
                body.pop("response_format", None)
                r = client.post(url, headers=headers, json=body)
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as e:
        raise LLMError(f"LLM request failed: HTTP {e.response.status_code}") from e
    except (httpx.HTTPError, ValueError) as e:
        raise LLMError(f"LLM request failed: {e.__class__.__name__}") from e
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError("LLM returned an unexpected response shape") from e


def parse_json(text: str) -> dict:
    """Extract the first JSON object from model output (tolerates code fences / prose)."""
    t = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", t, re.S)
    if fence:
        t = fence.group(1)
    else:
        i, j = t.find("{"), t.rfind("}")
        if i < 0 or j < i:
            raise LLMError("LLM did not return JSON")
        t = t[i:j + 1]
    try:
        obj = json.loads(t)
    except json.JSONDecodeError as e:
        raise LLMError(f"LLM returned invalid JSON: {e.msg}") from e
    if not isinstance(obj, dict):
        raise LLMError("LLM JSON must be an object")
    return obj


def schema_context(cat: Catalog, values: dict | None = None, max_values: int = 12) -> str:
    lines = [f"PostgreSQL schema \"{cat.schema}\" (search_path is set to it; use bare table names)."]
    for ds in cat.datasets.values():
        lines.append(f"\nTABLE {ds.slug}  -- {ds.name}{' (query table)' if ds.kind == 'query_table' else ''}, {ds.row_count} rows"
                     + (f"; default date column {ds.default_date}" if ds.default_date else ""))
        for c in ds.columns.values():
            extra = ""
            vals = (values or {}).get((ds.id, c.name))
            if vals and not is_id_column(c.name):
                extra = "  values: " + ", ".join(repr(v) for v in vals[:max_values]) + (" ..." if len(vals) > max_values else "")
            lines.append(f"  {c.name} {c.type}  -- {c.label}{(': ' + c.description) if c.description else ''}{extra}")
    if cat.edges:
        lines.append("\nRELATIONSHIPS (many-to-one; join child to parent with LEFT JOIN):")
        for e in cat.edges:
            a, b = cat.datasets.get(e.from_ds), cat.datasets.get(e.to_ds)
            if a and b:
                lines.append(f"  {a.slug}.{e.from_col} -> {b.slug}.{e.to_col}")
    if cat.metrics:
        lines.append("\nMETRICS (semantic layer; prefer these definitions):")
        for mt in cat.metrics.values():
            ds = cat.datasets.get(mt.dataset_id) if mt.dataset_id else None
            filt = " AND ".join(f"{f['column']} {f.get('op', 'eq')} {f.get('value')!r}" for f in (mt.filters or []))
            lines.append(f"  {mt.name} ({mt.label}) = {mt.expression}" + (f" ON {ds.slug}" if ds else "")
                         + (f" WHERE {filt}" if filt else "") + (" [semi-additive: use latest snapshot per period]" if mt.semi_additive else "")
                         + (f"  synonyms: {', '.join(mt.synonyms)}" if mt.synonyms else "") + (f"  -- {mt.description}" if mt.description else ""))
    rules = [r for rs in cat.rules.values() for r in rs]
    if rules:
        lines.append("\nBUSINESS RULES (always apply as WHERE conditions on that table):")
        for r in rules:
            ds = cat.datasets.get(r.dataset_id)
            cond = " AND ".join(f"{f['column']} {f.get('op', 'eq')} {f.get('value')!r}" for f in (r.filters or []))
            lines.append(f"  {ds.slug if ds else '?'}: {cond}  -- {r.name}: {r.description}")
    if cat.glossary:
        lines.append("\nGLOSSARY:")
        for g in cat.glossary:
            tgt = g.metric_name or (f"{g.column}={g.value!r}" if g.value is not None else g.column)
            lines.append(f"  '{g.term}' ({', '.join(g.synonyms or [])}) -> {g.target_type} {tgt}")
    return "\n".join(lines)


SYSTEM_PROMPT = """You are an analytics engineer that answers business questions with ONE read-only PostgreSQL query.
Rules:
- Use only the tables and columns listed in the schema. Never invent tables, columns or values.
- Write a single SELECT (CTEs allowed). No INSERT/UPDATE/DELETE/DDL, no system catalogs, no functions starting with pg_.
- Prefer semantic-layer metric definitions and apply their filters and the business rules.
- Give every output column a short snake_case alias. Put dimensions first, then measures.
- For trends group by date_trunc('month', <date>)::date (or the grain asked). Today is {today}; "last month" means the previous complete calendar month.
- Limit result rows to at most 500.
- If the question cannot be answered from this schema, set "type" to "clarify" and explain what is missing.
Return JSON only: {{"type": "query"|"clarify", "sql": "...", "chart": "kpi|line|bar|stacked_bar|area|pie|donut|table|scatter|heatmap",
"title": "short title", "assumptions": ["..."], "clarification": "..."}}"""


def generate_sql(cat: Catalog, question: str, history: list[dict], values: dict | None = None, error_feedback: str | None = None) -> dict:
    msgs = [{"role": "system", "content": SYSTEM_PROMPT.format(today=_today().isoformat())},
            {"role": "system", "content": schema_context(cat, values)}]
    for h in history[-6:]:
        msgs.append({"role": h["role"], "content": h["content"][:2000]})
    msgs.append({"role": "user", "content": question})
    if error_feedback:
        msgs.append({"role": "user", "content": f"The previous SQL failed: {error_feedback}\nReturn corrected JSON."})
    return parse_json(chat(msgs))


def explain(question: str, columns: list[dict], rows: list[list], assumptions: list[str]) -> str:
    sample = rows[:40]
    msgs = [
        {"role": "system", "content": "You explain query results to business users in 2-4 sentences. Use ONLY the numbers given. "
                                      "Never invent data. Mention notable highs/lows or changes. No markdown headings."},
        {"role": "user", "content": json.dumps({"question": question, "columns": [c["label"] for c in columns], "rows": sample,
                                                "total_rows": len(rows), "assumptions": assumptions}, default=str)},
    ]
    return chat(msgs, json_mode=False, temperature=0.2).strip()
