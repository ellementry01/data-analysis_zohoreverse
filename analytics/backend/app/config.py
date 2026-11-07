"""Runtime configuration. Every secret comes from the environment (or backend/.env)."""
import os
import re
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_ALLOWED_MODEL = re.compile(r"^claude-(haiku|sonnet)-[0-9a-z-]+$")


def check_model(model: str) -> str:
    """Only Claude Haiku / Sonnet IDs are permitted; Opus, Fable and Mythos are refused by policy."""
    m = (model or "").strip().lower()
    if any(w in m for w in ("opus", "fable", "mythos")) or not _ALLOWED_MODEL.match(m):
        raise ValueError(f"Model '{model}' is not allowed: only Claude Haiku and Claude Sonnet models may be configured")
    return m


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=os.path.join(BACKEND_DIR, ".env"), env_file_encoding="utf-8", extra="ignore")

    # Primary application database. Passwords may be omitted when supplied by pgpass.conf / PGPASSWORD.
    database_url: str = "postgresql+psycopg://postgres@localhost:5432/ellementry_analytics"
    # Optional dedicated read-only login used for AI / ad-hoc SQL. Falls back to database_url
    # with a READ ONLY transaction, statement timeout and schema scoping.
    readonly_database_url: str | None = None

    # Metadata lives in its own schema; each workspace's analytical data lives in schema ws_<id>.
    meta_schema: str = "ellementry_meta"

    upload_dir: str = os.path.join(BACKEND_DIR, "data", "uploads")
    max_upload_mb: int = 200

    # Query guard rails
    query_timeout_ms: int = 15000
    query_row_limit: int = 5000
    ai_query_timeout_ms: int = 10000

    # Optional OpenAI-compatible LLM (OpenAI, Azure OpenAI, Ollama, LM Studio, vLLM, OpenRouter, ...)
    llm_base_url: str | None = None
    llm_api_key: str | None = None
    llm_model: str = "gpt-4o-mini"
    llm_timeout_s: float = 60.0

    # Anthropic Claude (preferred AI provider). Routing: Haiku for ordinary questions, Sonnet for complex ones.
    # Only Claude Haiku / Sonnet model IDs are accepted - Opus, Fable and Mythos are rejected at startup.
    anthropic_api_key: str | None = None
    anthropic_simple_model: str = "claude-haiku-5-5"
    anthropic_complex_model: str = "claude-sonnet-5-5"

    @field_validator("anthropic_simple_model", "anthropic_complex_model")
    @classmethod
    def _only_haiku_or_sonnet(cls, v: str) -> str:
        return check_model(v)

    # AI spend caps, in rupees (0 = no cap). When a cap is reached Claude is not called and the offline engine
    # answers with a note. Placeholder values until the owner sets the budget (AI_ASSISTANTS_PLAN.md, open question 5).
    ai_daily_limit_user_inr: float = 100.0
    ai_monthly_limit_inr: float = 3000.0
    usd_inr_rate: float = 88.0
    # Optional JSON overriding the per-model prices in services/ai_usage.py (USD per million tokens), e.g.
    # {"claude-haiku-5-5": {"input": 0.1, "output": 0.5, "cache_read": 0.01, "cache_write": 0.125}}
    ai_prices_json: str | None = None

    # Assistant features, switched on phase by phase after each phase's gate (docs/AI_ASSISTANTS_PLAN.md).
    assistant_dashboard_chat: bool = False
    assistant_agent_loop: bool = False   # Phase 2: multi-step answers with tools in the dashboard chat
    assistant_memory: bool = False
    assistant_data_issues: bool = False   # Phase 5: issue register, tile notes, worth a look
    assistant_global: bool = False
    assistant_scheduled: bool = False

    # Sign-in (Phase 3). "dev": identity from the X-User-Email header or DEFAULT_USER, for local development and tests
    # only (refused unless PUBLIC_BASE_URL is localhost). "google": Google Workspace sign-in (OIDC), sessions in a
    # secure cookie, scripts use API tokens (Authorization: Bearer).
    auth_mode: str = "dev"
    public_base_url: str = "http://localhost:8000"   # where users reach the app; Google redirects back here
    google_client_id: str | None = None
    google_client_secret: str | None = None          # secret: env only, never printed
    google_allowed_domain: str | None = None         # e.g. ellementry.com; required in google mode
    session_hours: int = 12                          # absolute session length
    session_idle_hours: int = 4                      # signed out after this long without a request
    bootstrap_admins: str = ""                       # comma-separated emails made platform admins (and workspace admins) on sign-in

    @field_validator("auth_mode")
    @classmethod
    def _auth_mode(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in ("dev", "google"):
            raise ValueError("AUTH_MODE must be 'dev' or 'google'")
        return v

    default_user: str = "owner@local"
    # Pin "today" (YYYY-MM-DD) for reproducible relative date ranges in tests/demos; empty = real date.
    today_override: str | None = None
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    enable_scheduler: bool = True
    # The background job queue (services/jobs.py) runs inside the app's scheduler unless this is false (for example
    # when a separate `python -m app.worker` process runs it).
    enable_worker: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()


def today():
    from datetime import date

    s = get_settings()
    return date.fromisoformat(s.today_override) if s.today_override else date.today()
