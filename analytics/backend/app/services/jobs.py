"""Background jobs kept in the app database (Phase 4): memory extraction, profile rewrites, conversation summaries.

Why a table and not Redis: the jobs are few (a handful per conversation), PostgreSQL is already there and backed up,
and a row survives any restart. A worker claims one queued row at a time with SELECT ... FOR UPDATE SKIP LOCKED, so the
in-app scheduler and a separate worker process (`python -m app.worker`) can share the queue without running a job
twice. A failed job is retried with back-off (2, 4, 8 ... minutes) up to max_attempts, then kept as `failed` with its
error. A job left `running` by a process that died is picked up again after STALE_AFTER.

Handlers take (db, payload) and return a small JSON-able result. They must be safe to run twice.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import models as m

log = logging.getLogger(__name__)

STALE_AFTER = timedelta(minutes=10)
KEEP_DONE = timedelta(days=14)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _handlers() -> dict[str, Callable[[Session, dict], dict | None]]:
    from . import memory
    from .nlq import assistant

    return {"summarise_conversation": assistant.summarise_job,
            "extract_memories": memory.extract_job,
            "update_profile": memory.profile_job,
            "refresh_staleness": memory.staleness_job}


def enqueue(db: Session, kind: str, payload: dict, delay: timedelta | None = None, dedupe_key: str | None = None,
            max_attempts: int = 3, commit: bool = True) -> m.Job:
    """Queue a job. With a dedupe_key, a job of the same key that is still queued is moved to the new time instead of
    adding a second one (used to run memory extraction once a conversation has gone quiet)."""
    run_after = _now() + (delay or timedelta(0))
    if dedupe_key:
        job = db.query(m.Job).filter_by(dedupe_key=dedupe_key, status="queued").order_by(m.Job.id.desc()).first()
        if job:
            job.run_after, job.payload = run_after, payload
            if commit:
                db.commit()
            return job
    job = m.Job(kind=kind, payload=payload, dedupe_key=dedupe_key, run_after=run_after, max_attempts=max_attempts)
    db.add(job)
    if commit:
        db.commit()
    return job


def _claim(db: Session, now: datetime, include_future: bool) -> m.Job | None:
    q = select(m.Job).where(m.Job.status == "queued")
    if not include_future:
        q = q.where(m.Job.run_after <= now)
    job = db.execute(q.order_by(m.Job.run_after, m.Job.id).limit(1).with_for_update(skip_locked=True)).scalar_one_or_none()
    if job is None:
        return None
    job.status, job.locked_at, job.attempts = "running", now, job.attempts + 1
    db.commit()
    return job


def requeue_stale(db: Session, now: datetime | None = None) -> int:
    now = now or _now()
    stale = db.query(m.Job).filter(m.Job.status == "running", m.Job.locked_at < now - STALE_AFTER).all()
    for j in stale:
        j.status = "queued" if j.attempts < j.max_attempts else "failed"
        j.last_error = (j.last_error + "\n" if j.last_error else "") + "worker stopped while running"
        j.locked_at = None
    if stale:
        db.commit()
    return len(stale)


def run_one(db: Session, include_future: bool = False) -> m.Job | None:
    """Claim and run the next due job in its own session; returns the job (now done / queued again / failed)."""
    from ..db import SessionLocal

    job = _claim(db, _now(), include_future)
    if job is None:
        return None
    handler = _handlers().get(job.kind)
    work = SessionLocal()
    try:
        if handler is None:
            raise RuntimeError(f"no handler for job kind '{job.kind}'")
        result = handler(work, dict(job.payload or {}))
        work.commit()
        job.status, job.result, job.finished_at, job.last_error = "done", result or {}, _now(), ""
    except Exception as e:  # noqa: BLE001  (a job failure is recorded, never raised into the scheduler)
        work.rollback()
        log.warning("job %s (%s) failed on attempt %s: %s", job.id, job.kind, job.attempts, e)
        job.last_error = f"{type(e).__name__}: {str(e)[:500]}"
        if job.attempts < job.max_attempts:
            job.status, job.run_after = "queued", _now() + timedelta(minutes=2 ** job.attempts)
        else:
            job.status, job.finished_at = "failed", _now()
    finally:
        work.close()
    job.locked_at = None
    db.commit()
    return job


def run_pending(max_jobs: int = 20, include_future: bool = False) -> int:
    """Run due jobs (the scheduler calls this every 30 seconds; tests call it with include_future=True)."""
    from ..db import SessionLocal, get_engine

    get_engine()
    ran = 0
    with SessionLocal() as db:
        requeue_stale(db)
        while ran < max_jobs:
            if run_one(db, include_future) is None:
                break
            ran += 1
        if ran:
            db.query(m.Job).filter(m.Job.status == "done", m.Job.finished_at < _now() - KEEP_DONE).delete()
            db.commit()
    return ran
