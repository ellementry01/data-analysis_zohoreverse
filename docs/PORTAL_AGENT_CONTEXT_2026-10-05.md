# Agent Context: Ellementry Warehouse Intelligence Hub

Last updated: 5 October 2026

This file is the durable handoff for coding agents working in this repository. It describes the current project, the canonical warehouse, the database migration, the decisions made, the current verification boundary, and the safest next steps. Read this before changing schemas, imports, permissions, or dashboard behavior.

## Current State

- The final business schema is the package under `ellementry data schema/ellementry_dw/`.
- The active local database is PostgreSQL 18 database `ellementry_dw`.
- The old app-only database named `ellementry` was checked and dropped after cutover. It contained zero imports, raw source rows, products, or invoice facts; it contained the one admin account that was copied to the portal schema in `ellementry_dw`.
- Portal login is the existing `rajat` admin account. The account password hash was copied, not reset. Never ask the user to put its password in chat.
- The local PostgreSQL service is Windows service `postgresql-x64-18`, listening on port 5432.
- The app is started with `scripts/start_local.ps1` and serves the rebuilt frontend/API at `http://127.0.0.1:8000`.
- The active runtime health endpoint most recently returned `ready` with warehouse `ellementry_dw`; the root page returned HTTP 200.
- No real company exports, customer transaction rows, or other business facts have been loaded. The initial successful transform is an empty-data build over schema/reference seeds.
- The earlier screenshot exposed database credentials. They were rotated and `.env` database URLs were updated. Never display or copy secrets from `.env`; `.env` is local-only and must not be committed.

## Product And Repository Shape

The project is a React/TypeScript + Vite UI, a FastAPI portal API, and a PostgreSQL warehouse. It is not a direct-upload BI backend and does not use free-form model-generated SQL.

Current ownership:

- `ellementry data schema/ellementry_dw/`: authoritative source contracts, warehouse DDL, reviewed reference seeds, raw loader, transforms, quality gates, mart definitions, and warehouse tests.
- `backend/app/`: authentication and session security, portal API, fixed warehouse-mart adapter, database connection pools, and setup CLI.
- `backend/tests/test_warehouse.py`: authenticated API tests against a disposable portal-enabled warehouse database.
- `frontend/src/main.tsx`: warehouse-aligned React navigation, report filters/tables/export, readiness overview, and sign-in.
- `frontend/src/style.css`: existing Ellementry design styles plus report/filter/table/dialog styles.
- `migrations/003_warehouse_portal.sql`: app-owned portal tables and safe portal views only. Warehouse tables are not defined here.
- `scripts/`: credential generation, native Windows setup/start scripts, and backup/restore helpers.
- `docs/`: architecture, actual validation results, and release gates.
- `README.md`: native Windows quick setup and current warehouse workflow.

Retired code has been removed: the old app importer, profile registry, stock/operations metric SQL, LangGraph agent module, direct-core configuration endpoints, legacy app tests, old app foundation/application migrations, and obsolete inventory unpivot script. Do not restore those abstractions unless there is a newly approved requirement and a design compatible with the canonical warehouse.

## Canonical Database Architecture

The warehouse has one-way data flow:

```text
registered source files
  -> loader contracts
  -> raw source-specific tables
  -> stg typed/cleaned rows
  -> core dimensions/facts/ledger
  -> DQ gates and process coverage
  -> mart reporting views
  -> portal read-only API/UI
```

The schema layers are:

- `meta`: registered sources, load batches, pipeline settings, transform runs, DQ results, business processes/rules/gaps/notes, column lineage/rules, coverage, and schema history.
- `ref`: reviewed canonical product/location/channel/partner/code mappings and source aliases.
- `raw`: source values landed according to source-specific contracts. Treat this as restricted; raw workbooks may contain PII or commercially sensitive data.
- `stg`: typed and normalized rows derived from raw. It is not a second business-definition layer.
- `core`: conformed dimensions and facts, product history, transfers, receipts, returns, sell-out, stock snapshots and the signed stock movement ledger.
- `mart`: approved business definitions and reporting views. This is the only warehouse schema the portal metrics role may read.
- `insight`: warehouse model runs, forecasts, recommendations, human decisions, and alerts as represented by the supplied schema. The current web app does not run or expose AI agents over this schema.
- `app`: portal-only users, sessions, audit, rate buckets, schema version, and portal views. It does not own products, transactions, imports, or canonical business rules.

The warehouse README is the authority for individual table grains, business rules, source contracts, and file-processing semantics. Consult `ellementry data schema/ellementry_dw/README.md` and the corresponding SQL/contract before making semantic claims from a column name.

## Warehouse Package Workflow

The warehouse package targets PostgreSQL 16 and is portable to a cloud warehouse later. The project also ran its schema build and empty transform successfully against the local PostgreSQL 18 installation.

Fresh database build order is defined by `ellementry data schema/ellementry_dw/build_db.sh`; do not reorder it casually. It applies the numbered `sql/*.sql` files, including the core v2 transition, staging infrastructure, receipt grain, and generated column definitions. The build script is for a fresh database. Once a business database has data, use a new numbered migration; do not edit an already-applied migration or rerun the fresh build against populated data.

Reviewed CSVs in `seeds/` feed `python -m loader.seeds <database>`:

- Register data such as business rules/processes/gaps/source notes/partner types is upserted and may not silently disappear. Retire, close, or supersede it instead.
- Mapping tables are replaced from the reviewed seed files as described by `loader/seeds.py`.
- Mapping changes must be reviewed and checked with the seed tests and business owners.

The source loader is `python -m loader`, from the warehouse directory. Use:

- `python -m loader sources` to see registered source contracts and whether `--as-of` is required.
- `python -m loader load <SOURCE> <FILE> --dry-run` to validate without a database write.
- `python -m loader load <SOURCE> <FILE>` to commit a valid transactional file.
- `python -m loader load <SNAPSHOT_SOURCE> <FILE> --as-of YYYY-MM-DD` for a point-in-time/state/master file; the date must be confirmed from the source.
- `python -m loader batches` to inspect load attempts.

Loader contracts enforce exact expected headers/grain, explicit dates, row and workbook checks, duplicate-file protection, and all-or-nothing raw loads. Raw data is not cleaned destructively on ingress. A changed ERP export requires an intentional contract update, raw DDL migration, tests, and review.

`python -m transform run ellementry_dw` performs the raw-to-mart build in a single transaction. It writes DQ outcomes and fails/rolls back if any ERROR-level quality gate fails; the last successful build remains. WARN outcomes remain visible. Do not skip the transform and assume newly loaded raw rows are already in marts.

## Portal Database And Security Boundary

`migrations/003_warehouse_portal.sql` creates the portal schema and these marts-facing views:

- `mart.v_portal_products`
- `mart.v_portal_locations`
- `mart.v_portal_channels`
- `mart.v_portal_sources`
- `mart.v_portal_load_batches`
- `mart.v_portal_transform_runs`
- `mart.v_portal_business_rules`
- `mart.v_portal_data_gaps`
- `mart.v_portal_source_notes`

Portal schema tables are `app.schema_version`, `app.user_account`, `app.session`, `app.audit`, and `app.rate_bucket`.

There are two runtime connections, even though they point to the same PostgreSQL database:

- `DATABASE_URL` uses `ellementry_app`; CLI grants let it use the `app` schema for portal account/session/audit behavior. The web app does not use the database superuser.
- `METRICS_DATABASE_URL` uses `ellementry_metrics`; it has `USAGE` and `SELECT` on `mart`, and role default transactions are read-only. It must not gain `raw`, `stg`, `core`, `meta`, or `app` access.
- `ADMIN_DATABASE_URL` is for setup/migrations only. The application process must not receive it.

Authentication uses Argon2 password hashes, random hashed session tokens in the DB, an HttpOnly/SameSite cookie, CSRF checks on mutations, login rate limiting, allowlisted Host/origin middleware, and app audit entries. Login passwords must be at least 16 characters at account creation. Sessions are eight hours.

`backend/app/db.py` maintains separate app and metrics connection pools and makes metrics transactions read-only. `backend/app/security.py` implements auth and role checks. Keep SQL view names, order fields, and accepted filters code-owned; use bound parameters for values.

## Backend API Surface

The app entry point is `backend/app/main.py`, a small re-export of `backend/app/warehouse_api.py`. Run with `uvicorn app.main:app` from `backend/`.

Unauthenticated health/API endpoints:

- `GET /api/health/live`
- `GET /api/health/ready`
- `POST /api/auth/login`

Authenticated portal endpoints:

- `GET /api/auth/me`
- `POST /api/auth/logout`
- `GET /api/catalog`
- `GET /api/readiness`
- `GET /api/reports/{name}` with only report-specific allowlisted query filters; maximum 500 rows
- `GET /api/audit` for admins

There are no current endpoints for file upload, mapping creation, direct core writes, shipment-only metrics, agent execution, finding review, or model calls. File ingestion and business mapping administration use the warehouse package's CLI and reviewed seeds, not the app UI.

`backend/app/warehouse.py` defines 16 report IDs, fixed mart views, ordering columns, and supported filters:

| Report ID | Warehouse view |
|---|---|
| `sales` | `mart.v_net_sales_daily` |
| `inventory` | `mart.v_stock_position_latest` |
| `days_of_cover` | `mart.v_days_of_cover` |
| `returns` | `mart.v_returns_daily` |
| `transfers` | `mart.v_transfer_in_transit` |
| `purchase_orders` | `mart.v_open_purchase_orders` |
| `supplier_lead_time` | `mart.v_supplier_lead_time` |
| `partner_review` | `mart.v_partner_review` |
| `data_quality` | `mart.v_data_quality_latest` |
| `coverage` | `mart.v_data_coverage` |
| `source_batches` | `mart.v_portal_load_batches` |
| `transform_runs` | `mart.v_portal_transform_runs` |
| `sources` | `mart.v_portal_sources` |
| `business_rules` | `mart.v_portal_business_rules` |
| `data_gaps` | `mart.v_portal_data_gaps` |
| `source_notes` | `mart.v_portal_source_notes` |

The table above lists all 16 entries in `REPORTS`.

All reports sort by code-owned columns and return no more than 500 rows. Filters are values in prepared SQL; unknown report/filter names return 404/422. Date filters must be ISO dates. CSV export escapes spreadsheet formula-leading characters. There is no pagination yet; 500 rows is a display/export ceiling, not an aggregate-total contract.

Readiness summary counts are aggregated over safe views rather than derived from the bounded report lists. The overview shows registered/active sources, load counts, latest transform, DQ fail count, and process coverage. Empty business facts are expected in the fresh local database.

## Frontend Behavior

The warehouse UI is in `frontend/src/main.tsx` and currently has navigation for:

- Warehouse overview
- Sales
- Inventory, including days of cover
- Returns
- Transfers
- Purchasing, including supplier lead time
- Data pipeline: batches, transforms, registered sources, DQ, and coverage
- Business context: partner review, rules, gaps, and source notes

It has sign-in, readiness status, warehouse period, report filters, table record inspection, CSV export, and no-data states. It does not claim to ingest data or perform write actions against warehouse facts. `frontend/src/style.css` retains the existing Ellementry visual language and adds responsive report controls. Vite proxies `/api` to `127.0.0.1:8000` for development; production/local launcher serves `frontend/dist` from FastAPI.

## Migration: What Changed And Why

The migration decision was explicitly to make the user's supplied schema final and canonical, not to combine two parallel warehouse designs.

1. **Conflict discovered:** the old app schema and supplied warehouse shared schema names (`meta`, `raw`, `core`, `mart`) but differed in batch tables, primary-key names, fact grain, staging, facts, and marts. For example, the app expected `meta.import_batch`, `core.dim_product.product_id`, and app-specific compatibility views; the warehouse uses `meta.load_batch`, `core.dim_product.product_key`, its own contracts, and its own mart views. Running the warehouse v2 DDL in the old app DB could collide and its core migration drops/replaces v1 tables.
2. **Canonical contract chosen:** the supplied `ellementry_dw` folder owns all business data, raw loading, transforms, mappings, quality, and marts. The old app-specific importer/metrics/agent model was not adapted as another facts pipeline.
3. **Compatibility strategy:** add one portal-only migration and safe `mart.v_portal_*` views. Keep auth/session/audit in `app`; point all dashboard reads at a code-owned list of warehouse marts with a separate read-only metrics role.
4. **Isolated compatibility test:** build a separate fresh `ellementry_dw` database, not over the old app DB. Apply the warehouse SQL files in their documented order, load the reviewed seeds, run the transactional SQL schema tests, and run an empty-data transform. PostgreSQL 18 completed these checks; target/test SQL has a PostgreSQL 16 baseline.
5. **Portal integration:** apply `003_warehouse_portal.sql`; run CLI role grants. All 16 report queries and each declared filter were executed against actual empty warehouse marts.
6. **Account cutover:** copy the existing `rajat` password hash and available app audit rows into the new portal schema, preserving the user's login instead of requesting a new admin password. Sequence identities were synchronized.
7. **Credential hygiene:** DB credentials visible in an earlier screenshot were rotated; `.env` URLs were changed to the warehouse DB and URL-encoded. No secret values should be repeated in docs, output, or chat.
8. **Frontend cutover:** replace the old screens for direct data import, app-defined business rules, agent runs/findings, and mismatched stock/shipment metrics with pages over the supplied warehouse marts and process metadata.
9. **Legacy cleanup:** remove the old app schema migration files and app-specific importer/metric/agent modules/tests and unpivot helper that depended on the removed importer. Check old database counts; zero imported files, raw rows, products, and invoice facts. Since only the migrated admin remained, drop the old `ellementry` database. The new `ellementry_dw` database remained active.
10. **Setup/docs:** update README and architecture/release/validation docs, `.env.example`, backend dependency lock, Windows setup/start scripts, and optional Docker build/Compose to use `ellementry_dw` and the warehouse package.

The original schema folder was not removed or replaced; it remains the source of truth. No customer/business data was copied. The old app was not merged into warehouse facts. The only app record migration was the login/audit subset into the portal-owned schema.

## Current Database Setup And Commands

Current native Windows setup uses `.env` from the project root:

- `POSTGRES_PASSWORD`: local PostgreSQL `postgres` account. Avoid printing it; this value was reset/rotated after initial setup.
- `APP_DB_PASSWORD`: app portal role password.
- `METRICS_DB_PASSWORD`: read-only mart role password.
- `ADMIN_DATABASE_URL`: migration URL.
- `DATABASE_URL`: app role URL.
- `METRICS_DATABASE_URL`: read-only role URL.
- `APP_ORIGIN`, `ALLOWED_HOSTS`, `COOKIE_SECURE`: web boundary config.

Do not commit `.env`. `.env.example` is the safe template; `scripts/configure.py` creates a local `.env` and intentionally refuses to overwrite one. If PostgreSQL was installed first, `POSTGRES_PASSWORD` must match the installed local postgres user's password before setup.

Fresh setup:

```powershell
python scripts/configure.py
python -m pip install -r backend/requirements.txt
python -m pip install -r "ellementry data schema/ellementry_dw/requirements.txt"
.\scripts\setup_warehouse.ps1
```

`setup_warehouse.ps1` refuses to overwrite any database of the selected name. It creates the database, applies the warehouse SQL in order, loads seeds, runs `tests/test_schema.sql`, runs an empty initial transform, persists the encoded admin URL in `.env`, applies the portal migration, and grants roles. It does not create the portal admin; create that afterward:

```powershell
Push-Location backend
Get-Content ..\.env | ForEach-Object { if ($_ -match '^([^#=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1],$matches[2],'Process') } }
python -m app.cli create-user --username rajat --role admin
Pop-Location
```

Password is prompted twice directly in terminal, minimum 16 characters. Do not send it to an agent.

Build and launch:

```powershell
npm ci --prefix frontend
npm run build --prefix frontend
.\scripts\start_local.ps1
```

The local launcher loads `.env`, changes to `backend/`, and starts Uvicorn on loopback `127.0.0.1:8000`. Ctrl+C stops the web app; the PostgreSQL Windows service continues running. The API docs are at `/api/docs`.

Optional Docker Compose is aligned to PostgreSQL 16 and the same warehouse build. Its config parsed, but Docker was unavailable earlier and containers/image were not executed in this migration session. Do not claim Compose runtime validation.

## Verification Evidence And Limitations

Verified in this migration session:

- Ordered warehouse schema SQL build and reviewed seed load on PostgreSQL 18.
- Warehouse rollback-only schema SQL acceptance script exited successfully.
- Empty-data transform succeeded and produced the documented mart views.
- Warehouse loader/seed pytest: 36 passed, 19 skipped; skipped cases require optional sample/database fixtures.
- Portal API pytest against real local DB and roles: 4 passed (readiness/catalog, every report, every declared filter, rejected filters/role boundary).
- All report queries, catalog, readiness, and report filter mappings ran against the generated mart columns.
- Frontend `npm run build`: TypeScript and Vite passed.
- PowerShell setup scripts parsed; `docker compose config --quiet` passed.
- Browser smoke: temporary reader signed in; overview and sales pages rendered; 1440px and 390px viewport measurements showed document width below viewport width. The temporary account/session/audit rows were removed.
- Final runtime `/api/health/ready` returned `ready` for `ellementry_dw`; root page returned HTTP 200; PostgreSQL confirmed `ellementry` absent and `ellementry_dw` present.

Not verified:

- No real source exports or samples were loaded/reconciled; business mappings and source ownership need approval.
- Loader sample-file tests and DB-specific loader/transform suites requiring fixture files were not run.
- Every report was exercised at the API layer, but not manually reviewed in a browser with realistic loaded data.
- No browser pixel automation/artifact rendering or broad accessibility audit was completed.
- PostgreSQL 16 runtime, Docker build/start, concurrent workloads, TLS/shared deployment, backup restore, performance, and retention have not been verified.
- Fresh setup script was syntax-parsed but not run again against a second new database after the migration. Actual DB build steps it encodes were run manually and succeeded.
- Empty transform verifies SQL/schema compatibility, not business semantics or reconciled production totals.

See `docs/VALIDATION.md` for the shorter checked summary and `docs/RELEASE_CHECKLIST.md` for deployment gates.

## Guidance For Future Agents

1. Treat `ellementry data schema/ellementry_dw` as final. Do not reintroduce parallel app-owned facts/imports.
2. Before changing a business definition, inspect the relevant source contract, seed rows, core transformation SQL, mart SQL, and tests together. Keep the definition in the warehouse mart/SQL, not duplicated in TypeScript.
3. Never run `build_db.sh` or `setup_warehouse.ps1` against a populated database. Fresh setup refuses existing DBs; warehouse schema evolution must use numbered migrations after backup/staging.
4. Keep the metrics role `mart`-only and read-only. Keep web DB role limited to portal tables. Do not grant dashboards raw access.
5. Keep source load, reviewed seeds, transform, and API reporting as separate actions. A successful raw file load is not a successful transform; inspect DQ/coverage and last successful run.
6. Do not turn missing data into zero, infer dates/classifications, or claim a complete metric from a capped 500-row report.
7. Do not show or log passwords, full URLs, raw PII, or workbook payloads. The `.env` already contains rotated private values.
8. Add/adjust tests around actual warehouse views and role privileges when changing the report adapter. Run `python -m pytest -q tests/test_warehouse.py` with a disposable DB and `RUN_DB_TESTS=1`.
9. Document the exact PostgreSQL version and whether a check was run on PostgreSQL, a test client, or Docker. Do not call the deployment production-validated.
10. Be aware that the current server is a long-running local process. If changing Python API code, restart it with `scripts/start_local.ps1` to load changes. It is currently intended for local loopback use only.
