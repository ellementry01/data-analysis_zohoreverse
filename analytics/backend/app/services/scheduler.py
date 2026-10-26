"""In-process scheduler for periodic connector syncs."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from .. import models as m
from ..db import SessionLocal, get_engine

log = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


def run_due_schedules() -> int:
    from .connectors import sync_dataset

    get_engine()
    db = SessionLocal()
    ran = 0
    try:
        now = datetime.now(timezone.utc)
        for s in db.query(m.RefreshSchedule).filter_by(enabled=True).all():
            if s.last_run_at and s.last_run_at + timedelta(minutes=s.interval_minutes) > now:
                continue
            ds = db.get(m.Dataset, s.dataset_id)
            ws = db.get(m.Workspace, s.workspace_id)
            try:
                res = sync_dataset(db, ws, ds)
                s.last_status = f"ok: {res['rows']} rows"
            except Exception as e:  # keep scheduling other datasets
                db.rollback()
                s = db.get(m.RefreshSchedule, s.id)
                s.last_status = f"error: {e}"[:500]
                log.warning("Scheduled sync failed for dataset %s: %s", s.dataset_id, e)
            s.last_run_at = now
            db.commit()
            ran += 1
    finally:
        db.close()
    return ran


def start() -> None:
    global _scheduler
    if _scheduler:
        return
    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(run_due_schedules, "interval", minutes=1, id="sync", max_instances=1, coalesce=True)
    _scheduler.start()


def stop() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
