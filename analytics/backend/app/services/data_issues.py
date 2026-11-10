"""The data issue register (Phase 5 of docs/AI_ASSISTANTS_PLAN.md).

An issue says what it affects: whole dashboards (by key), metrics (by name) and datasets (by slug). A tile is affected
when its spec uses an affected metric (also through a composite metric) or reads an affected dataset; a dashboard is
affected when it is listed, or any of its tiles is. Only issues that are still live count (open or awaiting
confirmation); parked and solved ones don't.

Where it shows: a note on affected tiles and a "Known data issues" strip on the dashboard (everyone), the dashboard
assistant's context and its get_data_issues tool (so an answer about an affected number says so), and the owner's
notifications when an issue is opened, solved or reopened. Solving an issue sends memories that relied on it to review.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .. import models as m

STATUSES = ("open", "awaiting", "parked", "solved")
LIVE = ("open", "awaiting")
SEVERITIES = ("high", "medium", "low")
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
CODE = re.compile(r"^[A-Z]{1,4}-\d{1,5}$")


class IssueInputError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def clean_affects(db: Session, ws: m.Workspace, affects: dict | None, cat=None) -> dict:
    """Keep only names that exist: dashboard keys of this workspace, metric names, dataset slugs."""
    from .catalog import load_catalog

    a = affects or {}
    cat = cat or load_catalog(db, ws)
    keys = {d.key for d in db.query(m.Dashboard).filter_by(workspace_id=ws.id)}
    slugs = {d.slug for d in cat.datasets.values()}
    out = {"dashboards": sorted({str(x) for x in a.get("dashboards") or [] if str(x) in keys}),
           "metrics": sorted({str(x) for x in a.get("metrics") or [] if str(x) in cat.metrics}),
           "datasets": sorted({str(x) for x in a.get("datasets") or [] if str(x) in slugs})}
    unknown = [str(x) for k, have in (("dashboards", keys), ("metrics", set(cat.metrics)), ("datasets", slugs))
               for x in a.get(k) or [] if str(x) not in have]
    if unknown:
        raise IssueInputError(f"Unknown names in affects: {', '.join(unknown[:10])}")
    return out


def live_issues(db: Session, ws_id: int) -> list[m.DataIssue]:
    rows = db.query(m.DataIssue).filter(m.DataIssue.workspace_id == ws_id, m.DataIssue.status.in_(LIVE)).all()
    return sorted(rows, key=lambda i: (SEVERITY_ORDER.get(i.severity, 9), i.code))


# ----------------------------------------------------------------------------------------------- what they touch

def _widget_metrics(cat, spec: dict) -> set[str]:
    from .agent.context import _expand_composites, _metric_names

    return set(_expand_composites(cat, _metric_names(spec or {})))


def _widget_datasets(cat, spec: dict) -> set[str]:
    from .agent.context import _datasets_of

    ids = _datasets_of(cat, spec or {})
    by_id = {d.id: d.slug for d in cat.datasets.values()}
    out = {by_id[i] for i in ids if i in by_id}
    for n in _widget_metrics(cat, spec):           # composites read the datasets of their parts
        mt = cat.metrics.get(n)
        if mt and mt.dataset_id in by_id:
            out.add(by_id[mt.dataset_id])
    return out


def for_dashboard(db: Session, dash: m.Dashboard, cat) -> list[dict]:
    """Live issues touching a dashboard: [{issue, widget_ids, whole_dashboard}], most severe first."""
    out = []
    widgets = [(w, _widget_metrics(cat, w.spec), _widget_datasets(cat, w.spec)) for w in dash.widgets]
    for i in live_issues(db, dash.workspace_id):
        a = i.affects or {}
        mets, dss = set(a.get("metrics") or []), set(a.get("datasets") or [])
        hit = [w.id for w, wm, wd in widgets if (mets & wm) or (dss & wd)]
        whole = dash.key in (a.get("dashboards") or [])
        if hit or whole:
            out.append({"issue": i, "widget_ids": hit, "whole_dashboard": whole})
    return out


def about(db: Session, ws: m.Workspace, cat, target: str | None, dash: m.Dashboard | None) -> list[m.DataIssue]:
    """Live issues about a dashboard key, a metric or a dataset (the get_data_issues tool)."""
    from .permissions import can_see_dashboard

    t = (target or "").strip()
    if not t and dash is None:
        # the global assistant: every live issue on a dashboard this person can see, or on no dashboard at all
        out = []
        for i in live_issues(db, ws.id):
            keys = (i.affects or {}).get("dashboards") or []
            ds = [d for d in db.query(m.Dashboard).filter(m.Dashboard.workspace_id == ws.id, m.Dashboard.key.in_(keys))] if keys else []
            if not keys or any(can_see_dashboard(db, ws, d) for d in ds):
                out.append(i)
        return out
    if not t or (dash is not None and t == dash.key):
        return [x["issue"] for x in for_dashboard(db, dash, cat)] if dash is not None else []
    d = db.query(m.Dashboard).filter_by(workspace_id=ws.id, key=t).one_or_none()
    if d is not None:
        return [x["issue"] for x in for_dashboard(db, d, cat)] if can_see_dashboard(db, ws, d) else []
    if t in cat.metrics:
        names = {t}
        slug = next((ds.slug for ds in cat.datasets.values() if ds.id == cat.metrics[t].dataset_id), None)
        return [i for i in live_issues(db, ws.id) if names & set((i.affects or {}).get("metrics") or [])
                or (slug and slug in ((i.affects or {}).get("datasets") or []))]
    if t in {d.slug for d in cat.datasets.values()}:
        mets = {n for n, mt in cat.metrics.items() if mt.dataset_id and cat.datasets.get(mt.dataset_id)
                and cat.datasets[mt.dataset_id].slug == t}
        return [i for i in live_issues(db, ws.id) if t in ((i.affects or {}).get("datasets") or [])
                or mets & set((i.affects or {}).get("metrics") or [])]
    m_ = re.match(r"^[A-Za-z]{1,4}-\d+$", t)
    if m_:
        i = db.query(m.DataIssue).filter_by(workspace_id=ws.id, code=t.upper()).one_or_none()
        return [i] if i else []
    raise IssueInputError(f"'{t}' is not a dashboard key, metric, dataset or issue code")


def brief(i: m.DataIssue) -> dict:
    return {"code": i.code, "title": i.title, "status": i.status, "severity": i.severity, "note": i.note or i.title,
            "what_is_needed": i.summary[:600], "affects": i.affects or {}}


def pack_lines(db: Session, dash: m.Dashboard, cat) -> list[str]:
    """For the dashboard assistant's context: the live issues on this dashboard, with the tiles they touch."""
    hits = for_dashboard(db, dash, cat)
    if not hits:
        return []
    titles = {w.id: w.title for w in dash.widgets}
    lines = ["KNOWN DATA ISSUES on this dashboard (from the issue register; when an answer uses a number these touch, "
             "say so briefly with the code, e.g. \"affected by D-112: RTO is recorded only for website orders\"; never "
             "invent issues that are not listed):"]
    for h in hits:
        i = h["issue"]
        where = "the whole dashboard" if h["whole_dashboard"] and not h["widget_ids"] else \
            "; ".join(f'"{titles[w]}"' for w in h["widget_ids"][:8])
        lines.append(f"- {i.code} [{i.severity}, {i.status}] {i.title}. Affects: {where}. Meanwhile: {i.summary[:300]}")
    return lines


# ----------------------------------------------------------------------------------------------- changes

def notify(db: Session, ws_id: int, kind: str, title: str, body: str = "", code: str | None = None) -> None:
    db.add(m.Notification(workspace_id=ws_id, kind=kind, title=title[:300], body=body, issue_code=code, read_by=[]))


def set_status(db: Session, ws: m.Workspace, issue: m.DataIssue, status: str, user: str) -> None:
    if status not in STATUSES:
        raise IssueInputError(f"status must be one of {', '.join(STATUSES)}")
    before = issue.status
    if before == status:
        return
    issue.status, issue.updated_by = status, user
    if status == "solved":
        issue.solved_at = _now()
        notify(db, ws.id, "issue_solved", f"{issue.code} solved: {issue.title}", f"Marked solved by {user}.", issue.code)
    elif before == "solved":
        issue.solved_at = None
        notify(db, ws.id, "issue_reopened", f"{issue.code} reopened: {issue.title}", f"Reopened by {user}.", issue.code)


def after_change(db: Session, ws_id: int) -> None:
    """An issue changed: memories that relied on it go to review; the dashboards' notes are recomputed on read."""
    from ..db import SessionLocal
    from . import memory

    # its own session: the request's Workspace object carries who is acting and must not be touched
    with SessionLocal() as own:
        memory.refresh_staleness(own, own.get(m.Workspace, ws_id))   # no acting user: the full catalog


# ----------------------------------------------------------------------------------------------- the issue log
# (parsed and mapped by scripts/import_issue_log.py)

def import_rows(db: Session, ws: m.Workspace, rows: list[dict], solved_codes: list[str], user: str, cat=None) -> dict:
    """Add issues not in the register yet; mark solved those the log says are solved. Never overwrites what was edited
    in the app (the register is the source of truth after the first import)."""
    have = {i.code: i for i in db.query(m.DataIssue).filter_by(workspace_id=ws.id)}
    added, solved, skipped = [], [], []
    for r in rows:
        code = str(r.get("code") or "").strip().upper()
        if not CODE.match(code):
            raise IssueInputError(f"Bad issue code '{code}'")
        if code in have:
            skipped.append(code)
            continue
        status = r.get("status") or "open"
        if status not in STATUSES:
            raise IssueInputError(f"{code}: bad status '{status}'")
        issue = m.DataIssue(workspace_id=ws.id, code=code, title=str(r.get("title") or code)[:300],
                            area=str(r.get("area") or "")[:80], status=status,
                            status_detail=str(r.get("status_detail") or "")[:120],
                            severity=r.get("severity") if r.get("severity") in SEVERITIES else "medium",
                            summary=str(r.get("summary") or ""), note=str(r.get("note") or r.get("title") or "")[:500],
                            affects=clean_affects(db, ws, r.get("affects"), cat), owner=str(r.get("owner") or "")[:120],
                            source="import", updated_by=user)
        db.add(issue)
        added.append(code)
    for code in solved_codes:
        i = have.get(str(code).upper())
        if i is not None and i.status != "solved":
            set_status(db, ws, i, "solved", user)
            solved.append(i.code)
    if added:
        notify(db, ws.id, "issues_imported", f"{len(added)} data issues imported from the issue log",
               ", ".join(added[:40]))
    db.commit()
    if solved:
        after_change(db, ws.id)
    return {"added": added, "solved": solved, "already_there": skipped}
