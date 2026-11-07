from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models as m
from ..config import get_settings
from ..db import get_session
from ..deps import admin, current_user, viewer
from ..serializers import iso, workspace_out
from ..services import audit
from ..services import datasets as dsvc
from ..services.nlq import llm

router = APIRouter(prefix="/api", tags=["workspaces"])


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""


class MemberIn(BaseModel):
    user_email: str = Field(min_length=3, max_length=200)
    role: str = Field(pattern="^(admin|editor|viewer)$")


@router.get("/me")
def me(user: str = Depends(current_user), db: Session = Depends(get_session)):
    s = get_settings()
    features = {"dashboard_chat": s.assistant_dashboard_chat, "agent_loop": s.assistant_agent_loop,
                "memory": s.assistant_memory, "data_issues": s.assistant_data_issues, "global_assistant": s.assistant_global, "scheduled_agents": s.assistant_scheduled}
    u = db.get(m.User, user)
    admins = {e.strip().lower() for e in s.bootstrap_admins.split(",") if e.strip()}
    is_admin = bool(u and u.is_platform_admin) if s.auth_mode == "google" else (user in admins or user == s.default_user.lower())
    return {**_me(user, s), "features": features, "auth_mode": s.auth_mode, "name": u.name if u else "",
            "is_platform_admin": is_admin}


def _me(user: str, s) -> dict:
    from ..services.nlq import claude

    if claude.enabled():
        return {"email": user, "llm": {"enabled": True, "provider": "anthropic",
                                       "model": f"{claude.label(s.anthropic_simple_model)} / {claude.label(s.anthropic_complex_model)}",
                                       "simple_model": claude.label(s.anthropic_simple_model),
                                       "complex_model": claude.label(s.anthropic_complex_model), "base_url_host": "api.anthropic.com"}}
    return {"email": user, "llm": {"enabled": llm.enabled(), "provider": "openai-compatible" if llm.enabled() else None,
                                   "model": s.llm_model if llm.enabled() else None,
                                   "base_url_host": (s.llm_base_url or "").split("/")[2] if s.llm_base_url and "//" in s.llm_base_url else None}}


@router.post("/demo", status_code=201)
def load_demo(user: str = Depends(current_user)):
    """Build the demo workspace through the public API (same calls the UI makes)."""
    import os
    import subprocess
    import sys

    from fastapi.testclient import TestClient

    from ..demo import SAMPLE_DIR, DemoError, build_demo
    from ..main import app

    if not os.path.exists(os.path.join(SAMPLE_DIR, "sales_register.xlsx")):
        subprocess.run([sys.executable, os.path.join(SAMPLE_DIR, "generate.py")], check=True, cwd=SAMPLE_DIR)
    client = TestClient(app)
    client.headers["X-User-Email"] = user
    try:
        return build_demo(client, log=lambda *_: None)
    except DemoError as e:
        raise HTTPException(500, f"Demo build failed: {e}")


@router.get("/workspaces")
def list_workspaces(db: Session = Depends(get_session), user: str = Depends(current_user)):
    rows = (db.query(m.Workspace).join(m.WorkspaceMember).filter(m.WorkspaceMember.user_email == user)
            .order_by(m.Workspace.created_at.desc()).all())
    counts = dict(db.query(m.Dataset.workspace_id, func.count()).group_by(m.Dataset.workspace_id).all())
    dcounts = dict(db.query(m.Dashboard.workspace_id, func.count()).group_by(m.Dashboard.workspace_id).all())
    return [workspace_out(w, user, {"dataset_count": counts.get(w.id, 0), "dashboard_count": dcounts.get(w.id, 0)}) for w in rows]


@router.post("/workspaces", status_code=201)
def create_workspace(body: WorkspaceIn, db: Session = Depends(get_session), user: str = Depends(current_user)):
    ws = dsvc.create_workspace(db, body.name, body.description, user)
    return workspace_out(ws, user)


@router.get("/workspaces/{ws_id}")
def get_workspace(ws: m.Workspace = Depends(viewer), user: str = Depends(current_user)):
    return workspace_out(ws, user) | {"members": [{"user_email": x.user_email, "role": x.role} for x in ws.members]}


@router.patch("/workspaces/{ws_id}")
def update_workspace(body: WorkspaceIn, ws: m.Workspace = Depends(admin), db: Session = Depends(get_session),
                     user: str = Depends(current_user)):
    ws.name, ws.description = body.name, body.description
    db.commit()
    return workspace_out(ws, user)


@router.delete("/workspaces/{ws_id}", status_code=204)
def delete_workspace(ws: m.Workspace = Depends(admin), db: Session = Depends(get_session)):
    dsvc.delete_workspace(db, ws)


@router.put("/workspaces/{ws_id}/members")
def upsert_member(body: MemberIn, request: Request, ws: m.Workspace = Depends(admin), db: Session = Depends(get_session),
                  user: str = Depends(current_user)):
    email = body.user_email.strip().lower()
    s = get_settings()
    if s.auth_mode == "google" and not email.endswith("@" + (s.google_allowed_domain or "").lower()):
        raise HTTPException(400, f"Only {s.google_allowed_domain} accounts can be members")
    mem = next((x for x in ws.members if x.user_email == email), None)
    if mem:
        if mem.role == "admin" and body.role != "admin" and sum(x.role == "admin" for x in ws.members) == 1:
            raise HTTPException(400, "A workspace needs at least one admin")
        mem.role = body.role
    else:
        ws.members.append(m.WorkspaceMember(user_email=email, role=body.role))
    db.commit()
    audit.record(user, "member_set", ws.id, email, {"role": body.role}, audit.client_ip(request))
    return [{"user_email": x.user_email, "role": x.role} for x in ws.members]


@router.delete("/workspaces/{ws_id}/members/{email}")
def remove_member(email: str, request: Request, ws: m.Workspace = Depends(admin), db: Session = Depends(get_session),
                  user: str = Depends(current_user)):
    mem = next((x for x in ws.members if x.user_email == email.lower()), None)
    if not mem:
        raise HTTPException(404, "Member not found")
    if mem.role == "admin" and sum(x.role == "admin" for x in ws.members) == 1:
        raise HTTPException(400, "A workspace needs at least one admin")
    ws.members.remove(mem)
    db.commit()
    audit.record(user, "member_removed", ws.id, email.lower(), ip=audit.client_ip(request))
    return [{"user_email": x.user_email, "role": x.role} for x in ws.members]


@router.get("/workspaces/{ws_id}/history")
def query_history(limit: int = 100, source: str | None = None, ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session)):
    qry = db.query(m.QueryLog).filter_by(workspace_id=ws.id)
    if source:
        qry = qry.filter_by(source=source)
    return [{"id": h.id, "user": h.user_email, "source": h.source, "sql": h.sql, "status": h.status, "error": h.error,
             "duration_ms": h.duration_ms, "row_count": h.row_count, "created_at": iso(h.created_at)}
            for h in qry.order_by(m.QueryLog.id.desc()).limit(min(limit, 500))]
