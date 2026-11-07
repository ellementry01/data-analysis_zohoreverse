"""Data issues, tile notes, "worth a look" and the owner's notifications (Phase 5). Switched off unless
ASSISTANT_DATA_ISSUES is true. Members read; workspace admins edit the register and see notifications."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models as m
from ..config import get_settings
from ..db import get_session
from ..deps import admin, current_user, viewer
from ..serializers import iso
from ..services import audit, data_issues as di, worth_a_look
from ..services.catalog import load_catalog

router = APIRouter(prefix="/api/workspaces/{ws_id}", tags=["data issues"])


def _on():
    if not get_settings().assistant_data_issues:
        raise HTTPException(403, "Data issues are switched off (ASSISTANT_DATA_ISSUES)")


def _out(i: m.DataIssue) -> dict:
    return {"code": i.code, "title": i.title, "area": i.area, "status": i.status, "status_detail": i.status_detail,
            "severity": i.severity, "summary": i.summary, "note": i.note or i.title, "affects": i.affects or {},
            "owner": i.owner, "source": i.source, "opened_at": iso(i.opened_at), "solved_at": iso(i.solved_at),
            "updated_by": i.updated_by, "updated_at": iso(i.updated_at)}


def _get(db: Session, ws: m.Workspace, code: str) -> m.DataIssue:
    i = db.query(m.DataIssue).filter_by(workspace_id=ws.id, code=code.upper()).one_or_none()
    if i is None:
        raise HTTPException(404, "Issue not found")
    return i


@router.get("/data-issues")
def list_issues(ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session), status: str | None = None):
    _on()
    q = db.query(m.DataIssue).filter_by(workspace_id=ws.id)
    if status == "live":
        q = q.filter(m.DataIssue.status.in_(di.LIVE))
    elif status:
        q = q.filter(m.DataIssue.status == status)
    rows = sorted(q.all(), key=lambda i: (i.status == "solved", di.SEVERITY_ORDER.get(i.severity, 9), i.code))
    return [_out(i) for i in rows]


class IssueIn(BaseModel):
    code: str | None = Field(None, max_length=30)
    title: str = Field(min_length=3, max_length=300)
    area: str = Field("", max_length=80)
    status: str = Field("open", pattern="^(open|awaiting|parked|solved)$")
    severity: str = Field("medium", pattern="^(high|medium|low)$")
    summary: str = Field("", max_length=4000)
    note: str = Field("", max_length=500)
    owner: str = Field("", max_length=120)
    affects: dict = Field(default_factory=dict)


@router.post("/data-issues", status_code=201)
def create_issue(body: IssueIn, ws: m.Workspace = Depends(admin), db: Session = Depends(get_session),
                 user: str = Depends(current_user)):
    _on()
    code = (body.code or "").strip().upper()
    if not code:
        n = db.query(m.DataIssue).filter(m.DataIssue.workspace_id == ws.id, m.DataIssue.code.like("APP-%")).count()
        code = f"APP-{n + 1}"
    if not di.CODE.match(code):
        raise HTTPException(400, "The code must look like D-124")
    if db.query(m.DataIssue).filter_by(workspace_id=ws.id, code=code).count():
        raise HTTPException(409, f"{code} already exists")
    try:
        affects = di.clean_affects(db, ws, body.affects)
    except di.IssueInputError as e:
        raise HTTPException(400, str(e))
    i = m.DataIssue(workspace_id=ws.id, code=code, title=body.title, area=body.area, status=body.status,
                    severity=body.severity, summary=body.summary, note=body.note, owner=body.owner, affects=affects,
                    source="manual", updated_by=user)
    db.add(i)
    di.notify(db, ws.id, "issue_opened", f"{code} opened: {body.title}", f"Added by {user}.", code)
    db.commit()
    audit.record(user, "issue_created", ws.id, f"issue:{code}", {"severity": body.severity})
    return _out(i)


class IssuePatch(BaseModel):
    title: str | None = Field(None, min_length=3, max_length=300)
    area: str | None = Field(None, max_length=80)
    status: str | None = Field(None, pattern="^(open|awaiting|parked|solved)$")
    severity: str | None = Field(None, pattern="^(high|medium|low)$")
    summary: str | None = Field(None, max_length=4000)
    note: str | None = Field(None, max_length=500)
    owner: str | None = Field(None, max_length=120)
    affects: dict | None = None


@router.patch("/data-issues/{code}")
def edit_issue(code: str, body: IssuePatch, ws: m.Workspace = Depends(admin), db: Session = Depends(get_session),
               user: str = Depends(current_user)):
    _on()
    i = _get(db, ws, code)
    before = _out(i)
    try:
        if body.affects is not None:
            i.affects = di.clean_affects(db, ws, body.affects)
        for k in ("title", "area", "severity", "summary", "note", "owner"):
            v = getattr(body, k)
            if v is not None:
                setattr(i, k, v)
        status_changed = body.status is not None and body.status != i.status
        if body.status is not None:
            di.set_status(db, ws, i, body.status, user)
    except di.IssueInputError as e:
        raise HTTPException(400, str(e))
    i.updated_by = user
    db.commit()
    if status_changed:
        di.after_change(db, ws.id)
    audit.record(user, "issue_edited", ws.id, f"issue:{i.code}",
                 {k: before[k] for k in ("status", "severity", "affects") if before[k] != _out(i)[k]})
    return _out(i)


class ImportIn(BaseModel):
    rows: list[dict] = Field(default_factory=list, max_length=500)
    solved: list[str] = Field(default_factory=list, max_length=2000)


@router.post("/data-issues/import")
def import_issues(body: ImportIn, ws: m.Workspace = Depends(admin), db: Session = Depends(get_session),
                  user: str = Depends(current_user)):
    """Used by scripts/import_issue_log.py: adds issues not in the register, marks solved ones solved, changes nothing
    else (the register is the source of truth after the first import)."""
    _on()
    try:
        out = di.import_rows(db, ws, body.rows, body.solved, user)
    except di.IssueInputError as e:
        db.rollback()
        raise HTTPException(400, str(e))
    audit.record(user, "issues_imported", ws.id, "issue-log", {k: len(v) for k, v in out.items()})
    return out


# ----------------------------------------------------------------------------------------------- on a dashboard

@router.get("/dashboards/key/{key}/insights")
def dashboard_insights(key: str, ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session)):
    """The known issues touching this dashboard (with the tiles they touch) and its "worth a look" items. Costs no AI:
    the items were computed after the data last changed."""
    _on()
    from .analysis import _dashboard_by_key

    d = _dashboard_by_key(db, ws, key)
    cat = load_catalog(db, ws)
    issues = [{**di.brief(h["issue"]), "widget_ids": h["widget_ids"], "whole_dashboard": h["whole_dashboard"]}
              for h in di.for_dashboard(db, d, cat)]
    return {"issues": issues, "worth_a_look": worth_a_look.for_user(db, ws, d, cat)}


# ----------------------------------------------------------------------------------------------- notifications

@router.get("/notifications")
def notifications(ws: m.Workspace = Depends(admin), db: Session = Depends(get_session), user: str = Depends(current_user)):
    _on()
    rows = db.query(m.Notification).filter_by(workspace_id=ws.id).order_by(m.Notification.id.desc()).limit(50).all()
    return {"unread": sum(user not in (n.read_by or []) for n in rows),
            "items": [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "issue_code": n.issue_code,
                       "created_at": iso(n.created_at), "read": user in (n.read_by or [])} for n in rows]}


class ReadIn(BaseModel):
    ids: list[int] | None = None   # none = all


@router.post("/notifications/read")
def mark_read(body: ReadIn, ws: m.Workspace = Depends(admin), db: Session = Depends(get_session),
              user: str = Depends(current_user)):
    _on()
    q = db.query(m.Notification).filter_by(workspace_id=ws.id)
    if body.ids is not None:
        q = q.filter(m.Notification.id.in_(body.ids))
    n = 0
    for x in q:
        if user not in (x.read_by or []):
            x.read_by = [*(x.read_by or []), user]
            n += 1
    db.commit()
    return {"marked": n}
