# 07 — Running, configuring, testing

The machine is Windows 10. Shells are PowerShell 5.1 and Git Bash. Use absolute paths.

## Docker (the main way it runs now)
- The compose project is named **`ellementry`**, with containers `ellementry-db-1` (postgres:16-alpine) and `ellementry-app-1` (image `ellementry-analytics:latest`).
- App: http://localhost:8000. Database: `127.0.0.1:5433` (user `ellementry`, database `ellementry_analytics`).
- Volumes: `ellementry_pgdata` and `ellementry_uploads`. **`docker compose down -v` deletes all data**, so don't run it without asking.
- `analytics/.env` is git-ignored and must never be printed. It holds these names only:
  - `POSTGRES_PASSWORD`
  - `ELLEMENTRY_CONN_ELLEMENTRY_PASSWORD`
  - `ANTHROPIC_API_KEY`
  - the template is `.env.docker.example`
- Commands (from `analytics/`):
```bash
docker compose up -d --build                 # rebuild after code changes
docker compose up -d --force-recreate app    # REQUIRED after editing .env — plain `up -d` / `restart` may not reload it
docker compose logs -f app
docker compose ps
```
- From inside the container, the host's PostgreSQL 18 is reached at `host.docker.internal:5432`.

## Local (without Docker)
- `scripts\setup.ps1 -DbUser postgres` creates the databases and a venv, installs dependencies, migrates and builds the UI. It was used only for the first setup.
- `start.bat` or `scripts\start.ps1` serves the built UI and API on :8000. `scripts\start.ps1 -Dev` runs Vite on :5173 and uvicorn with `--reload` on :8000.
- `backend/.env` sets `DATABASE_URL=postgresql+psycopg://dw_owner@localhost:5432/ellementry_analytics` (host PostgreSQL 18), with the password in the file. It also has an empty `ANTHROPIC_API_KEY`, so local runs fall back to the offline engine unless the user fills it in.
- **Python note:** the bare `pip` on PATH belongs to a different interpreter. Use `python -m pip install …`.

## Environment variables (`config.Settings`)
| Var | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://postgres@localhost:5432/ellementry_analytics` | Overridden by `backend/.env` / compose |
| `READONLY_DATABASE_URL` | unset | Optional separate read-only login |
| `ANTHROPIC_API_KEY` | unset | Enables Claude |
| `ANTHROPIC_SIMPLE_MODEL` / `ANTHROPIC_COMPLEX_MODEL` | `claude-haiku-5-5` / `claude-sonnet-5-5` | Only Haiku or Sonnet IDs are accepted |
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | unset / `gpt-4o-mini` | OpenAI-compatible fallback, used only when there is no Anthropic key |
| `ELLEMENTRY_SECRET_KEY` | unset | Fernet key for saved connector passwords |
| `ELLEMENTRY_CONN_<NAME>` | — | Connector passwords, referenced by name |
| `QUERY_TIMEOUT_MS` / `AI_QUERY_TIMEOUT_MS` / `QUERY_ROW_LIMIT` | 15000 / 10000 / 5000 | Guard rails |
| `MAX_UPLOAD_MB` | 200 | |
| `UPLOAD_DIR` | `backend/data/uploads` (`/data/uploads` in Docker) | |
| `DEFAULT_USER` | `owner@local` | Identity when there is no `X-User-Email` header |
| `TODAY_OVERRIDE` | unset | Pins "today", e.g. `2026-10-17`, for the tests and ground truth |
| `ENABLE_SCHEDULER` | true | |
| `CORS_ORIGINS` | the :5173 origins | |

## Tests
- Location: `backend/tests/`, using pytest against a **real PostgreSQL** database `ellementry_analytics_test`. `conftest.py` defaults to `dw_owner@localhost`; override it with `TEST_DATABASE_URL`.
- Run them from `backend/`:
```powershell
$env:TODAY_OVERRIDE="2026-10-17"; python -m pytest -q
```
- Current result: **404 passed**, in about 2 minutes. About 80 s of that is building the demo workspace once.
- Test files:
  - `test_ingest`, `test_query_engine`, `test_datasets_api`, `test_dashboards`
  - `test_assistant` (NL plus a mocked OpenAI-compatible LLM)
  - `test_claude` (routing, escalation, safety and fallback, with a fake Anthropic client; it never calls the real API)
  - `test_safety`, `test_security_audit`, `test_hardening`, `test_analytics_units`
  - the end-to-end ground-truth test in `test_assistant`
- In tests, import shared helpers with `from conftest import api, build_mini`; relative imports don't work.
- Frontend: `cd frontend; npm run typecheck; npm run build`.
- **Live AI checks cost real money.** Get the user's OK first, and keep them short.

## Warehouse (ellementry_dw)
Run these from `ellementry-analytics/warehouse/` (details in its README and in 08):
```bash
python dw.py backup                       # before any load
python load_manifest.py ../exports        # load new exports listed in ../exports/MANIFEST.tsv
python dw.py transform run                # rebuild; ERROR checks roll everything back
python reconcile.py ../exports            # files vs warehouse, must say N of N agree
```
Then sync workspace 34. Each dataset has a Sync button, or `POST /api/workspaces/34/datasets/{id}/sync`; the hourly scheduler also does it.

## Demo data
- `sample_data/generate.py` (seed 42) writes 11 messy files for a synthetic home and kitchen brand, plus `ground_truth.json`, which is computed independently with pandas.
- The Docker image pre-generates the files at build time.
- `POST /api/demo` builds a demo workspace through the public API. The user **deleted the demo workspace from the app**, but the feature remains, and the tests use it.
