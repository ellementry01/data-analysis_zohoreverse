"""Monitoring for platform admins (Phase 8): AI cost per person and per day, answer times, tool errors, thumbs-down
answers with their traces, the background queue, refused requests, and evaluation runs over time."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models as m
from ..db import get_session
from ..deps import platform_admin
from ..services.ai_usage import IST
from ..serializers import iso

router = APIRouter(prefix="/api/admin", tags=["monitor"])

MAX_ANSWERS = 5000   # answers read for the time and error figures (newest first)


def _pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    return round(v[min(len(v) - 1, int(round(p * (len(v) - 1))))], 1)


def _day(t: datetime) -> str:
    return t.astimezone(IST).date().isoformat()


@router.get("/monitor")
def monitor(days: int = Query(14, ge=1, le=90), user: str = Depends(platform_admin), db: Session = Depends(get_session)):
    now = datetime.now(timezone.utc)
    since = (now.astimezone(IST) - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)

    # --- AI cost (the usage ledger: one row per Claude call)
    usage = db.query(m.AIUsage).filter(m.AIUsage.created_at >= since).all()
    by_day: dict[str, dict] = {}
    for i in range(days):
        d = (since + timedelta(days=i)).date().isoformat()
        by_day[d] = {"day": d, "cost_inr": 0.0, "calls": 0}
    by_user: dict[str, dict] = defaultdict(lambda: {"cost_inr": 0.0, "calls": 0, "questions": 0, "rate_limited": 0})
    by_purpose: dict[str, dict] = defaultdict(lambda: {"cost_inr": 0.0, "calls": 0})
    by_model: dict[str, dict] = defaultdict(lambda: {"cost_inr": 0.0, "calls": 0})
    for u in usage:
        d = by_day.setdefault(_day(u.created_at), {"day": _day(u.created_at), "cost_inr": 0.0, "calls": 0})
        for bucket in (d, by_user[u.user_email], by_purpose[u.purpose], by_model[u.model]):
            bucket["cost_inr"] += u.cost_inr or 0
            bucket["calls"] += 1
    for action, key in (("assistant_ask", "questions"), ("rate_limited", "rate_limited")):
        for who, n in (db.query(m.AuditEvent.user_email, func.count(m.AuditEvent.id))
                       .filter(m.AuditEvent.action == action, m.AuditEvent.at >= since)
                       .group_by(m.AuditEvent.user_email)):
            by_user[who][key] = n

    # --- answers: time, model, tool errors, number-check warnings, feedback
    answers = (db.query(m.Message).filter(m.Message.role == "assistant", m.Message.created_at >= since)
               .order_by(m.Message.id.desc()).limit(MAX_ANSWERS).all())
    seconds: list[float] = []
    by_engine: dict[str, list[float]] = defaultdict(list)
    tools: dict[str, dict] = defaultdict(lambda: {"calls": 0, "errors": 0, "last_error": None, "last_error_at": None})
    warned = up = down = 0
    for a in answers:
        p = a.payload or {}
        engine = p.get("model") or a.model or ("offline" if p.get("engine") in (None, "semantic") else p["engine"])
        if isinstance(p.get("seconds"), (int, float)):
            seconds.append(float(p["seconds"]))
            by_engine[engine].append(float(p["seconds"]))
        warned += bool(p.get("warnings"))
        up += a.feedback == "up"
        down += a.feedback == "down"
        for s in (a.tool_trace or p.get("steps") or []):
            if not isinstance(s, dict) or not s.get("tool"):
                continue
            t = tools[s["tool"]]
            t["calls"] += 1
            if s.get("ok") is False:
                t["errors"] += 1
                if t["last_error"] is None:            # newest first
                    t["last_error"], t["last_error_at"] = (s.get("error") or "")[:300], iso(a.created_at)

    # --- background queue
    jobs = dict(db.query(m.Job.status, func.count(m.Job.id)).group_by(m.Job.status).all())
    oldest = db.query(func.min(m.Job.run_after)).filter(m.Job.status == "queued", m.Job.run_after <= now).scalar()
    failed_recent = (db.query(m.Job).filter(m.Job.status == "failed", m.Job.created_at >= since)
                     .order_by(m.Job.id.desc()).limit(10).all())

    return {
        "days": days, "since": since.date().isoformat(),
        "cost": {"total_inr": round(sum(u.cost_inr or 0 for u in usage), 2), "calls": len(usage),
                 "by_day": [{**v, "cost_inr": round(v["cost_inr"], 2)} for _, v in sorted(by_day.items())],
                 "by_user": sorted(({"user": k, **v, "cost_inr": round(v["cost_inr"], 2)} for k, v in by_user.items()),
                                   key=lambda x: (-x["cost_inr"], -x["questions"], x["user"])),
                 "by_purpose": sorted(({"purpose": k, **v, "cost_inr": round(v["cost_inr"], 2)} for k, v in by_purpose.items()),
                                      key=lambda x: -x["cost_inr"]),
                 "by_model": sorted(({"model": k, **v, "cost_inr": round(v["cost_inr"], 2)} for k, v in by_model.items()),
                                    key=lambda x: -x["cost_inr"])},
        "answers": {"count": len(answers), "median_seconds": _pct(seconds, 0.5), "p95_seconds": _pct(seconds, 0.95),
                    "by_engine": sorted(({"engine": k, "count": len(v), "median_seconds": _pct(v, 0.5),
                                         "p95_seconds": _pct(v, 0.95)} for k, v in by_engine.items()),
                                        key=lambda x: -x["count"]),
                    "with_number_warnings": warned, "thumbs_up": up, "thumbs_down": down,
                    "capped": len(answers) >= MAX_ANSWERS},
        "tools": sorted(({"tool": k, **v} for k, v in tools.items()), key=lambda x: (-x["errors"], -x["calls"])),
        "jobs": {"by_status": jobs, "oldest_waiting_seconds": round((now - oldest).total_seconds()) if oldest else 0,
                 "recent_failures": [{"id": j.id, "kind": j.kind, "attempts": j.attempts, "error": (j.last_error or "")[:300],
                                      "at": iso(j.finished_at or j.created_at)} for j in failed_recent]},
    }


@router.get("/monitor/thumbs-down")
def thumbs_down(days: int = Query(30, ge=1, le=365), limit: int = Query(50, ge=1, le=200),
                user: str = Depends(platform_admin), db: Session = Depends(get_session)):
    """Answers people marked as wrong, newest first, with the question, the note and the steps behind the answer."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (db.query(m.Message, m.Conversation).join(m.Conversation, m.Conversation.id == m.Message.conversation_id)
            .filter(m.Message.feedback == "down", m.Message.created_at >= since)
            .order_by(m.Message.id.desc()).limit(limit).all())
    out = []
    for msg, conv in rows:
        q = (db.query(m.Message).filter(m.Message.conversation_id == conv.id, m.Message.role == "user",
                                         m.Message.id < msg.id).order_by(m.Message.id.desc()).first())
        p = msg.payload or {}
        steps = [{"n": s.get("n"), "tool": s.get("tool"), "label": s.get("label"), "ok": s.get("ok"),
                  "error": s.get("error"), "input": s.get("input"), "row_count": s.get("row_count")}
                 for s in (msg.tool_trace or p.get("steps") or []) if isinstance(s, dict)]
        out.append({"message_id": msg.id, "conversation_id": conv.id, "workspace_id": conv.workspace_id,
                    "user": conv.user_email, "scope": conv.scope_type + (f":{conv.dashboard_key}" if conv.dashboard_key else ""),
                    "at": iso(msg.created_at), "question": q.content if q else "", "answer": (msg.content or "")[:4000],
                    "note": msg.feedback_note, "model": p.get("model") or msg.model, "seconds": p.get("seconds"),
                    "warnings": p.get("warnings") or [], "steps": steps})
    return out


# ----------------------------------------------------------------------------------------------- evaluation runs

class Failure(BaseModel):
    id: str = Field(max_length=120)
    problems: list[str] = Field(default_factory=list, max_length=20)


class EvalRunIn(BaseModel):
    set_name: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_\-]+$")
    live: bool = False
    total: int = Field(ge=0)
    passed: int = Field(ge=0)
    numbers_checked: int = Field(0, ge=0)
    numbers_correct: int = Field(0, ge=0)
    invented: int = Field(0, ge=0)
    cost_inr: float = Field(0, ge=0)
    median_seconds: float | None = None
    failures: list[Failure] = Field(default_factory=list, max_length=500)
    git_commit: str = Field("", max_length=40)
    note: str = Field("", max_length=2000)
    created_at: datetime | None = None     # only to record an older run (from the docs)


def _run_out(r: m.EvalRun) -> dict:
    return {"id": r.id, "set_name": r.set_name, "live": r.live, "total": r.total, "passed": r.passed,
            "pass_rate": round(r.passed / r.total, 3) if r.total else None,
            "numbers_checked": r.numbers_checked, "numbers_correct": r.numbers_correct, "invented": r.invented,
            "cost_inr": r.cost_inr, "median_seconds": r.median_seconds, "failures": r.failures,
            "git_commit": r.git_commit, "note": r.note, "created_by": r.created_by, "created_at": iso(r.created_at)}


@router.post("/eval-runs", status_code=201)
def record_eval_run(body: EvalRunIn, user: str = Depends(platform_admin), db: Session = Depends(get_session)):
    if body.passed > body.total or body.numbers_correct > body.numbers_checked:
        raise HTTPException(400, "passed cannot exceed total, nor correct numbers the numbers checked")
    data = body.model_dump()
    data["failures"] = [{"id": f["id"], "problems": [p[:300] for p in f["problems"]]} for f in data["failures"]]
    created = data.pop("created_at") or datetime.now(timezone.utc)
    r = m.EvalRun(**data, created_by=user, created_at=created)
    db.add(r)
    db.commit()
    return _run_out(r)


@router.get("/eval-runs")
def list_eval_runs(set_name: str | None = None, live: bool | None = None, limit: int = Query(200, ge=1, le=1000),
                   user: str = Depends(platform_admin), db: Session = Depends(get_session)):
    q = db.query(m.EvalRun)
    if set_name:
        q = q.filter(m.EvalRun.set_name == set_name)
    if live is not None:
        q = q.filter(m.EvalRun.live == live)
    return [_run_out(r) for r in q.order_by(m.EvalRun.created_at.desc(), m.EvalRun.id.desc()).limit(limit)]
