"""Request dependencies: session, current user and workspace role checks.

Who is asking:
* AUTH_MODE=google (production): a signed-in session cookie, or an API token sent as "Authorization: Bearer <token>"
  (scripts). The X-User-Email header is ignored. Cookie-authenticated writes from another site are refused (Origin
  check, on top of the SameSite=Lax cookie).
* AUTH_MODE=dev (local development and tests only; refused at start-up unless PUBLIC_BASE_URL is localhost): the
  X-User-Email header, defaulting to DEFAULT_USER.

Roles are enforced per workspace: viewer < editor < admin. The workspace returned by viewer/editor/admin records who is
acting on it, which the permission checks (services/permissions.py) read.
"""
from fastapi import Depends, Header, HTTPException, Path, Request
from sqlalchemy.orm import Session

from . import models as m
from .config import get_settings
from .db import get_session
from .services import auth
from .services.permissions import ROLE_ORDER, hidden_dataset_ids, set_acting

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def current_user(request: Request, x_user_email: str | None = Header(default=None),
                 authorization: str | None = Header(default=None), db: Session = Depends(get_session)) -> str:
    s = get_settings()
    if s.auth_mode == "dev":
        email = (x_user_email or s.default_user).strip().lower()
        if not email or len(email) > 200:
            raise HTTPException(400, "Invalid user")
        return email
    if authorization and authorization.lower().startswith("bearer "):
        email = auth.user_from_api_token(db, authorization[7:].strip())
        if not email:
            raise HTTPException(401, "Invalid or expired API token")
        return email
    email = auth.user_from_session(db, request.cookies.get(auth.SESSION_COOKIE))
    if not email:
        raise HTTPException(401, "Sign in required")
    if request.method not in SAFE_METHODS:
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != auth.base_origin(s):
            raise HTTPException(403, "Cross-site request refused")
    return email


def platform_admin(user: str = Depends(current_user), db: Session = Depends(get_session)) -> str:
    """Manages users, API tokens and the audit log. In dev mode: DEFAULT_USER and BOOTSTRAP_ADMINS."""
    s = get_settings()
    if s.auth_mode == "dev":
        admins = {e.strip().lower() for e in s.bootstrap_admins.split(",") if e.strip()} | {s.default_user.lower()}
        if user in admins:
            return user
        raise HTTPException(403, "Platform administrators only")
    u = db.get(m.User, user)
    if not u or not u.is_platform_admin:
        raise HTTPException(403, "Platform administrators only")
    return user


def _workspace(db: Session, ws_id: int, user: str, min_role: str) -> m.Workspace:
    ws = db.get(m.Workspace, ws_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    member = next((x for x in ws.members if x.user_email == user), None)
    if not member:
        raise HTTPException(403, "You are not a member of this workspace")
    if ROLE_ORDER[member.role] < ROLE_ORDER[min_role]:
        raise HTTPException(403, f"This action requires the {min_role} role (you are {member.role})")
    return set_acting(ws, user, member.role)


def viewer(ws_id: int = Path(...), db: Session = Depends(get_session), user: str = Depends(current_user)) -> m.Workspace:
    return _workspace(db, ws_id, user, "viewer")


def editor(ws_id: int = Path(...), db: Session = Depends(get_session), user: str = Depends(current_user)) -> m.Workspace:
    return _workspace(db, ws_id, user, "editor")


def admin(ws_id: int = Path(...), db: Session = Depends(get_session), user: str = Depends(current_user)) -> m.Workspace:
    return _workspace(db, ws_id, user, "admin")


def dataset_of(db: Session, ws: m.Workspace, ds_id: int) -> m.Dataset:
    ds = db.get(m.Dataset, ds_id)
    if not ds or ds.workspace_id != ws.id or ds.id in hidden_dataset_ids(db, ws):
        raise HTTPException(404, "Dataset not found")
    return ds
