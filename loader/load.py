"""
Loads one file into its raw table.

Guarantees
  * All-or-nothing: raw rows, the LOADED batch record and loader DQ results
    commit together in ONE transaction, or not at all.
  * A failed load is still recorded (status FAILED, with the reason) in a
    separate transaction, so every attempt is auditable.
  * The same file (same bytes) cannot be loaded twice while a live load of it
    exists; the database enforces this, so even two loaders running at once
    cannot both succeed.
  * Row counts are verified in the database before commit.
Connection: libpq environment (PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE)
or DATABASE_URL. No credentials in code.
"""
from __future__ import annotations

import datetime as dt
import getpass
import os
from dataclasses import dataclass
from pathlib import Path

import psycopg

from .readers import read_workbook, sha256_of
from .validate import ContractError, load_contract, parse


class AlreadyLoaded(Exception):
    def __init__(self, batch_id: int, status: str):
        super().__init__(f"this exact file is already loaded as batch {batch_id} (status {status}); nothing done")
        self.batch_id = batch_id


class LoadRefused(Exception):
    """Operator error or policy refusal (missing --as-of, draft contract, unregistered source)."""


@dataclass
class Outcome:
    batch_id: int | None
    source: str
    sheet: str
    rows_read: int
    rows_loaded: int
    period: tuple | None
    as_of: dt.date | None
    warnings: list
    dry_run: bool


def connect() -> psycopg.Connection:
    return psycopg.connect(os.environ.get("DATABASE_URL", ""), autocommit=False)


def load_file(source: str, path: Path, *, as_of: dt.date | None = None, loaded_by: str | None = None,
              dry_run: bool = False, accept_draft: bool = False, conn: psycopg.Connection | None = None) -> Outcome:
    path = Path(path)
    if not path.is_file():
        raise LoadRefused(f"file not found: {path}")
    contract = load_contract(source)
    if contract["status"] != "verified" and not accept_draft:
        raise LoadRefused(f"contract for {source} is a DRAFT ({contract.get('draft_note', '')}). "
                          "Re-run with --accept-draft only after checking the file's columns by eye.")
    if contract["as_of_required"] and as_of is None:
        raise LoadRefused(f"{source} is a snapshot/state/master export: --as-of YYYY-MM-DD is required "
                          "(the date the export represents)")
    if not contract["as_of_required"] and as_of is not None:
        raise LoadRefused(f"{source} is transactional; its period comes from the data. Do not pass --as-of.")

    digest = sha256_of(path)
    who = loaded_by or getpass.getuser()
    try:
        book = read_workbook(path)
        sheet, parsed = parse(book, contract)
        if parsed.as_of_in_file and as_of != parsed.as_of_in_file:
            raise ContractError(f"--as-of {as_of} does not match the date printed in the report ({parsed.as_of_in_file})")
        if as_of and parsed.period_end and parsed.period_end > as_of:
            raise ContractError(f"the file contains business dates up to {parsed.period_end}, after --as-of {as_of}. "
                                "A state export cannot contain the future: check the date the export was taken.")
    except Exception as e:
        if not dry_run:                      # audit every rejected file, not only DB failures
            c = conn or connect()
            try:
                _check_source_registered(c, source)
                _record_failure(c, source, path, digest, None, as_of, who, e)
            finally:
                if conn is None:
                    c.close()
        raise

    outcome = Outcome(None, source, sheet, parsed.rows_read, len(parsed.records),
                      (parsed.period_start, parsed.period_end) if parsed.period_start else None,
                      as_of, parsed.warnings, dry_run)
    if dry_run:
        return outcome

    own = conn is None
    conn = conn or connect()
    try:
        _check_source_registered(conn, source)
        existing = _live_batch(conn, source, digest)
        if existing:
            raise AlreadyLoaded(*existing)
        try:
            outcome.batch_id = _load(conn, contract, parsed, path, digest, as_of, who)
            conn.commit()
        except psycopg.errors.UniqueViolation:
            conn.rollback()                    # another loader registered the same file first
            existing = _live_batch(conn, source, digest)
            if existing:
                raise AlreadyLoaded(*existing)
            raise
        except Exception as e:
            conn.rollback()
            _record_failure(conn, source, path, digest, parsed, as_of, who, e)
            raise
        return outcome
    finally:
        if own:
            conn.close()


def _check_source_registered(conn, source):
    row = conn.execute("SELECT is_active FROM meta.source_registry WHERE source_name = %s", (source,)).fetchone()
    conn.rollback()
    if row is None:
        raise LoadRefused(f"source {source} is not registered in meta.source_registry")
    if not row[0]:
        raise LoadRefused(f"source {source} is registered but inactive")


def _live_batch(conn, source, digest):
    row = conn.execute("SELECT batch_id, status FROM meta.load_batch WHERE source_name = %s AND file_sha256 = %s "
                       "AND status IN ('STARTED','LOADED') ORDER BY batch_id LIMIT 1", (source, digest)).fetchone()
    conn.rollback()
    return row


def _load(conn, contract, parsed, path, digest, as_of, who) -> int:
    source = contract["source_name"]
    table = f"raw.{source.lower()}"
    pivot = contract["layout"] == "STOCK_PIVOT"
    batch_id = conn.execute(
        "INSERT INTO meta.load_batch (source_name, file_name, file_sha256, period_start, period_end, as_of_date, "
        "rows_read, status, loaded_by) VALUES (%s,%s,%s,%s,%s,%s,%s,'STARTED',%s) RETURNING batch_id",
        (source, path.name, digest, parsed.period_start, parsed.period_end, as_of, parsed.rows_read, who)).fetchone()[0]

    lineage = ["batch_id", "source_row_number"] + (["source_col_number"] if pivot else [])
    cols = ", ".join(lineage + parsed.columns)
    with conn.cursor() as cur:
        with cur.copy(f"COPY {table} ({cols}) FROM STDIN") as cp:
            for rec in parsed.records:
                cp.write_row((batch_id, *rec))

    n = conn.execute(f"SELECT count(*) FROM {table} WHERE batch_id = %s", (batch_id,)).fetchone()[0]
    if n != len(parsed.records):
        raise RuntimeError(f"row count check failed: parsed {len(parsed.records)}, database holds {n}")

    for name, details, failed in parsed.warnings:
        conn.execute("INSERT INTO meta.dq_check_result (batch_id, check_name, target_table, severity, outcome, "
                     "failed_row_count, details) VALUES (%s,%s,%s,'WARN','FAIL',%s,%s)",
                     (batch_id, name, table, failed, details[:4000]))
    conn.execute("INSERT INTO meta.dq_check_result (batch_id, check_name, target_table, severity, outcome, "
                 "failed_row_count, details) VALUES (%s,'raw_row_count_matches_file',%s,'ERROR','PASS',0,%s)",
                 (batch_id, table, f"{n} rows landed = {len(parsed.records)} rows parsed"))
    notes = "; ".join(d for _, d, _ in parsed.warnings)[:1000] or None
    conn.execute("UPDATE meta.load_batch SET status='LOADED', rows_loaded=%s, rows_rejected=0, "
                 "finished_at=CURRENT_TIMESTAMP, notes=%s WHERE batch_id=%s", (n, notes, batch_id))
    return batch_id


def _record_failure(conn, source, path, digest, parsed, as_of, who, err):
    try:
        conn.execute(
            "INSERT INTO meta.load_batch (source_name, file_name, file_sha256, period_start, period_end, as_of_date, "
            "rows_read, rows_loaded, status, loaded_by, finished_at, notes) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,0,'FAILED',%s,CURRENT_TIMESTAMP,%s)",
            (source, path.name, digest, parsed.period_start if parsed else None, parsed.period_end if parsed else None,
             as_of, parsed.rows_read if parsed else None, who,
             f"{type(err).__name__}: {err}"[:1000]))
        conn.commit()
    except Exception:
        conn.rollback()     # never mask the original error
