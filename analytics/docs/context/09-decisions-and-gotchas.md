# 09 — Decisions, gotchas, known issues and next steps

## Decision log
| Decision | Why |
|---|---|
| Old working name removed everywhere (2026-10-26): compose project `ellementry`, image `ellementry-analytics`, schema `ellementry_meta`, DB `ellementry_analytics`, `ELLEMENTRY_*` env vars (`ELLEMENTRY_CONN_*`, `ELLEMENTRY_SECRET_KEY`), app folder `analytics/`, container user `ellementry`. Done with backups first, then the schema, database and role renamed in place and the Docker volumes copied, so no data was lost | The user asked for the old name to be removed from everywhere |
| Deleted only the **demo workspace in the app**; kept the generator, `/api/demo` and the button | This was the user's choice, from an explicit question. Tests depend on the demo |
| Claude routes **Haiku 5.5 (simple) / Sonnet 5.5 (complex)**; never Opus or Fable; no server-side fallbacks; model allow-list checked at startup | The user's explicit instruction |
| Routing is deterministic regex/heuristics in code, not an LLM classifier | It's free, instant and testable, and the routing reasons are visible in the UI |
| Claude returns a **QuerySpec first**, with SQL only as a fallback | Governed metrics and business rules then apply automatically, and the arithmetic stays in the engine |
| Narrative arithmetic is done in code (`_facts`), never by the model | In the live check the model miscounted (75 vs 76) |
| An explicit counting rule is in the prompt | Sonnet once counted distinct names (7) instead of rows (12) |
| Connector passwords are referenced by env var **name** (`ELLEMENTRY_CONN_*` only) | Secrets never pass through the API, the database or chat, and the prefix stops a connector from reading arbitrary server secrets |
| Connector imports keep the source column types | Empty views would otherwise import as all-text |
| Ports are bound to 127.0.0.1; identity-only auth | It's a local-first tool; real auth is a prerequisite for sharing (R1) |
| The warehouse lives in `ellementry-analytics/warehouse` (moved 2026-10-22, history kept) and the exports in `ellementry-analytics/exports` (outside git) | One place for the whole product; the exports hold customer data |
| Platform workbooks are normalised into the contract layout rather than loosening the contracts | Contracts stay strict; every change the normaliser makes is logged, personal data and payout columns are never written |
| Mappings added from data evidence are `is_confirmed = false` with the evidence in the note | Same rule as the original reviewed seeds: nothing is assumed confirmed until the business says so |
| PO Document Remark is stored but decides nothing until BR-031 is confirmed (`po_document_remark_confirmed`) | A PROPOSED rule is never treated as confirmed (PRD convention) |
| Executive dashboards are built by a script (`scripts/build_executive_dashboards.py`), not by hand | Rebuildable after any data or metric change, and every widget is checked for data on each build |
| KPI cards and tables colour a change by the metric's `higher_is_better` (the query engine now passes it on each measure column) | A rising return or RTO rate was shown green |
| Warehouse 2.4 fixes data-side problems in the warehouse, not in app calculated columns (courier groups, transit status, MRP status, tracked channels) | One definition for dashboards, Ask AI and any later report; the app only filters on the new columns |
| RTO rate and delivery time are measured only on channels that report them (`is_rto_tracked`, `is_delivery_tracked`, derived from the data each build) | Marketplace RTO never reaches the WMS and Nykaa/FNP/Flipkart send no delivery dates: an all-channel rate showed 4.3% instead of the website's 7.9% |
| Items with no MRP in any source are left out of stock value and counted on their own tile, never valued at 0 silently | 14,474 trading units (mostly discontinued) have no MRP anywhere |
| The ERP item master only fills gaps; it never overrides the Final Master, stock report or invoices | It is the least curated source, but it had a category for almost every product that lacked one |
| Raw exports are kept twice: canonical copies listed in `MANIFEST.tsv`, and every distinct original as received in `exports/_originals/` (`ORIGINALS.tsv` holds their sha256) | The user asked for the original files to be kept; renamed canonical copies alone lose the received names and the superseded re-exports |
| The project moved off the scratch workspace to the Desktop | The scratch path was a redirected AppData folder that broke mkdir, Alembic, npm/esbuild and Vite |

## Gotchas
- **`.env` changes need `docker compose up -d --force-recreate app`.** A plain `up -d` or `restart` may not reload them. This has bitten twice: once for the ELLEMENTRY_CONN password and once for the Anthropic key.
- After changing code, rebuild with `docker compose up -d --build`. The UI is baked into the image.
- `pip` on PATH belongs to another interpreter; use `python -m pip`.
- Shell heredocs once mangled `\b` into backspace characters. Use the Edit/Write tools for code changes.
- Importing `claude` from `config` causes a circular import. That is why `check_model` lives in `config.py`.
- Tests import with `from conftest import …`.
- Prompt caches are per model, so the first Sonnet question pays its own cache write.
- The README and QA_REPORT test counts (328 and 363) are stale; the current count is **404**.
- The README "Quick start" still mentions "Load demo workspace". The button still works.

- **After a hard shutdown**, the app's PostgreSQL container runs a long crash-recovery sync (about 10 minutes). The app can exit first; once the db is healthy, run `docker compose restart app`.
- **Docker Desktop doesn't start by itself after a reboot.** Launch `%LOCALAPPDATA%/Programs/DockerDesktop/Docker Desktop.exe`.
- **Warehouse commands go through `python dw.py …`** from `warehouse/`, so the admin login never appears in a command line. Tests: `DW_DATABASE=<disposable db> python dw.py pytest`; the script refuses `ellementry_dw`.
- **Windows Python writes CRLF line endings** unless told otherwise. The generators now write LF. Check `git diff --stat` for whole-file diffs.
- **Relative dates in the app are measured from today, but the warehouse period ends on 15 Sep 2026.** "Last 30 days" is empty until the as-of anchor (dashboard plan, item A2) is built or the period is moved.

## Known functional limitations
- "By warehouse" on a sales register can group by the warehouse code instead of the name. This is a demo-data quirk.
- "This month vs previous period" compares with the same number of days immediately before it, not the same days of the previous month.
- The offline engine understands only semantic-layer vocabulary. Open-ended phrasing needs Claude.
- Scheduled refresh applies to connectors only; files are refreshed by Replace or Append.
- Excel, PNG and PDF exports run client-side (PDF via print).

## Sensible next steps (none in progress; ask the user before starting)
1. Load real facts into `ellementry_dw` (in the warehouse project). Then re-verify the sales, returns and stock answers against direct SQL.
2. Add a stock-history mart view, so trend questions about stock become answerable.
3. Build the first dashboards for workspace 34, and add glossary terms for Ellementry vocabulary such as channel and location names.
4. Configure `READONLY_DATABASE_URL` with `scripts/create_readonly_role.sql` (R5).
5. Add real authentication (OIDC or an SSO proxy) before any shared or network deployment (R1).
6. Migrate to Tailwind 4 to clear the build-time npm audit findings (R2).
7. Refresh the test counts in the README and QA_REPORT.
