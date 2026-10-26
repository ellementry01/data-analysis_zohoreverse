"""Filter conditions -> parameterised SQL. Values are always bound parameters."""
from __future__ import annotations

from datetime import date, datetime, timedelta

OPS = {"eq", "neq", "in", "not_in", "gt", "gte", "lt", "lte", "between", "contains", "not_contains",
       "starts_with", "is_null", "not_null", "date_range"}

_CMP = {"eq": "=", "neq": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
_PG = {"text": "TEXT", "integer": "BIGINT", "decimal": "NUMERIC", "date": "DATE", "datetime": "TIMESTAMP", "boolean": "BOOLEAN"}


class FilterError(ValueError):
    pass


def _cast(v, dtype: str):
    if v is None:
        return None
    if dtype in ("integer", "decimal"):
        try:
            return float(v) if dtype == "decimal" else int(float(v))
        except (TypeError, ValueError) as e:
            raise FilterError(f"'{v}' is not a number") from e
    if dtype in ("date", "datetime"):
        if isinstance(v, (date, datetime)):
            return v
        try:
            d = datetime.fromisoformat(str(v)[:19])
        except ValueError as e:
            raise FilterError(f"'{v}' is not a date (use YYYY-MM-DD)") from e
        return d.date() if dtype == "date" else d
    if dtype == "boolean":
        return str(v).lower() in ("true", "1", "yes")
    return str(v)


def build_condition(col_sql: str, dtype: str, f: dict, params: dict, key: str) -> str:
    op = f.get("op", "eq")
    if op not in OPS:
        raise FilterError(f"Unsupported operator {op}")
    v = f.get("value")
    if op == "is_null":
        return f"{col_sql} IS NULL"
    if op == "not_null":
        return f"{col_sql} IS NOT NULL"
    if op in _CMP:
        params[key] = _cast(v, dtype)
        return f"{col_sql} {_CMP[op]} :{key}"
    if op in ("in", "not_in"):
        vals = v if isinstance(v, list) else [v]
        if not vals:
            return "TRUE" if op == "not_in" else "FALSE"
        names = []
        for i, item in enumerate(vals):
            params[f"{key}_{i}"] = _cast(item, dtype)
            names.append(f":{key}_{i}")
        neg = "NOT " if op == "not_in" else ""
        if dtype == "text":  # case-insensitive membership is friendlier for messy data
            names = [f"lower({n})" for n in names]
            return f"lower({col_sql}) {neg}IN ({', '.join(names)})"
        return f"{col_sql} {neg}IN ({', '.join(names)})"
    if op == "between":
        lo, hi = (v or [None, None])[:2]
        parts = []
        if lo not in (None, ""):
            params[f"{key}_lo"] = _cast(lo, dtype)
            parts.append(f"{col_sql} >= :{key}_lo")
        if hi not in (None, ""):
            params[f"{key}_hi"] = _cast(hi, dtype)
            parts.append(f"{col_sql} <= :{key}_hi")
        return " AND ".join(parts) or "TRUE"
    if op == "date_range":
        lo, hi = resolve_date_range(v)
        params[f"{key}_lo"], params[f"{key}_hi"] = lo, hi
        return f"{col_sql} >= :{key}_lo AND {col_sql} < :{key}_hi"
    if op in ("contains", "not_contains", "starts_with"):
        params[key] = (f"%{v}%" if op != "starts_with" else f"{v}%")
        neg = "NOT " if op == "not_contains" else ""
        return f"CAST({col_sql} AS TEXT) {neg}ILIKE :{key}"
    raise FilterError(op)


def _month_start(d: date, offset: int = 0) -> date:
    y, mth = d.year, d.month + offset
    while mth <= 0:
        mth += 12
        y -= 1
    while mth > 12:
        mth -= 12
        y += 1
    return date(y, mth, 1)


def _quarter_start(d: date) -> date:
    return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)


PRESETS = ["today", "yesterday", "last_7_days", "last_30_days", "last_90_days", "this_week", "last_week",
           "this_month", "last_month", "this_quarter", "last_quarter", "this_year", "last_year",
           "last_3_months", "last_6_months", "last_12_months", "year_to_date", "all_time"]


def resolve_date_range(v, today: date | None = None) -> tuple[date, date]:
    """Return [start, end) for a preset name, {"preset"}, {"last": n, "unit"} or {"from","to"} (inclusive to)."""
    if today is None:
        from ..config import today as _today
        today = _today()
    if isinstance(v, str):
        v = {"preset": v}
    if not isinstance(v, dict):
        raise FilterError("Invalid date range")
    if "from" in v or "to" in v:
        lo = _cast(v.get("from") or "1900-01-01", "date")
        hi = _cast(v.get("to") or "2999-12-31", "date") + timedelta(days=1)
        return lo, hi
    if "last" in v:
        n, unit = int(v["last"]), v.get("unit", "months")
        if unit.startswith("day"):
            return today - timedelta(days=n), today + timedelta(days=1)
        if unit.startswith("week"):
            start = today - timedelta(days=today.weekday())
            return start - timedelta(weeks=n), start
        if unit.startswith("month"):
            return _month_start(today, -n), _month_start(today)
        if unit.startswith("quarter"):
            qs = _quarter_start(today)
            return _month_start(qs, -3 * n), qs
        if unit.startswith("year"):
            return date(today.year - n, 1, 1), date(today.year, 1, 1)
        raise FilterError(f"Unknown unit {unit}")
    p = v.get("preset")
    t1 = today + timedelta(days=1)
    if p == "today":
        return today, t1
    if p == "yesterday":
        return today - timedelta(days=1), today
    if p in ("last_7_days", "last_30_days", "last_90_days"):
        n = int(p.split("_")[1])
        return today - timedelta(days=n - 1), t1
    if p == "this_week":
        s = today - timedelta(days=today.weekday())
        return s, t1
    if p == "last_week":
        s = today - timedelta(days=today.weekday())
        return s - timedelta(days=7), s
    if p == "this_month":
        return _month_start(today), t1
    if p == "last_month":
        return _month_start(today, -1), _month_start(today)
    if p in ("last_3_months", "last_6_months", "last_12_months"):
        n = int(p.split("_")[1])
        return _month_start(today, -n), _month_start(today)
    if p == "this_quarter":
        return _quarter_start(today), t1
    if p == "last_quarter":
        qs = _quarter_start(today)
        return _month_start(qs, -3), qs
    if p in ("this_year", "year_to_date"):
        return date(today.year, 1, 1), t1
    if p == "last_year":
        return date(today.year - 1, 1, 1), date(today.year, 1, 1)
    if p == "all_time":
        return date(1900, 1, 1), date(2999, 12, 31)
    raise FilterError(f"Unknown date preset '{p}'")


def previous_period(lo: date, hi: date, mode: str = "previous_period") -> tuple[date, date]:
    if mode == "previous_year":
        try:
            return lo.replace(year=lo.year - 1), hi.replace(year=hi.year - 1)
        except ValueError:  # Feb 29
            return lo - timedelta(days=365), hi - timedelta(days=365)
    # whole-month ranges shift by the same number of months
    if lo.day == 1 and hi.day == 1:
        months = (hi.year - lo.year) * 12 + hi.month - lo.month
        return _month_start(lo, -months), lo
    span = hi - lo
    return lo - span, lo


def describe_range(lo: date, hi: date) -> str:
    end = hi - timedelta(days=1)
    return f"{lo.isoformat()} to {end.isoformat()}"
