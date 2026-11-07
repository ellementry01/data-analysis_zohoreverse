"""Memory page and "Remember this?" cards (Phase 4). Everything here is per person: you see and change your own
memories, team facts, and decisions others chose to share; workspace admins also approve team facts.
Switched off unless ASSISTANT_MEMORY is true."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import models as m
from ..config import get_settings
from ..db import get_session
from ..deps import current_user, viewer
from ..serializers import iso
from ..services import audit, jobs, memory
from ..services.catalog import load_catalog

router = APIRouter(prefix="/api/workspaces/{ws_id}/memory", tags=["memory"])
ACTIONS = ("accept", "reject", "retire", "restore", "keep", "share", "unshare", "approve_share", "reject_share")


def _on():
    if not get_settings().assistant_memory:
        raise HTTPException(403, "Assistant memory is switched off (ASSISTANT_MEMORY)")


def _out(db: Session, ws: m.Workspace, user: str, x: m.Memory, dash_names: dict | None = None) -> dict:
    conv = db.get(m.Conversation, x.source_conversation_id) if x.source_conversation_id else None
    own_source = conv is not None and conv.user_email == user
    return {"id": x.id, "layer": x.layer, "kind": x.kind, "scope": x.scope,
            "scope_label": _scope_label(x.scope, dash_names or {}), "text": x.text, "rationale": x.rationale,
            "status": x.status, "review_reason": x.review_reason, "origin": x.origin, "visibility": x.visibility,
            "share_status": x.share_status, "mine": x.owner_email == user,
            "owner": x.owner_email if x.owner_email != user else None,
            "can_edit": memory.can_edit(ws, user, x),
            # where it came from: the thread only for its owner; the words are kept even if the chat is deleted
            "source": {"conversation_id": conv.id if own_source else None,
                       "dashboard_key": conv.dashboard_key if own_source else None,
                       "excerpt": x.source_excerpt if x.owner_email == user else ""},
            "created_at": iso(x.created_at), "approved_at": iso(x.approved_at), "last_used_at": iso(x.last_used_at),
            "use_count": x.use_count}


def _scope_label(scope: str, names: dict) -> str:
    if scope.startswith("dashboard:"):
        key = scope.split(":", 1)[1]
        return names.get(key, key)
    if scope.startswith("domain:"):
        return f"All {scope.split(':', 1)[1]} dashboards"
    return "All dashboards"


def _names(db: Session, ws: m.Workspace) -> dict:
    return {d.key: d.name for d in db.query(m.Dashboard).filter_by(workspace_id=ws.id)}


def _get(db: Session, ws: m.Workspace, user: str, mid: int) -> m.Memory:
    x = db.get(m.Memory, mid)
    if x is None or not memory.can_see(db, ws, user, x):
        raise HTTPException(404, "Memory not found")
    return x


@router.get("")
def list_memories(ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session), user: str = Depends(current_user),
                  status: str | None = None, layer: str | None = None, scope: str | None = None,
                  q: str | None = Query(None, max_length=200)):
    _on()
    query = memory.visible_query(db, ws, user)
    if status:
        query = query.filter(m.Memory.status == status)
    else:
        query = query.filter(m.Memory.status != "rejected")
    if layer:
        query = query.filter(m.Memory.layer == layer)
    if scope:
        query = query.filter(m.Memory.scope == scope)
    rows = query.order_by(m.Memory.id.desc()).limit(500).all()
    rows = [x for x in rows if x.owner_email == user or memory._scope_visible(db, ws, x.scope)]
    if q:
        words = memory._norm(q)
        rows = [x for x in rows if words <= memory._norm(f"{x.text} {x.rationale} {x.source_excerpt}")
                or q.lower() in f"{x.text} {x.rationale}".lower()]
    names = _names(db, ws)
    return [_out(db, ws, user, x, names) for x in rows]


@router.get("/proposals")
def proposals(ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session), user: str = Depends(current_user),
              dashboard_key: str | None = None):
    """Your "Remember this?" suggestions; on a dashboard, those about it or that came from its chat, plus global ones."""
    _on()
    rows = db.query(m.Memory).filter_by(workspace_id=ws.id, owner_email=user, status="proposed").order_by(m.Memory.id.desc()).all()
    if dashboard_key:
        convs = {c.id for c in db.query(m.Conversation.id).filter_by(workspace_id=ws.id, user_email=user,
                                                                   dashboard_key=dashboard_key)}
        rows = [x for x in rows if x.scope in ("global", f"dashboard:{dashboard_key}") or x.source_conversation_id in convs]
    names = _names(db, ws)
    return [_out(db, ws, user, x, names) for x in rows[:20]]


class MemoryIn(BaseModel):
    text: str = Field(min_length=3, max_length=500)
    kind: str = Field(pattern="^(preference|fact|decision|caveat|open_question)$")
    scope: str = Field("global", max_length=120)
    rationale: str = Field("", max_length=500)
    visibility: str = Field("private", pattern="^(private|shared)$")
    share_with_team: bool = False


@router.post("", status_code=201)
def create_memory(body: MemoryIn, ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session),
                  user: str = Depends(current_user)):
    _on()
    try:
        scope = memory.resolve_scope(ws, db, body.scope, None)
        x, created = memory.save(db, ws, user, body.text, body.kind, scope, body.rationale, origin="manual",
                                 status="active", cat=load_catalog(db, ws), share=body.share_with_team,
                                 visibility=body.visibility)
    except memory.MemoryInputError as e:
        raise HTTPException(400, str(e))
    if not created:
        raise HTTPException(409, f"You already have this memory (#{x.id})")
    audit.record(user, "memory_saved", ws.id, f"memory:{x.id}", {"kind": x.kind, "scope": x.scope, "origin": "manual"})
    return _out(db, ws, user, x, _names(db, ws))


class MemoryPatch(BaseModel):
    text: str | None = Field(None, min_length=3, max_length=500)
    rationale: str | None = Field(None, max_length=500)
    kind: str | None = Field(None, pattern="^(preference|fact|decision|caveat|open_question)$")
    scope: str | None = Field(None, max_length=120)


@router.patch("/{mid:int}")
def edit_memory(mid: int, body: MemoryPatch, ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session),
                user: str = Depends(current_user)):
    _on()
    x = _get(db, ws, user, mid)
    if not memory.can_edit(ws, user, x):
        raise HTTPException(403, "Only its owner (or a workspace admin, for team facts) can edit this memory")
    if x.status in ("rejected",):
        raise HTTPException(400, "A rejected suggestion can't be edited")
    before = {"text": x.text, "rationale": x.rationale, "kind": x.kind, "scope": x.scope}
    try:
        if body.scope is not None:
            x.scope = memory.resolve_scope(ws, db, body.scope, None)
        if body.kind is not None:
            if x.layer == "shared" and body.kind == "decision":
                raise memory.MemoryInputError("A team fact can't become a decision")
            x.kind = body.kind
            if x.layer != "shared":
                x.layer = memory._layer(body.kind)
    except memory.MemoryInputError as e:
        raise HTTPException(400, str(e))
    if body.text is not None:
        x.text = " ".join(body.text.split())
    if body.rationale is not None:
        x.rationale = body.rationale.strip()
    if x.status == "active":
        x.depends_on = memory.dependencies(load_catalog(db, ws), f"{x.text} {x.rationale}")
    db.commit()
    audit.record(user, "memory_edited", ws.id, f"memory:{x.id}", {"before": before})
    return _out(db, ws, user, x, _names(db, ws))


@router.post("/{mid:int}/{action}")
def memory_action(mid: int, action: str, ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session),
                  user: str = Depends(current_user)):
    _on()
    if action not in ACTIONS:
        raise HTTPException(404, "Unknown action")
    x = _get(db, ws, user, mid)
    try:
        memory.act(db, ws, user, x, action, cat=load_catalog(db, ws) if action in ("accept", "keep", "restore") else None)
    except memory.MemoryInputError as e:
        raise HTTPException(400, str(e))
    audit.record(user, f"memory_{action}", ws.id, f"memory:{x.id}", {"status": x.status, "layer": x.layer})
    return _out(db, ws, user, x, _names(db, ws))


@router.delete("/{mid:int}", status_code=204)
def delete_memory(mid: int, ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session),
                  user: str = Depends(current_user)):
    _on()
    x = _get(db, ws, user, mid)
    if not memory.can_edit(ws, user, x):
        raise HTTPException(403, "Only its owner (or a workspace admin, for team facts) can delete this memory")
    audit.record(user, "memory_deleted", ws.id, f"memory:{x.id}", {"text": x.text[:200], "layer": x.layer})
    db.delete(x)
    db.commit()


@router.get("/share-queue")
def share_queue(ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session), user: str = Depends(current_user)):
    """Team facts suggested by members, waiting for a workspace admin."""
    _on()
    if not memory.is_admin(ws):
        raise HTTPException(403, "Only workspace admins approve team facts")
    rows = db.query(m.Memory).filter_by(workspace_id=ws.id, share_status="pending").filter(
        m.Memory.status.in_(("active", "proposed"))).order_by(m.Memory.id).all()
    names = _names(db, ws)
    return [{**_out(db, ws, user, x, names), "owner": x.owner_email} for x in rows]


@router.get("/profile")
def get_profile(ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session), user: str = Depends(current_user)):
    _on()
    p = db.query(m.UserProfile).filter_by(workspace_id=ws.id, user_email=user).one_or_none()
    queued = db.query(m.Job).filter_by(dedupe_key=f"profile:{ws.id}:{user}", status="queued").count() > 0
    return {"text": p.text if p else "", "version": p.version if p else 0, "edited_by_user": bool(p and p.edited_by_user),
            "updated_at": iso(p.updated_at) if p and p.version else None, "sources": p.sources if p else [],
            "rewrite_queued": queued}


class ProfileIn(BaseModel):
    text: str = Field(max_length=1600)


@router.put("/profile")
def edit_profile(body: ProfileIn, ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session),
                 user: str = Depends(current_user)):
    _on()
    p = db.query(m.UserProfile).filter_by(workspace_id=ws.id, user_email=user).one_or_none()
    if p is None:
        p = m.UserProfile(workspace_id=ws.id, user_email=user, sources=[], version=0)
        db.add(p)
    p.text, p.edited_by_user = body.text.strip(), True
    p.version = (p.version or 0) + 1
    p.updated_at = memory._now()
    db.commit()
    audit.record(user, "profile_edited", ws.id, f"profile:{user}", {})
    return get_profile(ws, db, user)


@router.post("/profile/rewrite", status_code=202)
def rewrite_profile(ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session), user: str = Depends(current_user)):
    """Queue a rewrite of your profile from your memories (one Haiku call, in the background)."""
    _on()
    jobs.enqueue(db, "update_profile", {"workspace_id": ws.id, "user_email": user}, dedupe_key=f"profile:{ws.id}:{user}")
    return {"queued": True}


@router.get("/stats")
def stats(ws: m.Workspace = Depends(viewer), db: Session = Depends(get_session), user: str = Depends(current_user)):
    """How useful the suggestions are: of the learned (inferred) suggestions you decided on, how many you accepted."""
    _on()
    mine = db.query(m.Memory).filter_by(workspace_id=ws.id, owner_email=user)
    count = {s: mine.filter(m.Memory.status == s).count() for s in memory.STATUSES}
    inferred = mine.filter(m.Memory.origin == "inferred")
    decided = inferred.filter(m.Memory.status != "proposed").count()
    rejected = inferred.filter(m.Memory.status == "rejected").count()
    return {"counts": count, "inferred_decided": decided,
            "acceptance_rate": round((decided - rejected) / decided, 3) if decided else None,
            "share_queue": db.query(m.Memory).filter_by(workspace_id=ws.id, share_status="pending").count()
            if memory.is_admin(ws) else None}
