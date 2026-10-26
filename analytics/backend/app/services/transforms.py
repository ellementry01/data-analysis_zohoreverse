"""Data-preparation steps applied to a dataset's raw table. Each step is recorded and replayable."""
from __future__ import annotations

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection

from .. import models as m
from .filters import build_condition
from .naming import q
from .typeinfer import DATA_TYPES, PG_TYPES, coerce
from .warehouse import ROW_ID, raw_table

TRANSFORM_KINDS = {
    "trim_whitespace": "Trim surrounding/duplicate whitespace in text columns",
    "change_case": "Convert text to upper, lower or title case",
    "replace_values": "Find and replace values in a column",
    "fill_nulls": "Fill empty values with a constant",
    "remove_duplicates": "Remove duplicate rows (optionally by key columns)",
    "delete_rows": "Delete rows matching a condition",
    "cast_type": "Change a column's data type (unparseable values become empty)",
    "drop_column": "Remove a column",
    "standardize_values": "Map inconsistent spellings to one canonical value",
}


class TransformError(ValueError):
    pass


def _col(ds: m.Dataset, name: str, physical_only: bool = True) -> m.DatasetColumn:
    for c in ds.columns:
        if c.name == name and (not physical_only or not c.is_derived):
            return c
    raise TransformError(f"Column '{name}' not found")


def apply_transform(conn: Connection, schema: str, ds: m.Dataset, kind: str, p: dict) -> str:
    tbl = f"{q(schema)}.{q(raw_table(ds.slug))}"

    if kind == "trim_whitespace":
        cols = p.get("columns") or [c.name for c in ds.columns if c.data_type == "text" and not c.is_derived]
        total = 0
        for name in cols:
            c = _col(ds, name)
            if c.data_type != "text":
                continue
            r = conn.execute(text(
                f"UPDATE {tbl} SET {q(c.name)} = NULLIF(regexp_replace(btrim({q(c.name)}), '\\s+', ' ', 'g'), '') "
                f"WHERE {q(c.name)} IS DISTINCT FROM NULLIF(regexp_replace(btrim({q(c.name)}), '\\s+', ' ', 'g'), '')"
            ))
            total += r.rowcount
        return f"{total} values trimmed"

    if kind == "change_case":
        c = _col(ds, p["column"])
        fn = {"upper": "upper", "lower": "lower", "title": "initcap"}.get(p.get("mode", "title"))
        if not fn:
            raise TransformError("mode must be upper, lower or title")
        r = conn.execute(text(f"UPDATE {tbl} SET {q(c.name)} = {fn}({q(c.name)}) WHERE {q(c.name)} IS DISTINCT FROM {fn}({q(c.name)})"))
        return f"{r.rowcount} values changed"

    if kind == "replace_values":
        c = _col(ds, p["column"])
        find, repl = p.get("find", ""), p.get("replace", "")
        if p.get("match", "exact") == "contains":
            if c.data_type != "text":
                raise TransformError("'contains' replacement only works on text columns")
            r = conn.execute(text(f"UPDATE {tbl} SET {q(c.name)} = replace({q(c.name)}, :f, :r) WHERE strpos({q(c.name)}, :f) > 0"),
                             {"f": find, "r": repl})
        else:
            r = conn.execute(text(f"UPDATE {tbl} SET {q(c.name)} = CAST(:r AS {PG_TYPES[c.data_type]}) "
                                  f"WHERE CAST({q(c.name)} AS TEXT) = :f"), {"f": str(find), "r": repl if repl != "" else None})
        return f"{r.rowcount} values replaced"

    if kind == "standardize_values":
        c = _col(ds, p["column"])
        mapping: dict = p.get("mapping") or {}
        total = 0
        for target, variants in mapping.items():
            variants = [v for v in (variants or []) if v != target]
            if not variants:
                continue
            r = conn.execute(text(f"UPDATE {tbl} SET {q(c.name)} = :t WHERE lower(btrim({q(c.name)})) = ANY(:v) AND {q(c.name)} IS DISTINCT FROM :t"),
                             {"t": target, "v": [str(v).strip().lower() for v in variants]})
            total += r.rowcount
        return f"{total} values standardized"

    if kind == "fill_nulls":
        c = _col(ds, p["column"])
        r = conn.execute(text(f"UPDATE {tbl} SET {q(c.name)} = CAST(:v AS {PG_TYPES[c.data_type]}) WHERE {q(c.name)} IS NULL"),
                         {"v": p.get("value")})
        return f"{r.rowcount} empty values filled"

    if kind == "remove_duplicates":
        cols = p.get("columns") or [c.name for c in ds.columns if not c.is_derived]
        for name in cols:
            _col(ds, name)
        key = ", ".join(q(n) for n in cols)
        r = conn.execute(text(
            f"DELETE FROM {tbl} WHERE {q(ROW_ID)} IN (SELECT {q(ROW_ID)} FROM ("
            f"SELECT {q(ROW_ID)}, row_number() OVER (PARTITION BY {key} ORDER BY {q(ROW_ID)}) AS rn FROM {tbl}) d WHERE rn > 1)"
        ))
        return f"{r.rowcount} duplicate rows removed"

    if kind == "delete_rows":
        filters = p.get("filters") or []
        if not filters:
            raise TransformError("delete_rows needs at least one condition")
        cols = {c.name: c.data_type for c in ds.columns if not c.is_derived}
        params: dict = {}
        conds = [build_condition(q(f["column"]) if f.get("column") in cols else _bad(f), cols[f["column"]], f, params, f"p{i}")
                 for i, f in enumerate(filters)]
        r = conn.execute(text(f"DELETE FROM {tbl} WHERE {' AND '.join(conds)}"), params)
        return f"{r.rowcount} rows deleted"

    if kind == "cast_type":
        c = _col(ds, p["column"])
        to = p.get("to")
        if to not in DATA_TYPES:
            raise TransformError(f"Unsupported type {to}")
        rows = conn.execute(text(f"SELECT {q(ROW_ID)}, {q(c.name)} FROM {tbl}")).all()
        s = pd.Series([r[1] for r in rows], dtype="object")
        if c.data_type == "text":
            from .typeinfer import normalize_nulls
            s = normalize_nulls(s)
        conv, failed, _ = coerce(s, to)
        tmp = f"_cast_{c.name}"[:63]
        conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN {q(tmp)} {PG_TYPES[to]}"))
        raw = conn.connection.driver_connection
        with raw.cursor() as cur:
            cur.execute(f"CREATE TEMP TABLE _cast_vals (id BIGINT, v {PG_TYPES[to]}) ON COMMIT DROP")
            with cur.copy("COPY _cast_vals (id, v) FROM STDIN") as cp:
                from .warehouse import _py
                for (rid, _), v in zip(rows, conv.tolist()):
                    v = _py(v)
                    if v is not None and to == "date" and hasattr(v, "date"):
                        v = v.date()
                    cp.write_row((rid, v))
        conn.execute(text(f"UPDATE {tbl} t SET {q(tmp)} = v.v FROM _cast_vals v WHERE t.{q(ROW_ID)} = v.id"))
        conn.execute(text("DROP TABLE IF EXISTS _cast_vals"))
        conn.execute(text(f"ALTER TABLE {tbl} DROP COLUMN {q(c.name)} CASCADE"))
        conn.execute(text(f"ALTER TABLE {tbl} RENAME COLUMN {q(tmp)} TO {q(c.name)}"))
        c.data_type = to
        return f"converted to {to}; {failed} values could not be converted and were set empty"

    if kind == "drop_column":
        c = _col(ds, p["column"])
        conn.execute(text(f"ALTER TABLE {tbl} DROP COLUMN IF EXISTS {q(c.name)} CASCADE"))
        ds.columns.remove(c)
        return "column removed"

    raise TransformError(f"Unknown transform '{kind}'")


def _bad(f):
    raise TransformError(f"Unknown column '{f.get('column')}'")
