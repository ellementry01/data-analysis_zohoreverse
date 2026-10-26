"""Run QuerySpecs: compile -> validate -> execute -> period comparison -> chart suggestion -> insights."""
from __future__ import annotations

import math
from datetime import date, timedelta

import numpy as np
from sqlalchemy.orm import Session

from .. import models as m
from ..config import get_settings
from .catalog import Catalog
from .executor import QueryExecutionError, log_query, run_readonly
from .filters import describe_range, previous_period
from .query_engine import Compiled, QueryError, compile_query
from .spec import QuerySpec
from .sql_safety import UnsafeSQLError, validate_select


def _check_compiled(cat: Catalog, compiled: Compiled) -> None:
    """Defence in depth: the compiler's own SQL must also pass the static validator."""
    allowed = {d.slug for d in cat.datasets.values()}
    validate_select(compiled.sql, cat.schema, allowed)


def run_spec(db: Session, cat: Catalog, spec: QuerySpec, user: str, source: str = "chart", today: date | None = None) -> dict:
    settings = get_settings()
    compiled = compile_query(cat, spec, today=today, max_rows=settings.query_row_limit)
    _check_compiled(cat, compiled)
    try:
        res = run_readonly(compiled.sql, compiled.params, cat.schema)
    except QueryExecutionError as e:
        log_query(db, cat.workspace_id, user, source, compiled.sql, "error", str(e))
        raise
    log_query(db, cat.workspace_id, user, source, compiled.sql, "ok", duration_ms=res.duration_ms, row_count=res.row_count)
    out = {
        "columns": [c.__dict__ for c in compiled.columns],
        "rows": res.rows,
        "row_count": res.row_count,
        "truncated": res.truncated,
        "duration_ms": res.duration_ms,
        "sql": _inline_sql(compiled.sql, compiled.params),
        "warnings": list(compiled.warnings),
        "date_range": [compiled.date_range[0].isoformat(), (compiled.date_range[1] - timedelta(days=1)).isoformat()]
        if compiled.date_range else None,
    }
    if spec.compare:
        _attach_comparison(db, cat, spec, compiled, out, user, today)
    out["suggested_chart"] = suggest_chart(out["columns"], out["rows"])
    out["insights"] = insights(out["columns"], out["rows"], limited=bool(spec.limit) or res.truncated)
    if out.get("comparison", {}).get("summary"):
        out["insights"].insert(0, {"type": "comparison", "text": out["comparison"]["summary"]})
    return out


def _inline_sql(sql: str, params: dict) -> str:
    """Readable SQL for the inspection panel (values shown inline; execution always uses bound params)."""
    def lit(v):
        if v is None:
            return "NULL"
        if isinstance(v, bool):
            return "TRUE" if v else "FALSE"
        if isinstance(v, (int, float)):
            return repr(v)
        return "'" + str(v).replace("'", "''") + "'"
    for k in sorted(params, key=len, reverse=True):
        sql = sql.replace(f":{k}", lit(params[k]))
    return sql


def _attach_comparison(db, cat, spec: QuerySpec, compiled: Compiled, out: dict, user: str, today) -> None:
    if not compiled.date_range:
        out["warnings"].append("Period comparison needs a date range")
        return
    lo, hi = compiled.date_range
    plo, phi = previous_period(lo, hi, spec.compare)
    prev_spec = spec.model_copy(deep=True)
    prev_spec.time_range = {"from": plo.isoformat(), "to": (phi - timedelta(days=1)).isoformat()}
    prev_spec.compare = None
    prev_spec.limit = None
    pc = compile_query(cat, prev_spec, today=today)
    _check_compiled(cat, pc)
    prev = run_readonly(pc.sql, pc.params, cat.schema)
    log_query(db, cat.workspace_id, user, "chart", pc.sql, "ok", duration_ms=prev.duration_ms, row_count=prev.row_count)

    cols = out["columns"]
    dims = [i for i, c in enumerate(cols) if c["role"] == "dimension"]
    meas = [i for i, c in enumerate(cols) if c["role"] == "measure"]
    time_idx = next((i for i in dims if cols[i]["type"] in ("date", "datetime")), None)
    month_aligned = lo.day == 1 and hi.day == 1
    months = (lo.year - plo.year) * 12 + lo.month - plo.month

    def shift(v):
        if v is None:
            return None
        d = date.fromisoformat(str(v)[:10])
        if month_aligned or spec.compare == "previous_year":
            y, mth = d.year, d.month + months
            y += (mth - 1) // 12
            mth = (mth - 1) % 12 + 1
            try:
                return date(y, mth, d.day).isoformat()
            except ValueError:
                return date(y, mth, 28).isoformat()
        return (d + (lo - plo)).isoformat()

    prev_map = {}
    for r in prev.rows:
        key = tuple(shift(r[i]) if i == time_idx else r[i] for i in dims)
        prev_map[key] = r
    for i in meas:
        c = cols[i]
        cols.append({**c, "name": c["name"] + "__prev", "label": c["label"] + " (previous)", "role": "measure", "compare_of": c["name"]})
    for i in meas:
        c = cols[i]
        cols.append({**c, "name": c["name"] + "__change_pct", "label": c["label"] + " change %", "role": "measure",
                     "format": "percent", "compare_of": c["name"]})
    for r in out["rows"]:
        key = tuple(str(r[i])[:10] if i == time_idx and r[i] is not None else r[i] for i in dims)
        p = prev_map.get(key)
        prevs = [p[i] if p else None for i in meas]
        r.extend(prevs)
        for cur_i, pv in zip(meas, prevs):
            cv = r[cur_i]
            r.append(round((cv - pv) / abs(pv), 4) if cv is not None and pv not in (None, 0) else None)
    out["comparison"] = {"mode": spec.compare, "previous_range": describe_range(plo, phi), "current_range": describe_range(lo, hi)}
    if dims and meas:  # overall change for additive measures across all rows
        parts = []
        n = len(meas)
        for k, i in enumerate(meas):
            c = cols[i]
            if not c.get("additive", True):
                continue
            cur = sum(r[i] for r in out["rows"] if r[i] is not None)
            prv = sum(r[len(r) - 2 * n + k] for r in out["rows"] if r[len(r) - 2 * n + k] is not None)
            if prv:
                parts.append(f"{c['label']} totals {fmt(cur, c.get('format'))}, {'up' if cur >= prv else 'down'} "
                             f"{abs(cur - prv) / abs(prv):.1%} versus {fmt(prv, c.get('format'))} in "
                             f"{'the same period last year' if spec.compare == 'previous_year' else 'the previous period'}")
        if parts:
            out["comparison"]["summary"] = "Overall: " + "; ".join(parts) + "."


# ----------------------------------------------------------------------------------------------- charts

def suggest_chart(columns: list[dict], rows: list[list]) -> str:
    dims = [c for c in columns if c["role"] == "dimension"]
    meas = [c for c in columns if c["role"] == "measure" and not c.get("compare_of")]
    if not dims:
        return "kpi"
    if not meas:  # a plain list of values (e.g. dashboard filter options)
        return "table"
    time_dims = [d for d in dims if d["type"] in ("date", "datetime")]
    if time_dims:
        return "line" if len(dims) <= 2 else "table"
    if len(dims) == 1:
        if len(meas) == 2 and len(rows) > 8:
            return "scatter"
        additive = all(m.get("additive", True) for m in meas)
        return "bar" if len(rows) > 6 or len(meas) > 1 or not additive else "pie" if all((r[-1] or 0) >= 0 for r in rows) and len(rows) > 1 else "bar"
    if len(dims) == 2 and len(meas) == 1:
        a = len({r[0] for r in rows})
        b = len({r[1] for r in rows})
        return "heatmap" if a > 8 and b > 8 else "stacked_bar"
    return "table"


# ----------------------------------------------------------------------------------------------- insights

def insights(columns: list[dict], rows: list[list], limited: bool = False) -> list[dict]:
    out: list[dict] = []
    if not rows:
        return [{"type": "empty", "text": "No rows match this question and its filters."}]
    dims = [i for i, c in enumerate(columns) if c["role"] == "dimension"]
    meas = [i for i, c in enumerate(columns) if c["role"] == "measure" and not c.get("compare_of")]
    time_idx = next((i for i in dims if columns[i]["type"] in ("date", "datetime")), None)
    other_dims = [i for i in dims if i != time_idx]
    partial = None
    if time_idx is not None and rows:
        partial = _partial_period(columns[time_idx].get("grain"), rows[-1][time_idx])
        if partial:
            out.append({"type": "partial", "text": f"The latest period ({rows[-1][time_idx]}) is still in progress, so it is left out of trend and change calculations."})
    full_rows = rows[:-1] if partial and len(rows) > 2 else rows
    if time_idx is not None and len(other_dims) == 1 and meas:
        out.extend(_multi_series_insights(columns, full_rows, time_idx, other_dims[0], meas[0]))
    if time_idx is not None and not other_dims and len(meas) >= 2:
        a = [r[meas[0]] for r in full_rows]
        b = [r[meas[1]] for r in full_rows]
        pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
        if len(pairs) >= 4:
            r_ = float(np.corrcoef([p[0] for p in pairs], [p[1] for p in pairs])[0, 1])
            strength = "strong" if abs(r_) > 0.7 else "moderate" if abs(r_) > 0.4 else "weak"
            out.append({"type": "correlation", "text": f"{columns[meas[0]]['label']} and {columns[meas[1]]['label']} move together with a "
                                                       f"{strength} {'positive' if r_ >= 0 else 'negative'} correlation (r = {r_:.2f})."})
            ratio = sum(p[1] for p in pairs) / (sum(p[0] for p in pairs) or 1)
            out.append({"type": "ratio", "text": f"Over the period, {columns[meas[1]]['label']} is {ratio:.2f}× {columns[meas[0]]['label']}."})
    for mi in meas[:3]:
        label = columns[mi]["label"]
        if time_idx is not None and not other_dims:
            pts = [(r[time_idx], r[mi]) for r in full_rows if r[mi] is not None]
            if len(pts) >= 2:
                out.extend(_series_insights(label, pts, columns[mi].get("format", "number")))
        elif len(dims) == 1 and time_idx is None:
            vals = [(r[dims[0]], r[mi]) for r in rows if r[mi] is not None]
            total = sum(v for _, v in vals if v and v > 0)
            if vals and total:
                top = max(vals, key=lambda x: x[1])
                low = min(vals, key=lambda x: x[1])
                share = f", {top[1] / total:.0%} of the total" if columns[mi].get("additive", True) and not limited else ""
                out.append({"type": "top", "measure": columns[mi]["name"], "text":
                            f"{top[0]} has the highest {label} ({fmt(top[1], columns[mi].get('format'))}{share})."})
                if len(vals) > 2:
                    out.append({"type": "bottom", "measure": columns[mi]["name"], "text":
                                f"{low[0]} has the lowest {label} ({fmt(low[1], columns[mi].get('format'))})."})
    for c in columns:
        if c.get("format") == "percent" and c["name"].endswith("__change_pct"):
            idx = columns.index(c)
            vals = [r[idx] for r in rows if r[idx] is not None]
            if len(rows) == 1 and vals:
                base = c["label"].replace(" change %", "")
                out.append({"type": "comparison", "text": f"{base} is {'up' if vals[0] >= 0 else 'down'} {abs(vals[0]):.1%} versus the previous period."})
    return out


def _partial_period(grain: str | None, value) -> bool:
    """True when the bucket containing `value` has not finished yet."""
    from ..config import today as _today

    if not grain or value is None:
        return False
    try:
        d = date.fromisoformat(str(value)[:10])
    except ValueError:
        return False
    t = _today()
    if grain == "day":
        return d >= t
    if grain == "week":
        return d + timedelta(days=7) > t
    if grain == "month":
        return (d.year, d.month) >= (t.year, t.month)
    if grain == "quarter":
        return (d.year, (d.month - 1) // 3) >= (t.year, (t.month - 1) // 3)
    if grain == "year":
        return d.year >= t.year
    return False


def _multi_series_insights(columns, rows, t_idx, s_idx, m_idx) -> list[dict]:
    label = columns[m_idx]["label"]
    f = columns[m_idx].get("format", "number")
    series: dict = {}
    for r in rows:
        if r[m_idx] is not None:
            series.setdefault(r[s_idx], []).append((r[t_idx], float(r[m_idx])))
    if not series:
        return []
    totals = {k: sum(v for _, v in pts) for k, pts in series.items()}
    grand = sum(totals.values()) or 1
    ranked = sorted(totals.items(), key=lambda x: -x[1])
    out = [{"type": "series_total", "text": "Totals: " + "; ".join(
        f"{k} {fmt(v, f)} ({v / grand:.0%})" for k, v in ranked[:5]) + "."}]
    for k, pts in list(series.items())[:5]:
        pts.sort(key=lambda p: str(p[0]))
        if len(pts) >= 2 and pts[0][1]:
            ch = (pts[-1][1] - pts[0][1]) / abs(pts[0][1])
            out.append({"type": "series_change", "text": f"{k}: {label} {'rose' if ch >= 0 else 'fell'} {abs(ch):.1%} from {pts[0][0]} to {pts[-1][0]}."})
    if len(ranked) >= 2:
        lead = sum(1 for t in {p[0] for pts in series.values() for p in pts}
                   if max(series, key=lambda k: dict(series[k]).get(t, float("-inf"))) == ranked[0][0])
        periods = len({p[0] for pts in series.values() for p in pts})
        out.append({"type": "leader", "text": f"{ranked[0][0]} leads in {lead} of {periods} periods."})
    return out


def _series_insights(label: str, pts: list, f: str) -> list[dict]:
    res = []
    vals = np.array([float(v) for _, v in pts])
    first, last = vals[0], vals[-1]
    if len(vals) >= 3:
        x = np.arange(len(vals))
        slope, intercept = np.polyfit(x, vals, 1)
        fit = slope * x + intercept
        ss_res = float(((vals - fit) ** 2).sum())
        ss_tot = float(((vals - vals.mean()) ** 2).sum()) or 1.0
        r2 = 1 - ss_res / ss_tot
        mean = abs(vals.mean()) or 1.0
        rel = slope / mean
        if r2 > 0.3 and abs(rel) > 0.01:
            res.append({"type": "trend", "direction": "up" if slope > 0 else "down", "text":
                        f"{label} shows a {'rising' if slope > 0 else 'falling'} trend (about {abs(rel):.1%} of the average per period, R² {r2:.2f})."})
        else:
            res.append({"type": "trend", "direction": "flat", "text": f"{label} has no clear trend over this period."})
        res.extend(detect_anomalies(label, pts, vals, f))
    if first:
        ch = (last - first) / abs(first)
        res.append({"type": "change", "text": f"{label} went from {fmt(first, f)} ({pts[0][0]}) to {fmt(last, f)} ({pts[-1][0]}), {'+' if ch >= 0 else ''}{ch:.1%}."})
    peak = int(vals.argmax())
    res.append({"type": "peak", "text": f"Peak {label}: {fmt(vals[peak], f)} in {pts[peak][0]}."})
    return res


def detect_anomalies(label: str, pts: list, vals: np.ndarray, f: str = "number", threshold: float = 3.0) -> list[dict]:
    """Robust z-score on residuals from a rolling median (needs >= 7 points)."""
    if len(vals) < 7:
        return []
    k = 5
    med = np.array([np.median(vals[max(0, i - k // 2): i + k // 2 + 1]) for i in range(len(vals))])
    resid = vals - med
    mad = np.median(np.abs(resid - np.median(resid))) or (np.std(resid) or 1.0)
    z = 0.6745 * (resid - np.median(resid)) / mad
    out = []
    for i in np.where(np.abs(z) > threshold)[0]:
        out.append({"type": "anomaly", "index": int(i), "x": pts[i][0], "value": float(vals[i]), "expected": float(med[i]),
                    "text": f"Unusual {label} in {pts[i][0]}: {fmt(vals[i], f)} vs ~{fmt(med[i], f)} expected ({'above' if resid[i] > 0 else 'below'})."})
    return out[:5]


def fmt(v, f: str | None = "number") -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "–"
    v = float(v)
    if f == "percent":
        return f"{v:.1%}"
    a = abs(v)
    s = f"{v / 1e7:.2f} Cr" if a >= 1e7 else f"{v / 1e5:.2f} L" if a >= 1e5 else f"{v:,.0f}" if a >= 100 or v.is_integer() else f"{v:,.2f}"
    return ("₹" + s) if f == "currency" else s


__all__ = ["run_spec", "suggest_chart", "insights", "QueryError", "UnsafeSQLError", "QueryExecutionError"]
