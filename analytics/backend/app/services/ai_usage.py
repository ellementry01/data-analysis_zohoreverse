"""AI usage ledger and spend caps.

Every Claude call is recorded in `ai_usage` (who, for what, which model, tokens, estimated cost in rupees). Before a
call, `check_budget()` refuses it when the user's daily cap or the monthly cap for all users is reached; callers then
answer with the offline engine and say why.

Who the call is for comes from `ai_context(...)`, set by the request handler (contextvars, so it is per request).
"""
from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from .. import models as m
from ..config import get_settings

log = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))  # India has no daylight saving: a fixed offset is exact

# USD per million tokens (Anthropic first-party API). Haiku 5.5 is priced higher above a 100K-token prompt.
# Cache writes (5-minute TTL) cost 1.25x input, cache reads 0.1x input.
PRICES: dict[str, dict] = {
    "claude-haiku-5-5": {"input": 0.10, "output": 0.50, "cache_read": 0.01, "cache_write": 0.125,
                         "long_prompt_tokens": 100_000,
                         "long": {"input": 0.50, "output": 2.50, "cache_read": 0.05, "cache_write": 0.625}},
    "claude-sonnet-5-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20, "cache_write": 2.50},
}
FALLBACK_MODEL = "claude-sonnet-5-5"  # an unknown model is costed at the dearer allowed model, never at zero


class BudgetExceeded(RuntimeError):
    """A spend cap is reached; Claude must not be called."""


@dataclass(frozen=True)
class AIContext:
    user: str = "system"
    workspace_id: int | None = None
    conversation_id: int | None = None
    purpose: str = "chat"


_ctx: ContextVar[AIContext] = ContextVar("ai_context", default=AIContext())


def current() -> AIContext:
    return _ctx.get()


@contextmanager
def ai_context(**fields):
    """Set (part of) the context for the Claude calls made inside the block."""
    token = _ctx.set(replace(_ctx.get(), **fields))
    try:
        yield
    finally:
        _ctx.reset(token)


def prices() -> dict[str, dict]:
    raw = get_settings().ai_prices_json
    if not raw:
        return PRICES
    try:
        override = json.loads(raw)
        return {**PRICES, **{k: v for k, v in override.items() if isinstance(v, dict)}}
    except json.JSONDecodeError:
        log.warning("AI_PRICES_JSON is not valid JSON; using the built-in prices")
        return PRICES


def cost_inr(model: str, usage: dict) -> float:
    table = prices()
    p = table.get(model) or table[FALLBACK_MODEL]
    inp = int(usage.get("input_tokens") or 0)
    out = int(usage.get("output_tokens") or 0)
    cr = int(usage.get("cache_read_input_tokens") or 0)
    cw = int(usage.get("cache_creation_input_tokens") or 0)
    if "long" in p and inp + cr + cw > p.get("long_prompt_tokens", 10**12):
        p = {**p, **p["long"]}
    usd = (inp * p["input"] + out * p["output"] + cr * p["cache_read"] + cw * p["cache_write"]) / 1_000_000
    return round(usd * get_settings().usd_inr_rate, 4)


def _session():
    from ..db import SessionLocal, get_engine

    get_engine()
    return SessionLocal()


def _day_start(now: datetime) -> datetime:
    local = now.astimezone(IST)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def _month_start(now: datetime) -> datetime:
    return _day_start(now).replace(day=1)


def spent_inr(user: str | None, since: datetime) -> float:
    with _session() as db:
        q = db.query(func.coalesce(func.sum(m.AIUsage.cost_inr), 0.0)).filter(m.AIUsage.created_at >= since)
        if user is not None:
            q = q.filter(m.AIUsage.user_email == user)
        return float(q.scalar() or 0.0)


def check_budget(user: str | None = None, now: datetime | None = None) -> None:
    """Raise BudgetExceeded when the user's daily cap or the monthly cap (all users) is reached."""
    s = get_settings()
    now = now or datetime.now(timezone.utc)
    user = user or current().user
    if s.ai_daily_limit_user_inr > 0 and spent_inr(user, _day_start(now)) >= s.ai_daily_limit_user_inr:
        raise BudgetExceeded(f"today's AI limit for {user} (Rs {s.ai_daily_limit_user_inr:,.0f}) is used up")
    if s.ai_monthly_limit_inr > 0 and spent_inr(None, _month_start(now)) >= s.ai_monthly_limit_inr:
        raise BudgetExceeded(f"this month's AI limit for the company (Rs {s.ai_monthly_limit_inr:,.0f}) is used up")


def record(model: str, usage: dict) -> float:
    """Write one ledger row for a Claude call; never raises (a ledger failure must not lose the answer)."""
    ctx = current()
    cost = cost_inr(model, usage)
    try:
        with _session() as db:
            db.add(m.AIUsage(workspace_id=ctx.workspace_id, user_email=ctx.user, conversation_id=ctx.conversation_id,
                             purpose=ctx.purpose, model=model, input_tokens=int(usage.get("input_tokens") or 0),
                             output_tokens=int(usage.get("output_tokens") or 0),
                             cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
                             cache_write_tokens=int(usage.get("cache_creation_input_tokens") or 0), cost_inr=cost))
            db.commit()
    except Exception:  # noqa: BLE001
        log.exception("could not record AI usage")
    return cost
