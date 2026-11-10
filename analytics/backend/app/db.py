from collections.abc import Iterator

from sqlalchemy import MetaData, create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings

settings = get_settings()


class Base(DeclarativeBase):
    metadata = MetaData(schema=settings.meta_schema)


_engine: Engine | None = None
_ro_engine: Engine | None = None
SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)


def _pool() -> dict:
    return {"pool_pre_ping": True, "future": True, "pool_size": settings.db_pool_size,
            "max_overflow": settings.db_max_overflow, "pool_timeout": settings.db_pool_timeout_s}


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(settings.database_url, **_pool())
        SessionLocal.configure(bind=_engine)
    return _engine


def get_readonly_engine() -> Engine:
    """Engine for user/AI-authored SQL. Uses a dedicated read-only role when configured."""
    global _ro_engine
    if _ro_engine is None:
        if settings.readonly_database_url:
            _ro_engine = create_engine(settings.readonly_database_url, **_pool())
        else:
            _ro_engine = get_engine()
    return _ro_engine


def reset_engines(database_url: str | None = None) -> None:
    """Used by tests to point the app at another database."""
    global _engine, _ro_engine
    if database_url:
        settings.database_url = database_url
        settings.readonly_database_url = None
    _engine = None
    _ro_engine = None
    get_engine()


def get_session() -> Iterator[Session]:
    get_engine()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Run Alembic migrations up to head."""
    from alembic import command
    from alembic.config import Config
    import os

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(here, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(here, "alembic"))
    cfg.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    # several server processes start at once (WEB_CONCURRENCY): one migrates, the others wait for it, then find nothing to do
    with get_engine().connect() as lock:
        lock.execute(text("SELECT pg_advisory_lock(7202612)"))
        lock.commit()
        try:
            with get_engine().begin() as conn:
                conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{settings.meta_schema}"'))
            command.upgrade(cfg, "head")
        finally:
            lock.execute(text("SELECT pg_advisory_unlock(7202612)"))
            lock.commit()
