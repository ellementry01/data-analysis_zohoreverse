"""Physical storage of analytical data.

Layout per workspace schema (ws_<id>):
  _raw_<slug>   physical table holding imported rows (+ hidden _row_id identity column)
  <slug>        view exposed to users / charts / AI = raw columns + derived (formula) columns
  <slug>        for query tables the view is the user's SELECT
"""
from __future__ import annotations

import io
import logging
import math
from datetime import date, datetime

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from .. import models as m
from .naming import q
from .typeinfer import PG_TYPES, coerce

log = logging.getLogger(__name__)
ROW_ID = "_row_id"


def raw_table(slug: str) -> str:
    return f"_raw_{slug}"[:63]


def ensure_schema(conn: Connection, schema: str) -> None:
    conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {q(schema)}"))


def drop_schema(conn: Connection, schema: str) -> None:
    conn.execute(text(f"DROP SCHEMA IF EXISTS {q(schema)} CASCADE"))


def _py(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if v is pd.NaT or (isinstance(v, (pd.Timestamp,)) and pd.isna(v)):
        return None
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return None if np.isnan(v) else float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def create_raw_table(conn: Connection, schema: str, table: str, columns: list[tuple[str, str]]) -> None:
    cols = ",\n  ".join(f"{q(n)} {PG_TYPES[t]}" for n, t in columns)
    conn.execute(text(f"DROP TABLE IF EXISTS {q(schema)}.{q(table)} CASCADE"))
    conn.execute(text(
        f"CREATE TABLE {q(schema)}.{q(table)} (\n  {q(ROW_ID)} BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,\n  {cols}\n)"
    ))


def copy_rows(conn: Connection, schema: str, table: str, df: pd.DataFrame, columns: list[tuple[str, str]]) -> int:
    """Bulk-load a typed DataFrame with COPY."""
    if df.empty:
        return 0
    names = [n for n, _ in columns]
    raw = conn.connection.driver_connection  # psycopg.Connection
    collist = ", ".join(q(n) for n in names)
    with raw.cursor() as cur:
        with cur.copy(f"COPY {q(schema)}.{q(table)} ({collist}) FROM STDIN") as cp:
            for row in df[names].itertuples(index=False, name=None):
                out = []
                for v, (_, t) in zip(row, columns):
                    v = _py(v)
                    if v is not None and t == "date" and isinstance(v, datetime):
                        v = v.date()
                    out.append(v)
                cp.write_row(out)
    return len(df)


def add_columns(conn: Connection, schema: str, table: str, columns: list[tuple[str, str]]) -> None:
    for n, t in columns:
        conn.execute(text(f"ALTER TABLE {q(schema)}.{q(table)} ADD COLUMN IF NOT EXISTS {q(n)} {PG_TYPES[t]}"))


def view_sql(schema: str, ds: m.Dataset) -> str:
    parts = []
    for c in ds.columns:
        if c.is_derived:
            parts.append(f"({c.expression}) AS {q(c.name)}")
        else:
            parts.append(q(c.name))
    if not parts:
        parts = [q(ROW_ID)]
    return f"SELECT {', '.join(parts)} FROM {q(schema)}.{q(raw_table(ds.slug))}"


def _create_view(conn: Connection, schema: str, name: str, sql: str) -> None:
    conn.execute(text(f"CREATE OR REPLACE VIEW {q(schema)}.{q(name)} AS {sql}"))


def rebuild_view(db: Session, conn: Connection, schema: str, ds: m.Dataset) -> None:
    sql = ds.query_sql if ds.kind == "query_table" else view_sql(schema, ds)
    sp = conn.begin_nested()
    try:
        _create_view(conn, schema, ds.slug, sql)
        sp.commit()
        return
    except Exception:  # column removed/retyped -> must drop and rebuild dependants
        sp.rollback()
    conn.execute(text(f"DROP VIEW IF EXISTS {q(schema)}.{q(ds.slug)} CASCADE"))
    _create_view(conn, schema, ds.slug, sql)
    rebuild_query_tables(db, conn, schema, ds.workspace_id, skip=ds.id)


def rebuild_query_tables(db: Session, conn: Connection, schema: str, workspace_id: int, skip: int | None = None) -> list[str]:
    """Recreate query-table views (they may depend on each other) until no progress is made."""
    pending = [d for d in db.query(m.Dataset).filter_by(workspace_id=workspace_id, kind="query_table") if d.id != skip]
    errors: list[str] = []
    for _ in range(len(pending) + 1):
        if not pending:
            break
        still = []
        for d in pending:
            sp = conn.begin_nested()
            try:
                _create_view(conn, schema, d.slug, d.query_sql)
                sp.commit()
            except Exception as e:
                sp.rollback()
                still.append(d)
                errors.append(f"{d.name}: {e.__class__.__name__}")
        if len(still) == len(pending):
            break
        pending = still
    return errors if pending else []


def load_dataframe(
    db: Session, conn: Connection, schema: str, ds: m.Dataset, df: pd.DataFrame, mode: str
) -> dict:
    """Coerce df to the dataset's physical columns and load it. mode: create | replace | append."""
    physical = [(c.name, c.data_type) for c in ds.columns if not c.is_derived]
    report = {"rows_loaded": 0, "conversion_failures": {}}
    typed = pd.DataFrame(index=df.index)
    for name, dtype in physical:
        if name in df.columns:
            series, failed, bad = coerce(df[name], dtype)
            typed[name] = series
            if failed:
                report["conversion_failures"][name] = {"count": failed, "samples": bad}
        else:
            typed[name] = None
    table = raw_table(ds.slug)
    if mode in ("create", "replace"):
        conn.execute(text(f"DROP VIEW IF EXISTS {q(schema)}.{q(ds.slug)} CASCADE"))
        create_raw_table(conn, schema, table, physical)
    else:
        add_columns(conn, schema, table, physical)
    report["rows_loaded"] = copy_rows(conn, schema, table, typed, physical)
    return report


def apply_transforms(conn: Connection, schema: str, ds: m.Dataset) -> list[str]:
    """Replay recorded data-prep steps on the raw table (used after refresh/replace)."""
    from .transforms import apply_transform

    messages = []
    for t in ds.transforms:
        sp = conn.begin_nested()
        try:
            msg = apply_transform(conn, schema, ds, t.kind, t.params)
            sp.commit()
            t.last_result = msg
        except Exception as e:  # keep going: a failed step must not block the refresh
            sp.rollback()
            t.last_result = f"failed: {e}"
            messages.append(f"Step '{t.kind}' failed: {e}")
    return messages


def refresh_stats(conn: Connection, schema: str, ds: m.Dataset) -> None:
    ds.row_count = int(conn.execute(text(f"SELECT count(*) FROM {q(schema)}.{q(ds.slug)}")).scalar() or 0)


def to_jsonable(v):
    v = _py(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if hasattr(v, "__float__") and not isinstance(v, (int, float, bool)):
        try:
            return float(v)
        except (TypeError, ValueError):
            return str(v)
    return v
