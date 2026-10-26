"""Guarded execution of analytical SELECTs."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import models as m
from ..config import get_settings
from ..db import get_readonly_engine
from .naming import q
from .warehouse import to_jsonable


class QueryExecutionError(RuntimeError):
    pass


@dataclass
class Result:
    columns: list[str]
    rows: list[list]
    row_count: int
    truncated: bool
    duration_ms: float
    sql: str
    params: dict = field(default_factory=dict)


def run_readonly(sql: str, params: dict, schema: str, timeout_ms: int | None = None, row_limit: int | None = None) -> Result:
    """Execute inside a READ ONLY transaction with a statement timeout and the workspace search_path."""
    settings = get_settings()
    timeout_ms = int(timeout_ms or settings.query_timeout_ms)
    row_limit = int(row_limit or settings.query_row_limit)
    engine = get_readonly_engine()
    start = time.perf_counter()
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text(f"SET LOCAL statement_timeout = {timeout_ms}"))
            conn.execute(text("SET LOCAL lock_timeout = 2000"))
            conn.execute(text("SET LOCAL work_mem = '64MB'"))
            conn.execute(text(f"SET LOCAL search_path = {q(schema)}"))
            res = conn.execute(text(sql), params)
            cols = list(res.keys())
            raw = res.fetchmany(row_limit + 1)
        except Exception as e:
            trans.rollback()
            msg = str(getattr(e, "orig", e)).split("\n")[0]
            if "statement timeout" in msg:
                msg = f"The query took longer than {timeout_ms / 1000:g}s and was cancelled"
            elif "read-only transaction" in msg:
                msg = "The query tried to modify data, which is not allowed"
            raise QueryExecutionError(msg) from e
        trans.rollback()  # nothing to commit: read-only
    truncated = len(raw) > row_limit
    rows = [[to_jsonable(v) for v in r] for r in raw[:row_limit]]
    return Result(cols, rows, len(rows), truncated, round((time.perf_counter() - start) * 1000, 1), sql, params)


def log_query(db: Session, workspace_id: int, user: str, source: str, sql: str, status: str,
              error: str = "", duration_ms: float = 0, row_count: int = 0) -> None:
    db.add(m.QueryLog(workspace_id=workspace_id, user_email=user, source=source, sql=sql[:20000], status=status,
                      error=error[:2000], duration_ms=duration_ms, row_count=row_count))
    db.commit()
