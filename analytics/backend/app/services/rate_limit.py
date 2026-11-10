"""Per-person limits on questions to the assistants (Phase 8). Counted from the audit log, so the limit holds across
server processes and restarts. A refused request answers 429 with a plain message and is itself recorded. Only
questions that can reach Claude count: the audit event of an offline question carries engine "semantic"."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models as m
from ..config import get_settings
from . import audit

COUNTED = ("assistant_ask", "briefing")


def check(db: Session, user: str, workspace_id: int | None = None, engine: str = "auto") -> None:
    """Refuse a question that could reach Claude when the person has asked too many lately. Free offline answers (the
    semantic engine, or Claude not configured) are never limited and don't count."""
    from .nlq import claude

    s = get_settings()
    if engine == "semantic" or not claude.enabled():
        return
    now = datetime.now(timezone.utc)
    for seconds, limit, word in ((60, s.assistant_rate_per_minute, "minute"), (3600, s.assistant_rate_per_hour, "hour")):
        if limit <= 0:
            continue
        n = (db.query(func.count(m.AuditEvent.id))
             .filter(m.AuditEvent.user_email == user, m.AuditEvent.action.in_(COUNTED),
                     m.AuditEvent.at >= now - timedelta(seconds=seconds),
                     func.coalesce(m.AuditEvent.detail["engine"].as_string(), "") != "semantic").scalar())
        if n >= limit:
            audit.record(user, "rate_limited", workspace_id, word, {"limit": limit})
            raise HTTPException(429, f"You have asked {n} questions in the last {word}, the most allowed. "
                                     f"Please wait a little and ask again.", headers={"Retry-After": str(min(seconds, 60))})
