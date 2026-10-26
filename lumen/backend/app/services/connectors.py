"""External SQL database connectors.

Extensible registry: each connector kind knows how to build a SQLAlchemy URL and how to list tables.
Credentials: a connector stores host/database/user plus EITHER the name of an environment variable
holding the password (`password_env`) OR a password encrypted with LUMEN_SECRET_KEY (Fernet). Plaintext
passwords are never persisted, and never returned by the API. PostgreSQL also honours pgpass.conf.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from urllib.parse import quote_plus

import pandas as pd
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import Session

from .. import models as m

MAX_IMPORT_ROWS = 2_000_000


class ConnectorError(ValueError):
    pass


def _fernet():
    key = os.environ.get("LUMEN_SECRET_KEY")
    if not key:
        return None
    from cryptography.fernet import Fernet

    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_password(pw: str) -> str:
    f = _fernet()
    if not f:
        raise ConnectorError("To save a password, set LUMEN_SECRET_KEY (see README) or use a password environment variable / pgpass")
    return f.encrypt(pw.encode()).decode()


PASSWORD_ENV_PREFIX = "LUMEN_CONN_"
_ENV_NAME = re.compile(r"^LUMEN_CONN_[A-Z0-9_]{1,60}$")


def _check_env_name(name: str) -> None:
    # Only dedicated variables may be referenced; otherwise a connector pointed at an attacker's host
    # could be used to send out unrelated server secrets (LLM_API_KEY, LUMEN_SECRET_KEY, ...).
    if not _ENV_NAME.match(name or ""):
        raise ConnectorError(f"Password variables must be named {PASSWORD_ENV_PREFIX}<NAME> (upper case), e.g. LUMEN_CONN_ERP_PASSWORD")


def _env_value(name: str) -> str | None:
    """Process environment first, then backend/.env (pydantic only loads declared settings from it)."""
    if name in os.environ:
        return os.environ[name]
    from dotenv import dotenv_values

    from ..config import BACKEND_DIR

    return dotenv_values(os.path.join(BACKEND_DIR, ".env")).get(name)


def _password(cfg: dict) -> str | None:
    if cfg.get("password_env"):
        _check_env_name(cfg["password_env"])
        val = _env_value(cfg["password_env"])
        if val is None:
            raise ConnectorError(f"Environment variable {cfg['password_env']} is not set")
        return val
    if cfg.get("password_encrypted"):
        f = _fernet()
        if not f:
            raise ConnectorError("LUMEN_SECRET_KEY is required to decrypt the saved password")
        return f.decrypt(cfg["password_encrypted"].encode()).decode()
    return None


class BaseConnector:
    kind = "base"
    label = "Base"
    default_schema: str | None = None

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def url(self) -> URL | str:
        raise NotImplementedError

    def engine(self) -> Engine:
        return create_engine(self.url(), pool_pre_ping=True, connect_args=self.connect_args())

    def connect_args(self) -> dict:
        return {}

    def list_tables(self) -> list[dict]:
        eng = self.engine()
        try:
            insp = inspect(eng)
            schemas = [self.cfg.get("schema")] if self.cfg.get("schema") else [s for s in insp.get_schema_names()
                                                                                if s not in ("information_schema", "pg_catalog", "pg_toast")
                                                                                and not s.startswith("pg_temp") and not s.startswith("pg_toast")]
            out = []
            for s in schemas:
                for t in insp.get_table_names(schema=s):
                    out.append({"schema": s, "table": t, "type": "table"})
                for v in insp.get_view_names(schema=s):
                    out.append({"schema": s, "table": v, "type": "view"})
            return out
        finally:
            eng.dispose()

    def read_table(self, schema: str | None, table: str, limit: int | None = None) -> pd.DataFrame:
        eng = self.engine()
        try:
            insp = inspect(eng)
            valid = set(insp.get_table_names(schema=schema)) | set(insp.get_view_names(schema=schema))
            if table not in valid:
                raise ConnectorError(f"Table {table} not found")
            prep = eng.dialect.identifier_preparer
            ref = (prep.quote_schema(schema) + "." if schema else "") + prep.quote(table)
            sql = f"SELECT * FROM {ref}"
            lim = min(limit or MAX_IMPORT_ROWS, MAX_IMPORT_ROWS)
            with eng.connect() as conn:
                self.begin_readonly(conn)
                return pd.read_sql(text(f"SELECT * FROM ({sql}) t LIMIT {int(lim)}"), conn)
        finally:
            eng.dispose()

    def begin_readonly(self, conn) -> None:
        pass

    def column_types(self, schema: str | None, table: str) -> dict[str, str]:
        """Ellementry data types declared by the source schema (reliable even when the table is empty)."""
        from sqlalchemy import types as T

        eng = self.engine()
        try:
            cols = inspect(eng).get_columns(table, schema=schema)
        finally:
            eng.dispose()
        out = {}
        for c in cols:
            t = c["type"]
            if isinstance(t, T.Boolean):
                out[c["name"]] = "boolean"
            elif isinstance(t, T.Integer):
                out[c["name"]] = "integer"
            elif isinstance(t, (T.Numeric, T.Float)):
                out[c["name"]] = "decimal"
            elif isinstance(t, T.DateTime):
                out[c["name"]] = "datetime"
            elif isinstance(t, T.Date):
                out[c["name"]] = "date"
            else:
                out[c["name"]] = "text"
        return out


class PostgresConnector(BaseConnector):
    kind = "postgresql"
    label = "PostgreSQL"

    def url(self):
        c = self.cfg
        return URL.create("postgresql+psycopg", username=c.get("user") or None, password=_password(c),
                          host=c.get("host") or "localhost", port=int(c.get("port") or 5432), database=c.get("database"))

    def connect_args(self):
        return {"connect_timeout": 10, "options": "-c default_transaction_read_only=on -c statement_timeout=600000"}

    def begin_readonly(self, conn):
        conn.execute(text("SET TRANSACTION READ ONLY"))


class GenericSQLAlchemyConnector(BaseConnector):
    """Any database with an installed SQLAlchemy driver (MySQL, SQL Server, SQLite, Snowflake, ...)."""

    kind = "sqlalchemy"
    label = "Other SQL (SQLAlchemy URL)"

    def url(self):
        raw = self.cfg.get("url", "")
        if not raw or "://" not in raw:
            raise ConnectorError("Provide a SQLAlchemy URL such as mysql+pymysql://user@host/db")
        pw = _password(self.cfg)
        if pw is not None and "@" in raw:
            scheme, rest = raw.split("://", 1)
            userinfo, host = rest.split("@", 1)
            if ":" not in userinfo:
                raw = f"{scheme}://{userinfo}:{quote_plus(pw)}@{host}"
        return raw


REGISTRY: dict[str, type[BaseConnector]] = {c.kind: c for c in (PostgresConnector, GenericSQLAlchemyConnector)}


def get_connector(conn: m.Connector) -> BaseConnector:
    cls = REGISTRY.get(conn.kind)
    if not cls:
        raise ConnectorError(f"Unknown connector type {conn.kind}")
    return cls(conn.config or {})


def sanitize_config(kind: str, cfg: dict) -> dict:
    if kind not in REGISTRY:
        raise ConnectorError(f"Unknown connector type {kind}")
    allowed = {"host", "port", "database", "user", "schema", "url", "password_env"}
    out = {k: v for k, v in cfg.items() if k in allowed and v not in (None, "")}
    if out.get("password_env"):
        _check_env_name(out["password_env"])
    if cfg.get("password"):
        out["password_encrypted"] = encrypt_password(cfg["password"])
    if kind == "sqlalchemy" and "url" in out:
        u = out["url"]
        if "://" in u and "@" in u.split("://", 1)[1] and ":" in u.split("://", 1)[1].split("@", 1)[0]:
            raise ConnectorError("Do not put the password in the URL; use a password environment variable or saved password")
    return out


def public_config(cfg: dict) -> dict:
    out = {k: v for k, v in (cfg or {}).items() if k != "password_encrypted"}
    out["has_saved_password"] = bool((cfg or {}).get("password_encrypted"))
    return out


def test_connection(conn: m.Connector) -> dict:
    c = get_connector(conn)
    try:
        eng = c.engine()
        with eng.connect() as cx:
            cx.execute(text("SELECT 1"))
        eng.dispose()
        status = "ok"
    except ConnectorError:
        raise
    except Exception as e:
        status = f"error: {str(getattr(e, 'orig', e)).splitlines()[0][:300]}"
    conn.last_tested_at = datetime.now(timezone.utc)
    conn.last_status = status
    return {"status": status}


def sync_dataset(db: Session, ws: m.Workspace, ds: m.Dataset) -> dict:
    from .datasets import import_dataframe

    src = ds.source_info or {}
    conn = db.get(m.Connector, src.get("connector_id"))
    if not conn:
        raise ConnectorError("The connector for this dataset was deleted")
    c = get_connector(conn)
    df = c.read_table(src.get("source_schema"), src["source_table"])
    try:
        types = c.column_types(src.get("source_schema"), src["source_table"])
    except Exception:  # some drivers cannot reflect views; new columns then fall back to inference
        types = None
    import_dataframe(db, ws, ds.name, df, "connector", src, dataset=ds, source_types=types)
    return {"rows": int(len(df))}
