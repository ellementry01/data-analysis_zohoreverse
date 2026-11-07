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
| `AI_DAILY_LIMIT_USER_INR` / `AI_MONTHLY_LIMIT_INR` | 100 / 3000 | Spend caps in rupees (0 = off): per user per Indian calendar day, and for everyone per month. When reached, Claude is not called and the offline engine answers with a note. Placeholders until the owner sets the budget |
| `USD_INR_RATE` | 88 | Converts the per-token prices (USD) into the rupee estimates in `ai_usage` |
| `AI_PRICES_JSON` | unset | Overrides the built-in model prices in `services/ai_usage.py` (USD per million tokens) |
| `ASSISTANT_DASHBOARD_CHAT`, `ASSISTANT_AGENT_LOOP`, `ASSISTANT_MEMORY`, `ASSISTANT_GLOBAL`, `ASSISTANT_SCHEDULED` | false | Assistant features, switched on phase by phase (`docs/AI_ASSISTANTS_PLAN.md`); reported in `/api/me`. `ASSISTANT_DASHBOARD_CHAT=true` is set in `analytics/.env` since 2026-11-07 (admins only); a copy of the `.env` from before is in `backups/` |
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
- Current result: **465 passed** (2026-11-07), in about 3 minutes. About 80 s of that is building the demo workspace once.
- Test files:
  - `test_ingest`, `test_query_engine`, `test_datasets_api`, `test_dashboards`
  - `test_assistant` (NL plus a mocked OpenAI-compatible LLM)
  - `test_claude` (routing, escalation, safety and fallback, with a fake Anthropic client; it never calls the real API)
  - `test_dashboard_chat` (Phase 1: access, the dashboard pack, screen-state validation, recomputed screen numbers, filter inheritance, threads, feedback, the eval runner on dashboards)
- `test_assistant_groundwork` (dashboard keys and the 0002 migration round trip, conversation scopes, the AI usage ledger and spend caps, feature flags, the test harness itself, the eval runner)
- **Scripted Claude for tests:** `tests/fakes.py` (`FakeMessages`, `turn`, `say`, `tool_call`) and the `fake_claude` fixture. It also enforces the rules: Haiku/Sonnet only, no `temperature`/`fallbacks`, no forced `tool_choice`, and the tool-loop contract (every `tool_use` answered by a `tool_result` in one user message). Use it for every new test that touches Claude.
- **Evaluation sets:** `backend/evals/` (`python -m evals run <set>` from `backend/`, against the running app; needs `pyyaml` from `requirements-dev.txt`). Expected numbers come from SQL or a QuerySpec run at eval time. Without `--live` the free offline engine answers; `--live` uses Claude and refuses to start unless `EVAL_LIVE_OK=1` (owner's OK first). Sets live in `evals/sets/`: `sample.yaml` and `dashboard_basic.yaml` (80 questions, 8 per dashboard; expected values from the dashboard's own widgets with the same filters). The runner checks the number, named labels, required mentions and that every number in an answer comes from its data, and deletes the threads it creates. The offline engine scored 15/80 on 2026-11-07 (it can't use dashboard context): that run only proves the wiring.
  - `test_safety`, `test_security_audit`, `test_hardening`, `test_analytics_units`
  - the end-to-end ground-truth test in `test_assistant`
- In tests, import shared helpers with `from conftest import api, build_mini`; relative imports don't work.
- Frontend: `cd frontend; npm run typecheck; npm run build`.
- **Live AI checks cost real money.** Get the user's OK first, and keep them short.

## Warehouse (ellementry_dw)
Run these from `warehouse/` (details in its README and in 08):
```bash
python dw.py backup                       # before any load or migration
python dw.py psql --single-transaction -f sql/<NNN>_<name>.sql   # a new migration; first with DW_DATABASE=ellementry_dw_trial
python load_manifest.py ../exports        # load new exports listed in ../exports/MANIFEST.tsv
python dw.py transform run                # rebuild; ERROR checks roll everything back
python reconcile.py ../exports            # files vs warehouse, must say 28 of 28 agree
DW_DATABASE=dw_test_po python dw.py pytest -q   # warehouse tests, never on ellementry_dw
```
- Warehouse suite (2026-11-03, schema 2.15): **85 passed, 7 skipped** in about 77 minutes; each transform test module rebuilds the test database (~9 minutes).
- **Test database `dw_test_po`:** a disposable, seeded copy with the sample files loaded (the transform tests need data). Apply every new migration to it as well (`DW_DATABASE=dw_test_po python dw.py psql --single-transaction -f sql/<file>`, then `python dw.py seeds dw_test_po`). Otherwise the transform tests fail at setup with "relation/column does not exist". The full suite takes about 77 minutes; run it in the background, or one module with `-k`.

Backups of the app's own database (Docker), into the project's `backups/` folder:
```bash
docker exec ellementry-db-1 sh -c 'pg_dump -U "$POSTGRES_USER" -Fc -f /tmp/app.dump ellementry_analytics'
docker cp ellementry-db-1:/tmp/app.dump backups/ellementry_analytics_<date>.dump
MSYS_NO_PATHCONV=1 docker exec ellementry-db-1 rm -f /tmp/app.dump
```
If pg_dump fails with "cache lookup failed for index", the app was re-syncing datasets (it does on start-up and hourly): wait a minute and retry.

Then, from `analytics/` on the host (the scripts call the app's API on :8000), sync the app and rebuild the dashboards:
```bash
python scripts/configure_warehouse_workspace.py   # sync datasets, import new views, metrics, calculated columns
python scripts/build_executive_dashboards.py      # rebuild the 10 dashboards (ids change), flag empty widgets
python scripts/update_dashboard_widgets.py Stock Fulfilment   # update named dashboards in place (ids kept)
```
Each dataset also has a Sync button (`POST /api/workspaces/34/datasets/{id}/sync`), and the hourly scheduler syncs too.

## ERP downloads (Expand smERP, in the built-in browser)
The user signs in themselves; the agent only downloads reports. Report centre: `Report/ReportLinkCentre.aspx?ReportModuleIndex=N` (3 Sales, 4 Purchase, 7 Inventory). Steps: pick **Custom date** in the box in front of the dates → choose From / To → **Set Date** → tick **Consolidated** → choose **Excel** → click the arrow in front of the report. Files land in `C:\Users\Dileep\Downloads`; copy them to `exports/_originals/erp_<date>/`. Widen the browser to 1400×900 first (the narrow layout hides the controls). Known ERP failures: Document Wise Stock Movement *Details* ("Divide by zero"; Summary works), Purchase Register ("Employee is not associated with any Department"), Customer Information Sheet (needs a contact).

## Demo data
- `sample_data/generate.py` (seed 42) writes 11 messy files for a synthetic home and kitchen brand, plus `ground_truth.json`, which is computed independently with pandas.
- The Docker image pre-generates the files at build time.
- `POST /api/demo` builds a demo workspace through the public API. The user **deleted the demo workspace from the app**, but the feature remains, and the tests use it.
