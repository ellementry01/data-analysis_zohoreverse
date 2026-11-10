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
| `ASSISTANT_DASHBOARD_CHAT`, `ASSISTANT_AGENT_LOOP`, `ASSISTANT_MEMORY`, `ASSISTANT_GLOBAL`, `ASSISTANT_SCHEDULED` | false | Assistant features, switched on phase by phase (`docs/AI_ASSISTANTS_PLAN.md`); reported in `/api/me`. `ASSISTANT_DASHBOARD_CHAT=true` and `ASSISTANT_AGENT_LOOP=true` are set in `analytics/.env` since 2026-11-07, `ASSISTANT_MEMORY=true` since Phase 4 (admins only), `ASSISTANT_DATA_ISSUES=true` since Phase 5, `ASSISTANT_GLOBAL=true` since Phase 6 (admins only), `ASSISTANT_SCHEDULED=true` since Phase 7 (admins only); a copy of the `.env` from before is in `backups/` |
| `AUTH_MODE` | `dev` | `dev` (header identity, localhost only) or `google` (company sign-in); see "Company sign-in" below |
| `PUBLIC_BASE_URL` | `http://localhost:8000` | Where users reach the app; Google redirects to `<this>/api/auth/callback`; must be https outside localhost |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_ALLOWED_DOMAIN` | unset | The OAuth client (secret: env only) and the company domain allowed to sign in |
| `SESSION_HOURS` / `SESSION_IDLE_HOURS` | 12 / 4 | Session lifetime and idle sign-out |
| `BOOTSTRAP_ADMINS` | empty | Comma-separated emails made platform admins (and workspace admins) when they sign in |
| `ELLEMENTRY_API_TOKEN` | - | For scripts on the host (not the app): the API token sent as `Authorization: Bearer` |
| `DEFAULT_USER` | `owner@local` | Identity when there is no `X-User-Email` header (dev mode only) |
| `TODAY_OVERRIDE` | unset | Pins "today", e.g. `2026-10-17`, for the tests and ground truth |
| `ENABLE_SCHEDULER` | true | |
| `ENABLE_WORKER` | true | Run the background job queue inside the app's scheduler; set false when a separate `python -m app.worker` process runs it |
| `CORS_ORIGINS` | the :5173 origins | |

## Company sign-in (Google Workspace): switching it on
The code is in place (Phase 3); the live app stays in `AUTH_MODE=dev` until these steps are done. Only the owner does steps 1-4 (they need the company Google admin account and produce a secret).
1. In the Google Cloud console (console.cloud.google.com), signed in with the company Google Workspace account, create a project (e.g. "Ellementry Analytics").
2. APIs & Services -> OAuth consent screen: user type **Internal** (only company accounts can ever sign in), app name "Ellementry Analytics", support email; scopes `openid`, `email`, `profile`.
3. APIs & Services -> Credentials -> Create credentials -> OAuth client ID -> **Web application**. Authorised redirect URI: `http://localhost:8000/api/auth/callback` (add the production `https://.../api/auth/callback` when hosting exists). Copy the client ID and client secret.
4. In `analytics/.env` (never in chat or git) add: `AUTH_MODE=google`, `GOOGLE_CLIENT_ID=...`, `GOOGLE_CLIENT_SECRET=...`, `GOOGLE_ALLOWED_DOMAIN=<company domain>`, `BOOTSTRAP_ADMINS=<owner's email>`, `PUBLIC_BASE_URL=http://localhost:8000`.
5. `docker compose up -d --force-recreate app`, open http://localhost:8000 and sign in. The owner becomes platform admin and admin of every workspace.
6. Administration -> API tokens: create one for scripts and put it in `ELLEMENTRY_API_TOKEN` where scripts run (dashboard builds, `configure_warehouse_workspace.py`, evals). Without it they get 401.
7. Add the COO and others as workspace members (company emails) and, where needed, access rules in workspace Settings.
To go back: remove `AUTH_MODE=google` (or set `dev`) and recreate the app.

## Tests
- Location: `backend/tests/`, using pytest against a **real PostgreSQL** database `ellementry_analytics_test`. `conftest.py` defaults to `dw_owner@localhost`; override it with `TEST_DATABASE_URL`.
- Run them from `backend/`:
```powershell
$env:TODAY_OVERRIDE="2026-10-17"; python -m pytest -q
```
- Current result: **609 passed** (2026-11-10), in about 4 minutes. About 80 s of that is building the demo workspace once.
- Test files:
  - `test_ingest`, `test_query_engine`, `test_datasets_api`, `test_dashboards`
  - `test_assistant` (NL plus a mocked OpenAI-compatible LLM)
  - `test_claude` (routing, escalation, safety and fallback, with a fake Anthropic client; it never calls the real API)
  - `test_identity` (Phase 3: Google sign-in with a simulated Google - every refusal, forged tokens, single-use state, header spoofing, session expiry, sign-out, cross-site writes, bootstrap admins, switching users off, company-only members, API tokens, unsafe start-up configs; access rules on dashboards, domains and datasets for people and the assistant; lineage; audit)
- `test_domain_agents` (Phase 7: alerts from CSV datasets shaped like the warehouse views; the switch; admins only; summary and filters; a decision records who and when and becomes a decision memory, is refused on a resolved or unknown alert, works with memory off; new alerts and failed runs announced once; the briefing hook only when `BRIEFING_EVERY_DAYS` is set; briefing facts in code and deterministic, worded by Sonnet and reused for the same facts, a new decision changes them, an invented number rewritten once then the facts shown, the model off, the job; the Stock assistant explains with get_alerts and sees only its domain; Operations sees only POs; viewers keep the old path; get_alerts only on global and domain scopes and for admins)
- `test_global_assistant` (Phase 6: the Ask page on the global assistant with the index and cross-dashboard tile reads, streaming, older threads continue and are listed, viewers and the semantic engine keep the old path, "create a dashboard" still works, the switch, memories from every scope with their origin, "remember" is global, a hidden dashboard leaves no data, memory, issue or mention, the index within budget for 10 and 30 dashboards, issues and worth-a-look on the cards, the eval runner's two-number check)
- `test_data_issues` (Phase 5: the real ISSUE_LOG.md parses completely and its mapping names only real dashboards; import adds once, marks solved, keeps edits; only admins change the register; tile notes through composite metrics, the dashboard strip, parked/solved hidden; solving sends memories to review; the assistant's pack and tool; issue text as data; "worth a look" on a 3-year series (last year, unusual month, record, gap, data age), cached until the data changes, never computed in a request, hidden data filtered, queued after a sync; the switch; notifications per person; the eval runner's issue-code check)
- `test_memory` (Phase 4: explicit saves decided from the user's words, the model can't save silently, limits and duplicates, memories in the prompt and citations, scopes, ranking budget, search, isolation between people in prompts/API/page, shared decisions, team facts and admin approval, restricted dashboards, learning after 30 quiet minutes, accept/edit/reject, rejected suggestions never repeated, staleness and keep, profile rewrites and user edits, the job queue (retries, crashed worker, claimed once), the switch, the story runner)
- `test_agent_loop` (Phase 2: multi-step answers, parallel calls, tool errors, escalation, step/time limits, refusal and outage, the number check and rewrite, every tool, workspace isolation, streaming, thread summaries)
- `test_dashboard_chat` (Phase 1: access, the dashboard pack, screen-state validation, recomputed screen numbers, filter inheritance, threads, feedback, the eval runner on dashboards)
- `test_assistant_groundwork` (dashboard keys and the 0002 migration round trip, conversation scopes, the AI usage ledger and spend caps, feature flags, the test harness itself, the eval runner)
- **Scripted Claude for tests:** `tests/fakes.py` (`FakeMessages`, `turn`, `say`, `tool_call`) and the `fake_claude` fixture. It also enforces the rules: Haiku/Sonnet only, no `temperature`/`fallbacks`, no forced `tool_choice`, and the tool-loop contract (every `tool_use` answered by a `tool_result` in one user message). Use it for every new test that touches Claude.
- **Evaluation sets:** `backend/evals/` (`python -m evals run <set>` from `backend/`, against the running app; needs `pyyaml` from `requirements-dev.txt`). Expected numbers come from SQL or a QuerySpec run at eval time. Without `--live` the free offline engine answers; `--live` uses Claude and refuses to start unless `EVAL_LIVE_OK=1` (owner's OK first). Sets live in `evals/sets/`: `domain.yaml` (Phase 7: 20 questions to the Stock, Operations and Executive assistants: alert counts, the worst cases, what each rule checks and its threshold, a dashboard tile behind an alert, and refusing to decide; expected numbers by SQL on `agent_alerts` at run time; case field `domain`; needs `--live`; **live 2026-11-10 (owner's OK): 19/20 at first, Rs 2.05; the miss was a right answer the checker couldn't read ("Eighteen products": Haiku starts a sentence with a word, not a digit). `agent/numbers.py` now reads spelled-out counts, which also puts them under the assistant's own number check; recheck 1/1, Rs 0.29. No invented numbers**), `global.yaml` (Phase 6, last live run 2026-11-10: 25/25 after one prompt fix, about Rs 19 in all; 25 Ask-page questions: comparisons across dashboards with both numbers checked (`also_expect`), finding the right dashboard (`expect.dashboard`), summaries, data issues, and what exists for the user; `context_dashboards` names what an answer may quote; needs `--live`), `issues.yaml` (Phase 5: 20 questions on workspace 34, 12 on tiles a known issue touches (the answer must name it) and 8 on tiles none touches (it must not pin an unrelated one); `check_issue_codes` fails any cited code not recorded for that dashboard; offline dry run 2026-11-07 resolved every tile and expected number; **live 2026-11-07 (owner's OK): 18/20, every number right (18/18), Rs 6.95**; both failures were the checker: an answer explained D-039's substance ("1,441 units not received after 60 days") without the code, now accepted, and "99" from an issue's own title ("99-100% discount") counted as invented, now the register's texts count as a source; recheck 2/2, Rs 0.16. One answer went to Sonnet and cost Rs 4.58 of the 6.95 (a cache write on the large prompt)), `memory.yaml` (Phase 4: 7 stories over several conversations: save and apply "compare with last year", a decision recalled on another dashboard, a dashboard's memory staying there, retired and rejected memories not used, "what did I decide", a team fact; needs `--live`; the runner deletes what each story creates; **live 2026-11-07 (owner's OK): 5/7 at first, Rs 5.85; both failures were the checker's word lists ("cash-on-delivery" for COD; a recalled decision backed with "only 6,475 of 78,215 units sold" instead of the words "unsold"/"sell-through"), widened; recheck 2/2, Rs 0.22. No invented numbers**), `sample.yaml`, `dashboard_deep.yaml` (50 harder questions, 5 per dashboard, for Phase 2; **live 2026-11-07: 50/50 after fixes, every number right, Rs 12.25, median 15 s**; the first run was 49/50 numbers right, with 12 checker false positives because the checker didn't see the screen, now fixed by `screen_numbers`) and `dashboard_basic.yaml` (80 questions, 8 per dashboard; expected values from the dashboard's own widgets with the same filters). The runner checks the number, named labels, required mentions and that every number in an answer comes from its data, and deletes the threads it creates. The offline engine scored 15/80 on 2026-11-07 (it can't use dashboard context): that run only proves the wiring. **Live run with Claude (2026-11-07, owner's OK): 78/80 passed, 69/69 numbers correct, Rs 30.81, median 15 s per answer**; the 2 failures were checker false positives (year-months, numbers inside band names), fixed. A 12-question recheck after the formatting fix passed 12/12 (Rs 11.94, mostly cache rewrites after the rebuild).
  - `test_safety`, `test_security_audit`, `test_hardening`, `test_analytics_units`
  - the end-to-end ground-truth test in `test_assistant`
- In tests, import shared helpers with `from conftest import api, build_mini`; relative imports don't work.
- Frontend: `cd frontend; npm run typecheck; npm run build`.
- **Live AI checks cost real money.** Get the user's OK first, and keep them short.

## Data issue register (Phase 5)
- First import (done 2026-11-07, 37 issues): `python scripts/import_issue_log.py` from `analytics/` (`--dry-run` prints what it would send). It maps each issue to the dashboards and metrics it touches (`AREA_AFFECTS` by area, `ISSUE_AFFECTS` per code). Re-run it after the log changes: it adds new codes and marks solved ones, never overwriting edits made on the Data issues page, which is the source of truth from now on. Needs `ELLEMENTRY_API_TOKEN` once company sign-in is on.

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
- **Agent runner (Phase 7, schema 2.16):** `python dw.py agents run all` after every successful `transform run` (then the app's hourly sync picks the alerts up). Exit 3 = not run (latest build failed, ERROR check, missing setting); 4 = a run failed and wrote nothing. Thresholds are rows of `meta.pipeline_setting` (`stock.low_cover_days`, `ops.po_overdue_critical_days`; switches `agent.stock.enabled`, `agent.operations.enabled`); a rule is switched off with `UPDATE insight.alert_rule SET is_active = false` (its open alerts are resolved on the next run). Change them only through `dw.py psql` after `dw.py backup`.
- Agent tests: `DW_DATABASE=dw_agents_test python dw.py pytest -q tests/test_agents.py` (14 passed in 32 s). `dw_agents_test` is a restore of a warehouse backup with migration 240 (any loaded, built copy works); rebuild it with `pg_restore` from the latest `backups/ellementry_dw_*.dump` into a fresh database.
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
