"""One permission check for people and for the assistant.

Access rules (models.AccessRule) restrict a dashboard, a domain of dashboards, or a dataset. A target without rules is
visible to every member of the workspace (so nothing changes until an admin adds rules); a target with rules is
visible only to the members they match, by minimum workspace role or by email. Workspace admins see everything.

The workspace dependencies (deps.viewer/editor/admin) record who is acting on the Workspace object they return
(`acting_user`, `acting_role`). load_catalog, dataset_of and the dashboard lookups read it, so the query engine, the SQL
console, Ask AI and every assistant tool see only what the person asking may see. Code that runs without a person
(scheduled syncs, scripts at the service level) has no acting user and is not restricted.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from .. import models as m

ROLE_ORDER = {"viewer": 0, "editor": 1, "admin": 2}
TARGET_TYPES = ("dashboard", "domain", "dataset")


def acting(ws: m.Workspace) -> tuple[str | None, str | None]:
    return getattr(ws, "acting_user", None), getattr(ws, "acting_role", None)


def set_acting(ws: m.Workspace, user: str | None, role: str | None) -> m.Workspace:
    ws.acting_user, ws.acting_role = user, role
    return ws


def _rules(db: Session, ws_id: int, target_type: str) -> list[m.AccessRule]:
    return db.query(m.AccessRule).filter_by(workspace_id=ws_id, target_type=target_type).all()


def _matches(rule: m.AccessRule, user: str, role: str | None) -> bool:
    if rule.principal_type == "user":
        return rule.principal == user
    return role is not None and ROLE_ORDER.get(role, -1) >= ROLE_ORDER.get(rule.principal, 99)


def can_see_dashboard(db: Session, ws: m.Workspace, dash: m.Dashboard) -> bool:
    if dash.workspace_id != ws.id:
        return False
    user, role = acting(ws)
    if user is None or role == "admin":
        return True
    rules = [r for r in _rules(db, ws.id, "dashboard") if r.target == dash.key]
    if dash.domain:
        rules += [r for r in _rules(db, ws.id, "domain") if r.target == dash.domain]
    return not rules or any(_matches(r, user, role) for r in rules)


def hidden_dataset_ids(db: Session, ws: m.Workspace) -> set[int]:
    user, role = acting(ws)
    if user is None or role == "admin":
        return set()
    by_slug: dict[str, list[m.AccessRule]] = {}
    for r in _rules(db, ws.id, "dataset"):
        by_slug.setdefault(r.target, []).append(r)
    if not by_slug:
        return set()
    hidden_slugs = {slug for slug, rs in by_slug.items() if not any(_matches(r, user, role) for r in rs)}
    if not hidden_slugs:
        return set()
    return {i for (i,) in db.query(m.Dataset.id).filter(m.Dataset.workspace_id == ws.id, m.Dataset.slug.in_(hidden_slugs))}


def visible_dashboards(db: Session, ws: m.Workspace, query=None) -> list[m.Dashboard]:
    q = query if query is not None else db.query(m.Dashboard).filter_by(workspace_id=ws.id)
    return [d for d in q if can_see_dashboard(db, ws, d)]
