"""Audit log: sign-ins, sign-outs, assistant questions, access-rule and user changes. Writes in its own session, so an
event is kept even when the request rolls back, and never raises (a failed audit write must not break the request)."""
from __future__ import annotations

import logging

from .. import models as m

log = logging.getLogger(__name__)


def record(user: str, action: str, workspace_id: int | None = None, target: str = "", detail: dict | None = None,
           ip: str = "") -> None:
    from ..db import SessionLocal, get_engine

    try:
        get_engine()
        with SessionLocal() as db:
            db.add(m.AuditEvent(user_email=(user or "anonymous")[:200], action=action[:60], workspace_id=workspace_id,
                                target=str(target or "")[:300], detail=detail or {}, ip=(ip or "")[:64]))
            db.commit()
    except Exception:  # noqa: BLE001
        log.exception("could not write audit event %s", action)


def client_ip(request) -> str:
    try:
        return request.client.host if request and request.client else ""
    except Exception:  # noqa: BLE001
        return ""
