"""In-process scheduler for periodic connector syncs, the job queue and memory upkeep.

The server may run several processes (WEB_CONCURRENCY, Phase 8). The syncs and the hourly upkeep must run once, so only
the process holding a PostgreSQL advisory lock (the leader) runs them; when it stops, its connection closes, the lock is
released and another process takes over at its next tick. The job queue runs in every process: each job is claimed
once (SKIP LOCKED)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from .. import models as m
from ..db import SessionLocal, get_engine

log = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None
LEADER_LOCK = 7202611            # any constant; the same in every process of this app
_leader_conn = None


def is_leader() -> bool:
    """True when this process holds (or now takes) the scheduler lock. The lock lives on a dedicated connection."""
    global _leader_conn
    from sqlalchemy import text

    try:
        if _leader_conn is not None:
            _leader_conn.execute(text("SELECT 1"))
            _leader_conn.commit()
            return True
        conn = get_engine().connect()
        got = bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": LEADER_LOCK}).scalar())
        conn.commit()
        if got:
            _leader_conn = conn
            log.info("this process runs the scheduled syncs")
        else:
            conn.close()
        return got
    except Exception:  # noqa: BLE001  (lost connection: the lock went with it; try again next tick)
        log.warning("scheduler lock check failed", exc_info=True)
        if _leader_conn is not None:
            try:
                _leader_conn.invalidate()
            except Exception:  # noqa: BLE001
                pass
        _leader_conn = None
        return False


def release_leader() -> None:
    global _leader_conn
    if _leader_conn is not None:
        from sqlalchemy import text

        try:
            # unlock explicitly: close() only hands a pooled connection back, and the session (with the lock) lives on
            _leader_conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": LEADER_LOCK})
            _leader_conn.commit()
            _leader_conn.close()
        except Exception:  # noqa: BLE001
            try:
                _leader_conn.invalidate()   # discard the session itself: the lock goes with it
            except Exception:  # noqa: BLE001
                pass
        _leader_conn = None


def _leader_only(fn):
    def run():
        if is_leader():
            return fn()
        return None
    run.__name__ = fn.__name__
    return run


def run_due_schedules() -> int:
    from .connectors import sync_dataset

    get_engine()
    db = SessionLocal()
    ran = 0
    synced: set[int] = set()
    try:
        now = datetime.now(timezone.utc)
        for s in db.query(m.RefreshSchedule).filter_by(enabled=True).all():
            if s.last_run_at and s.last_run_at + timedelta(minutes=s.interval_minutes) > now:
                continue
            ds = db.get(m.Dataset, s.dataset_id)
            ws = db.get(m.Workspace, s.workspace_id)
            try:
                res = sync_dataset(db, ws, ds, force=False)
                s.last_status = f"ok: {res['rows']} rows" + (", unchanged" if res.get("unchanged") else "")
                if not res.get("unchanged"):
                    synced.add(s.workspace_id)
            except Exception as e:  # keep scheduling other datasets
                db.rollback()
                s = db.get(m.RefreshSchedule, s.id)
                s.last_status = f"error: {e}"[:500]
                log.warning("Scheduled sync failed for dataset %s: %s", s.dataset_id, e)
            s.last_run_at = now
            db.commit()
            ran += 1
        _after_sync(db, synced)
    finally:
        db.close()
    return ran


def _after_sync(db, ws_ids: set[int]) -> None:
    """Phase 5: after a sync, "worth a look" is recomputed for dashboards whose data changed (the job compares
    fingerprints, so an unchanged re-sync costs one cheap check)."""
    from ..config import get_settings

    if not ws_ids:
        return
    if get_settings().assistant_data_issues:
        from . import worth_a_look

        try:
            for ws_id in ws_ids:
                worth_a_look.queue(db, ws_id)
        except Exception:  # noqa: BLE001
            log.exception("could not queue worth-a-look")
            db.rollback()
    if get_settings().assistant_scheduled:   # Phase 7: announce new alerts, queue the briefing when due
        from . import domain_agents

        for ws_id in ws_ids:
            try:
                domain_agents.after_sync(db, ws_id)
            except Exception:  # noqa: BLE001
                log.exception("could not process agent alerts")
                db.rollback()


def run_jobs() -> int:
    from . import jobs

    try:
        return jobs.run_pending()
    except Exception:  # noqa: BLE001  (keep the scheduler alive)
        log.exception("background jobs failed")
        return 0


def queue_memory_upkeep() -> None:
    """Hourly: re-check memories whose metrics changed; weekly profile rewrites (Phase 4, only with memory on)."""
    from ..config import get_settings
    from . import jobs, memory

    if not get_settings().assistant_memory:
        return
    get_engine()
    db = SessionLocal()
    try:
        jobs.enqueue(db, "refresh_staleness", {}, dedupe_key="staleness")
        memory.enqueue_due_profiles(db)
    except Exception:  # noqa: BLE001
        log.exception("could not queue memory upkeep")
    finally:
        db.close()


def start() -> None:
    from ..config import get_settings

    global _scheduler
    if _scheduler:
        return
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(_leader_only(run_due_schedules), "interval", minutes=1, id="sync", max_instances=1, coalesce=True)
    if get_settings().enable_worker:
        _scheduler.add_job(run_jobs, "interval", seconds=30, id="jobs", max_instances=1, coalesce=True)
    _scheduler.add_job(_leader_only(queue_memory_upkeep), "interval", hours=1, id="memory_upkeep", max_instances=1,
                       coalesce=True)
    _scheduler.start()


def stop() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
    release_leader()
