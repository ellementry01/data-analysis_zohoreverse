"""Request dependencies: session, current user and workspace role checks.

Local-first auth model: the user is identified by the X-User-Email header (defaults to DEFAULT_USER).
Roles are enforced per workspace: viewer < editor < admin.
"""
from fastapi import Depends, Header, HTTPException, Path
from sqlalchemy.orm import Session

from . import models as m
from .config import get_settings
from .db import get_session

ROLE_ORDER = {"viewer": 0, "editor": 1, "admin": 2}


def current_user(x_user_email: str | None = Header(default=None)) -> str:
    email = (x_user_email or get_settings().default_user).strip().lower()
    if not email or len(email) > 200:
        raise HTTPException(400, "Invalid user")
    return email


def _workspace(db: Session, ws_id: int, user: str, min_role: str) -> m.Workspace:
    ws = db.get(m.Workspace, ws_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    member = next((x for x in ws.members if x.user_email == user), None)
    if not member:
        raise HTTPException(403, "You are not a member of this workspace")
    if ROLE_ORDER[member.role] < ROLE_ORDER[min_role]:
        raise HTTPException(403, f"This action requires the {min_role} role (you are {member.role})")
    return ws


def viewer(ws_id: int = Path(...), db: Session = Depends(get_session), user: str = Depends(current_user)) -> m.Workspace:
    return _workspace(db, ws_id, user, "viewer")


def editor(ws_id: int = Path(...), db: Session = Depends(get_session), user: str = Depends(current_user)) -> m.Workspace:
    return _workspace(db, ws_id, user, "editor")


def admin(ws_id: int = Path(...), db: Session = Depends(get_session), user: str = Depends(current_user)) -> m.Workspace:
    return _workspace(db, ws_id, user, "admin")


def dataset_of(db: Session, ws: m.Workspace, ds_id: int) -> m.Dataset:
    ds = db.get(m.Dataset, ds_id)
    if not ds or ds.workspace_id != ws.id:
        raise HTTPException(404, "Dataset not found")
    return ds
