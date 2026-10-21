"""
Runs warehouse commands with the admin login from .env (ADMIN_DATABASE_URL), without ever printing it.

    python dw.py loader load ERP_RETAIL_SALES <file>            # any `python -m loader ...` command
    python dw.py transform run [database]                       # defaults to the database in the URL
    python dw.py seeds [database]                               # load the reviewed seed CSVs
    python dw.py build <new_database>                           # fresh schema build (build_db.sh)
    python dw.py psql [-c "SQL"] [-f file.sql]                  # psql on the warehouse
    python dw.py backup [file]                                  # pg_dump --format=custom, then verified

Set DW_DATABASE to point any command at another database (e.g. a trial copy).
"""
from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent
PG_BIN = Path(os.environ.get("PG_BIN", r"C:\Program Files\PostgreSQL\18\bin"))


def pg_env() -> tuple[dict, str]:
    url = os.environ.get("ADMIN_DATABASE_URL") or dotenv_values(HERE / ".env").get("ADMIN_DATABASE_URL")
    if not url:
        sys.exit("ADMIN_DATABASE_URL is not set (warehouse/.env)")
    u = urlsplit(url)
    db = os.environ.get("DW_DATABASE") or u.path.lstrip("/")
    env = dict(os.environ, PGHOST=u.hostname or "localhost", PGPORT=str(u.port or 5432), PGUSER=unquote(u.username or ""),
               PGPASSWORD=unquote(u.password or ""), PGDATABASE=db)
    env.pop("DATABASE_URL", None)            # the loader would prefer it over the PG* variables
    env["PATH"] = str(PG_BIN) + os.pathsep + env.get("PATH", "")
    return env, db


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__); return 2
    env, db = pg_env()
    cmd, rest = argv[0], argv[1:]
    if cmd == "loader":
        args = [sys.executable, "-m", "loader", *rest]
    elif cmd == "transform":
        args = [sys.executable, "-m", "transform", *(rest if len(rest) > 1 else [*(rest or ["run"]), db])]
    elif cmd == "seeds":
        args = [sys.executable, "-m", "loader.seeds", rest[0] if rest else db]
    elif cmd == "build":
        args = ["bash", "build_db.sh", rest[0]]
    elif cmd == "psql":
        args = [str(PG_BIN / "psql"), "-v", "ON_ERROR_STOP=1", *rest]
    elif cmd == "backup":
        out = rest[0] if rest else str(HERE.parent.parent / "ellementry_backups" / f"{db}_{dt.datetime.now():%Y-%m-%d_%H%M}.dump")
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run([str(PG_BIN / "pg_dump"), "--format=custom", "--file", out, db], env=env)
        if r.returncode == 0:
            r = subprocess.run([str(PG_BIN / "pg_restore"), "--list", out], env=env, stdout=subprocess.DEVNULL)
        print(f"backup {'OK' if r.returncode == 0 else 'FAILED'}: {out}")
        return r.returncode
    else:
        print(__doc__); return 2
    return subprocess.run(args, cwd=HERE, env=env).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
