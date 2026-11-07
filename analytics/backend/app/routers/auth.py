"""Sign-in, sign-out, API tokens, user administration, the audit log, and per-workspace access rules (Phase 3)."""
from __future__ import annotations

import html
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models as m
from ..config import get_settings
from ..db import get_session
from ..deps import admin, current_user, platform_admin
from ..serializers import iso
from ..services import audit, auth
from ..services.dashboards import DOMAINS
from ..services.permissions import ROLE_ORDER, TARGET_TYPES

router = APIRouter(tags=["auth"])


# ----------------------------------------------------------------------------------------------- sign-in

@router.get("/api/auth/config")
def auth_config():
    """Public: how this deployment signs people in (the frontend reads it before anything else)."""
    s = get_settings()
    return {"mode": s.auth_mode, "provider": "google" if s.auth_mode == "google" else None,
            "domain": s.google_allowed_domain if s.auth_mode == "google" else None}


@router.get("/api/auth/login")
def login(next: str = "/", db: Session = Depends(get_session)):
    if get_settings().auth_mode != "google":
        return RedirectResponse(auth.safe_next(next), status_code=302)
    return RedirectResponse(auth.begin_login(db, next), status_code=302)


def _page(title: str, message: str, status: int = 200) -> HTMLResponse:
    body = (f"<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)}</title><body style='font-family:system-ui,sans-serif;max-width:32rem;margin:15vh auto;"
            f"padding:0 1rem;color:#1e293b'><h1 style='font-size:1.25rem'>{html.escape(title)}</h1><p>{html.escape(message)}</p>"
            f"<p><a href='/api/auth/login'>Sign in</a></p></body>")
    return HTMLResponse(body, status_code=status)


@router.get("/api/auth/callback")
def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
             db: Session = Depends(get_session)):
    s = get_settings()
    if s.auth_mode != "google":
        raise HTTPException(404, "Not found")
    ip = audit.client_ip(request)
    if error or not code or not state:
        audit.record("anonymous", "sign_in_failed", detail={"reason": error or "missing code"}, ip=ip)
        return _page("Sign-in cancelled", "Google did not complete the sign-in.", 400)
    try:
        user, token, next_path = auth.complete_login(db, state, code, ip, request.headers.get("user-agent", ""))
    except auth.AuthError as e:
        db.rollback()
        audit.record("anonymous", "sign_in_failed", detail={"reason": str(e)}, ip=ip)
        return _page("Sign-in refused", str(e), 403)
    audit.record(user.email, "sign_in", ip=ip)
    resp = RedirectResponse(next_path, status_code=302)
    resp.set_cookie(auth.SESSION_COOKIE, token, max_age=s.session_hours * 3600, httponly=True,
                    secure=auth.secure_cookies(s), samesite="lax", path="/")
    return resp


@router.post("/api/auth/logout")
def logout(request: Request, user: str = Depends(current_user), db: Session = Depends(get_session)):
    auth.revoke_session(db, request.cookies.get(auth.SESSION_COOKIE))
    audit.record(user, "sign_out", ip=audit.client_ip(request))
    resp = Response(status_code=204)
    resp.delete_cookie(auth.SESSION_COOKIE, path="/")
    return resp


# ----------------------------------------------------------------------------------------------- API tokens (scripts)

class TokenIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    days: int | None = Field(default=90, ge=1, le=365)


def _token_out(t: m.ApiToken) -> dict:
    return {"id": t.id, "name": t.name, "user_email": t.user_email, "created_at": iso(t.created_at),
            "last_used_at": iso(t.last_used_at), "expires_at": iso(t.expires_at), "revoked": t.revoked}


@router.get("/api/admin/tokens")
def list_tokens(user: str = Depends(platform_admin), db: Session = Depends(get_session)):
    return [_token_out(t) for t in db.query(m.ApiToken).order_by(m.ApiToken.created_at.desc()).limit(200)]


@router.post("/api/admin/tokens", status_code=201)
def create_token(body: TokenIn, request: Request, user: str = Depends(platform_admin), db: Session = Depends(get_session)):
    """A token that acts as the admin who creates it. Shown once; only its hash is kept."""
    if not db.get(m.User, user):
        db.add(m.User(email=user, name="", is_platform_admin=True))
        db.commit()
    row, token = auth.create_api_token(db, user, body.name, body.days)
    audit.record(user, "token_created", target=body.name, ip=audit.client_ip(request))
    return {**_token_out(row), "token": token}


@router.delete("/api/admin/tokens/{tid}", status_code=204)
def revoke_token(tid: int, request: Request, user: str = Depends(platform_admin), db: Session = Depends(get_session)):
    t = db.get(m.ApiToken, tid)
    if not t:
        raise HTTPException(404, "Token not found")
    t.revoked = True
    db.commit()
    audit.record(user, "token_revoked", target=t.name, ip=audit.client_ip(request))


# ----------------------------------------------------------------------------------------------- users

class UserPatch(BaseModel):
    active: bool | None = None
    is_platform_admin: bool | None = None


def _user_out(u: m.User, db: Session) -> dict:
    roles = {w.workspace.name: w.role for w in db.query(m.WorkspaceMember).filter_by(user_email=u.email)}
    return {"email": u.email, "name": u.name, "active": u.active, "is_platform_admin": u.is_platform_admin,
            "created_at": iso(u.created_at), "last_login_at": iso(u.last_login_at), "workspaces": roles}


@router.get("/api/admin/users")
def list_users(user: str = Depends(platform_admin), db: Session = Depends(get_session)):
    return [_user_out(u, db) for u in db.query(m.User).order_by(m.User.email)]


@router.patch("/api/admin/users/{email}")
def update_user(email: str, body: UserPatch, request: Request, user: str = Depends(platform_admin),
                db: Session = Depends(get_session)):
    u = db.get(m.User, email.lower())
    if not u:
        raise HTTPException(404, "User not found")
    if u.email == user and (body.active is False or body.is_platform_admin is False):
        raise HTTPException(400, "You can't switch off your own access or admin rights")
    if body.is_platform_admin is not None:
        u.is_platform_admin = body.is_platform_admin
    if body.active is False and u.active:
        auth.deactivate(db, u)       # every session and token stops working at once
    elif body.active is True:
        u.active = True
    db.commit()
    audit.record(user, "user_updated", target=u.email, detail=body.model_dump(exclude_none=True), ip=audit.client_ip(request))
    return _user_out(u, db)


# ----------------------------------------------------------------------------------------------- audit log

@router.get("/api/admin/audit")
def audit_log(user: str = Depends(platform_admin), db: Session = Depends(get_session), action: str | None = None,
              who: str | None = None, before: datetime | None = None, limit: int = Query(200, ge=1, le=1000)):
    q = db.query(m.AuditEvent)
    if action:
        q = q.filter(m.AuditEvent.action == action)
    if who:
        q = q.filter(m.AuditEvent.user_email == who.lower())
    if before:
        q = q.filter(m.AuditEvent.at < before)
    return [{"id": e.id, "at": iso(e.at), "user_email": e.user_email, "action": e.action, "workspace_id": e.workspace_id,
             "target": e.target, "detail": e.detail, "ip": e.ip}
            for e in q.order_by(m.AuditEvent.at.desc(), m.AuditEvent.id.desc()).limit(limit)]


# ----------------------------------------------------------------------------------------------- access rules

class RuleIn(BaseModel):
    target_type: str = Field(pattern="^(dashboard|domain|dataset)$")
    target: str = Field(min_length=1, max_length=200)
    principal_type: str = Field(pattern="^(role|user)$")
    principal: str = Field(min_length=1, max_length=200)


def _rule_out(r: m.AccessRule) -> dict:
    return {"id": r.id, "target_type": r.target_type, "target": r.target, "principal_type": r.principal_type,
            "principal": r.principal, "created_by": r.created_by, "created_at": iso(r.created_at)}


@router.get("/api/workspaces/{ws_id}/access-rules")
def list_rules(ws: m.Workspace = Depends(admin), db: Session = Depends(get_session)):
    return [_rule_out(r) for r in db.query(m.AccessRule).filter_by(workspace_id=ws.id)
            .order_by(m.AccessRule.target_type, m.AccessRule.target, m.AccessRule.id)]


@router.post("/api/workspaces/{ws_id}/access-rules", status_code=201)
def add_rule(body: RuleIn, request: Request, ws: m.Workspace = Depends(admin), db: Session = Depends(get_session),
             user: str = Depends(current_user)):
    assert body.target_type in TARGET_TYPES
    if body.target_type == "dashboard" and not db.query(m.Dashboard).filter_by(workspace_id=ws.id, key=body.target).first():
        raise HTTPException(400, f"No dashboard with key '{body.target}'")
    if body.target_type == "domain" and (body.target not in DOMAINS or not body.target):
        raise HTTPException(400, f"Unknown domain '{body.target}'")
    if body.target_type == "dataset" and not db.query(m.Dataset).filter_by(workspace_id=ws.id, slug=body.target).first():
        raise HTTPException(400, f"No dataset '{body.target}'")
    principal = body.principal.strip().lower()
    if body.principal_type == "role" and principal not in ROLE_ORDER:
        raise HTTPException(400, "A role rule needs viewer, editor or admin")
    if body.principal_type == "user" and "@" not in principal:
        raise HTTPException(400, "A user rule needs an email address")
    if db.query(m.AccessRule).filter_by(workspace_id=ws.id, target_type=body.target_type, target=body.target,
                                        principal_type=body.principal_type, principal=principal).first():
        raise HTTPException(409, "That rule already exists")
    r = m.AccessRule(workspace_id=ws.id, target_type=body.target_type, target=body.target, principal_type=body.principal_type,
                     principal=principal, created_by=user)
    db.add(r)
    db.commit()
    audit.record(user, "access_rule_added", ws.id, f"{body.target_type}:{body.target}",
                 {"principal_type": body.principal_type, "principal": principal}, audit.client_ip(request))
    return _rule_out(r)


@router.delete("/api/workspaces/{ws_id}/access-rules/{rid}", status_code=204)
def delete_rule(rid: int, request: Request, ws: m.Workspace = Depends(admin), db: Session = Depends(get_session),
                user: str = Depends(current_user)):
    r = db.get(m.AccessRule, rid)
    if not r or r.workspace_id != ws.id:
        raise HTTPException(404, "Rule not found")
    db.delete(r)
    db.commit()
    audit.record(user, "access_rule_removed", ws.id, f"{r.target_type}:{r.target}",
                 {"principal_type": r.principal_type, "principal": r.principal}, audit.client_ip(request))
