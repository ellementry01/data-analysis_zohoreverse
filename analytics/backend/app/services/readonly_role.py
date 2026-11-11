"""The read-only database login for user- and AI-authored queries (QA_REPORT risk R5, Phase 8).

`run_readonly` already uses a READ ONLY transaction, a timeout and the workspace's search_path, and every statement passes
`validate_select`. With READONLY_DATABASE_URL set, it also runs as a login that can only read the workspace schemas
(ws_*): it has no access to the app's own tables (ellementry_meta: users, sessions, tokens, conversations, memories), and
the database refuses any write even if every other guard failed.

Run inside the app container (it connects as the app's owner login), with the password on stdin:
    python -m app.services.readonly_role [role]
`scripts/setup_readonly_role.py` does this from the host and writes READONLY_DATABASE_URL into analytics/.env.
"""
from __future__ import annotations

import re
import sys

from sqlalchemy import text
from sqlalchemy.engine import Connection

from .naming import q

_SAFE_PASSWORD = re.compile(r"^[A-Za-z0-9_\-]{20,}$")


def setup(conn: Connection, role: str, password: str) -> list[str]:
    """Create or update the role and grant it every workspace schema. Returns the schemas granted."""
    if not _SAFE_PASSWORD.match(password or ""):
        raise ValueError("The password must be at least 20 letters, digits, '-' or '_'")
    exists = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).first()
    verb = "ALTER" if exists else "CREATE"
    # a password cannot be a bind parameter in CREATE/ALTER ROLE; it is checked against _SAFE_PASSWORD above
    conn.exec_driver_sql(f"{verb} ROLE {q(role)} LOGIN PASSWORD '{password}' NOSUPERUSER NOCREATEDB NOCREATEROLE "
                         f"NOINHERIT NOREPLICATION")
    conn.execute(text(f"ALTER ROLE {q(role)} SET default_transaction_read_only = on"))
    conn.execute(text(f"ALTER ROLE {q(role)} SET statement_timeout = '15s'"))
    db = conn.execute(text("SELECT current_database()")).scalar()
    conn.execute(text(f"GRANT CONNECT ON DATABASE {q(db)} TO {q(role)}"))
    conn.execute(text(f"REVOKE ALL ON SCHEMA public FROM {q(role)}"))
    from . import warehouse

    schemas = [r[0] for r in conn.execute(text(r"SELECT nspname FROM pg_namespace WHERE nspname LIKE 'ws\_%' ORDER BY 1"))]
    for s in schemas:
        warehouse.grant_reader(conn, s)
    return schemas


def main() -> int:
    from ..config import get_settings
    from ..db import get_engine

    role = sys.argv[1] if len(sys.argv) > 1 else get_settings().readonly_role
    password = sys.stdin.readline().strip()
    get_settings().readonly_role = role
    with get_engine().begin() as conn:
        schemas = setup(conn, role, password)
    print(f"Role {role} ready; workspace schemas granted: {len(schemas)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
