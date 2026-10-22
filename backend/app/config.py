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
    database_url: str = "postgresql+psycopg://postgres@localhost:5432/lumen_analytics"
    # Optional dedicated read-only login used for AI / ad-hoc SQL. Falls back to database_url
    # with a READ ONLY transaction, statement timeout and schema scoping.
    readonly_database_url: str | None = None

    # Metadata lives in its own schema; each workspace's analytical data lives in schema ws_<id>.
    meta_schema: str = "lumen_meta"

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

    default_user: str = "owner@local"
    # Pin "today" (YYYY-MM-DD) for reproducible relative date ranges in tests/demos; empty = real date.
    today_override: str | None = None
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    enable_scheduler: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()


def today():
    from datetime import date

    s = get_settings()
    return date.fromisoformat(s.today_override) if s.today_override else date.today()
