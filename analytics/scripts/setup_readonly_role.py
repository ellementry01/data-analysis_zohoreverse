"""Give the app a read-only database login for user- and AI-authored queries (QA_REPORT risk R5, Phase 8).

From analytics/ on the host, with the Docker stack running:
    python scripts/setup_readonly_role.py
It makes a new random password (never printed), creates or updates the `ellementry_reader` role inside the app's
database container, and writes READONLY_DATABASE_URL into analytics/.env (keeping a copy of the old file as .env.bak).
Then recreate the app: docker compose up -d --force-recreate app
Run it again at any time to change the password.
"""
from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # analytics/
ENV = os.path.join(HERE, ".env")
ROLE = "ellementry_reader"
CONTAINER = os.environ.get("APP_CONTAINER", "ellementry-app-1")
KEY = "READONLY_DATABASE_URL"


def main() -> int:
    password = secrets.token_urlsafe(32)
    r = subprocess.run(["docker", "exec", "-i", CONTAINER, "python", "-m", "app.services.readonly_role", ROLE],
                       input=password + "\n", capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write("Setting up the role failed:\n" + (r.stderr or r.stdout)[-2000:] + "\n")
        return 1
    print(r.stdout.strip())
    url = f"postgresql+psycopg://{ROLE}:{password}@db:5432/ellementry_analytics"
    lines = open(ENV, encoding="utf-8").read().splitlines() if os.path.exists(ENV) else []
    if os.path.exists(ENV):
        shutil.copyfile(ENV, ENV + ".bak")
    lines = [x for x in lines if not x.startswith(KEY + "=")]
    lines.append(f"{KEY}={url}")
    with open(ENV, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    print(f"{KEY} written to analytics/.env (password not shown). Now: docker compose up -d --force-recreate app")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
