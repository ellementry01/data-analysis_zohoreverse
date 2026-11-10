"""Alerts from the scheduled domain agents, decisions on them and the executive briefing (Phase 7). Switched off unless
ASSISTANT_SCHEDULED is true. For workspace admins only: data alerts go to the owner (plan decision, 2026-11-07)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models as m
from ..config import get_settings
from ..db import get_session
from ..deps import admin, current_user
from ..services import audit, domain_agents as da
from ..services.catalog import load_catalog

router = APIRouter(prefix="/api/workspaces/{ws_id}/agents", tags=["domain agents"])


def _on(db: Session, ws: m.Workspace):
    if not get_settings().assistant_scheduled:
        raise HTTPException(403, "Scheduled agents are switched off (ASSISTANT_SCHEDULED)")
    cat = load_catalog(db, ws)
    return cat


@router.get("/summary")
def summary(ws: m.Workspace = Depends(admin), db: Session = Depends(get_session)):
    cat = _on(db, ws)
    out = da.summary(db, ws, cat)
    out["briefing"] = da.briefing_out(db.query(m.Briefing).filter_by(workspace_id=ws.id)
                                      .order_by(m.Briefing.created_at.desc()).first())
    return out


@router.get("/alerts")
def list_alerts(ws: m.Workspace = Depends(admin), db: Session = Depends(get_session), domain: str | None = None,
                status: str = "OPEN", code: str | None = None, q: str | None = None):
    cat = _on(db, ws)
    if domain and domain not in da.DOMAINS:
        raise HTTPException(400, f"domain must be one of {', '.join(da.DOMAINS)}")
    status = status.upper()
    if status not in ("OPEN", "RESOLVED", "ALL"):
        raise HTTPException(400, "status must be OPEN, RESOLVED or ALL")
    return da.alerts(db, ws, cat, agent=da.DOMAINS[domain]["agent"] if domain else None, status=status, code=code,
                     search=q, limit=2000)


class DecisionIn(BaseModel):
    decision: str = Field(pattern="^(acknowledged|dismissed)$")
    note: str = Field("", max_length=1000)


@router.post("/alerts/{alert_id}/decision")
def decide(alert_id: int, body: DecisionIn, ws: m.Workspace = Depends(admin), db: Session = Depends(get_session),
           user: str = Depends(current_user)):
    cat = _on(db, ws)
    try:
        d = da.decide(db, ws, cat, user, alert_id, body.decision, body.note)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    except da.AgentInputError as e:
        raise HTTPException(409, str(e)) from e
    audit.record(user, "alert_decision", ws.id, f"alert:{alert_id}", {"decision": body.decision, "memory_id": d.memory_id})
    return da.get_alert(db, ws, cat, alert_id)


@router.get("/decisions")
def decisions(ws: m.Workspace = Depends(admin), db: Session = Depends(get_session), alert_id: int | None = None):
    _on(db, ws)
    return da.history(db, ws, alert_id)


@router.get("/briefings")
def briefings(ws: m.Workspace = Depends(admin), db: Session = Depends(get_session)):
    _on(db, ws)
    rows = db.query(m.Briefing).filter_by(workspace_id=ws.id).order_by(m.Briefing.created_at.desc()).limit(20).all()
    return [da.briefing_out(b) for b in rows]


@router.post("/briefing")
def write_briefing(ws: m.Workspace = Depends(admin), db: Session = Depends(get_session), user: str = Depends(current_user)):
    """Write the briefing now (one Sonnet call unless the facts are unchanged since the last one)."""
    cat = _on(db, ws)
    if not da.available(cat):
        raise HTTPException(409, "The warehouse alert views are not imported into this workspace yet")
    from ..services import rate_limit
    from ..services.ai_usage import ai_context

    rate_limit.check(db, user, ws.id)
    with ai_context(user=user, workspace_id=ws.id):
        b = da.briefing(db, ws, cat, user=user)
    audit.record(user, "briefing", ws.id, f"briefing:{b.id}", {"written_by": b.written_by})
    return da.briefing_out(b)
