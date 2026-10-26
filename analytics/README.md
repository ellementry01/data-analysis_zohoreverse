# Ellementry Analytics

A local-first, AI-assisted business analytics platform. Import messy Excel/CSV files or SQL tables into
PostgreSQL, clean and relate them, define governed business metrics, build interactive dashboards, and ask
questions in plain English. Every answer is computed from your own database and shows the SQL behind it.

Ellementry's product behaviour was informed by a study of **Zoho Analytics'** public website and help center. The
study was done with the REA reverse-engineering tool; see [`../research`](../research). The study used only
public pages; there was no login, no proprietary code and no internal APIs. All code here is independent.

---

## 1. Quick start (Windows)

Prerequisites: **Python 3.11+**, **Node.js 18+**, **PostgreSQL 14+** (running locally).

```powershell
# one-time: creates databases ellementry_analytics (+ _test), a venv, installs deps, migrates, builds the UI
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -DbUser postgres

# run (API + UI on http://localhost:8000)
start.bat                      # or: powershell -File scripts\start.ps1
powershell -File scripts\start.ps1 -Dev   # dev mode: Vite on :5173 with hot reload, API on :8000
```

The database password is never written into code. Provide it in one of these ways:

- `%APPDATA%\postgresql\pgpass.conf` (recommended)
- the `PGPASSWORD` environment variable
- a password inside `DATABASE_URL` in `backend\.env`, a git-ignored file

Then open the app and click **Load demo workspace**. It imports 11 deliberately messy spreadsheets, cleans
them, relates them, defines metrics and builds a dashboard, all through the public API, in about a minute.

### Docker (optional)
```powershell
copy .env.docker.example .env      # then set POSTGRES_PASSWORD to a long random string
docker compose up -d --build       # PostgreSQL 16 + app  ->  http://localhost:8000
docker compose logs -f app         # follow logs;  docker compose down  (data persists in volumes)
```
The containers are hardened:

- a multi-stage image running as a non-root `ellementry` user with a health check
- a read-only root filesystem, all Linux capabilities dropped, `no-new-privileges`, and memory/PID limits
- ports published on `127.0.0.1` only
- data in the `pgdata` and `uploads` named volumes (removing them with `docker compose down -v` deletes everything)

To use Ollama running on the host, set `LLM_BASE_URL=http://host.docker.internal:11434/v1`.

### Connecting another PostgreSQL database (e.g. a data warehouse on this PC)
1. **Use a read-only login.** Ideally one that can only `SELECT` from the reporting schema.
2. **Put its password in Ellementry's `.env`.** Use the main `.env` for Docker, or `backend\.env` when running locally. The variable must be named `ELLEMENTRY_CONN_<NAME>`, e.g. `ELLEMENTRY_CONN_ERP_PASSWORD=...`. Only `ELLEMENTRY_CONN_*` names are accepted, so a connector can't be used to read other server secrets.
3. **Recreate the container.** Run `docker compose up -d`; a plain `restart` doesn't reload `.env`.
4. **Add the connection.** In **Import data → Databases**, enter host, database, user and schema, and type the variable *name* into "password environment variable". From Docker, the host for a database on this PC is `host.docker.internal`.
5. **Import the tables and views.** Pick them, then set an auto-sync interval.

Column types come from the source schema, so empty tables still get the right date and number types.

### Manual setup
```powershell
cd backend; python -m venv .venv; .venv\Scripts\pip install -r requirements.txt
copy .env.example .env     # set DATABASE_URL
.venv\Scripts\python -m uvicorn app.main:app --port 8000      # migrations run automatically on start
cd ..\frontend; npm install; npm run dev                       # http://localhost:5173 (proxies /api)
cd ..\sample_data; python generate.py                         # regenerate demo data (deterministic)
```

---

## 2. What you can do

| Area | Functionality (all persisted in PostgreSQL, survives restarts) |
|---|---|
| **Workspaces** | Create, rename and delete. Members with **admin / editor / viewer** roles, enforced by the API. |
| **File import** | `.xlsx/.xls/.csv/.tsv`, several files at once, sheet picker, **automatic header-row detection** (skips title rows) with manual override, preview of 50 rows. Type inference handles ₹/Rs./commas/(negatives)/%, mixed `YYYY-MM-DD` + `dd/mm/yyyy`, booleans, and leading-zero IDs. You can correct types, rename or exclude columns. Before import it warns about empty values, type conflicts, duplicates, inconsistent spellings and missing headers. Modes: **new / append / replace**. |
| **Database connectors** | PostgreSQL, plus any SQLAlchemy-supported database through a URL (the registry is extensible). Connections open read-only. You can test, browse tables, preview and import, sync on demand or on a **schedule** (in-process scheduler). Passwords are never stored in plain text: use pgpass, an environment variable, or Fernet encryption with `ELLEMENTRY_SECRET_KEY`. |
| **Data management** | Paginated grid with search and sort, display names, descriptions, hidden columns, type conversion, **calculated columns** (validated SQL expressions, computed live), CSV/Excel export, column **profiling** (stats, histograms, top values), and **quality checks** with one-click fixes. |
| **Data preparation** | Recorded recipe steps: trim, change case, find/replace, standardize spelling variants, fill empty values, remove duplicates, delete rows, change type and drop a column. Steps are **replayed automatically after every refresh or replace**. |
| **Relationships** | Many-to-one lookups with validation: the key must be unique, types must match, and the match rate is reported. Automatic **suggestions** and an interactive model graph. Charts and the AI join through lookups automatically (LEFT JOIN from the fact table, never fanning out). |
| **Query tables** | Saved validated `SELECT`s that behave like datasets. Dependents are rebuilt when sources change, and deletion is blocked while something depends on them. There's also a SQL console with saved queries. |
| **Semantic layer** | **Metrics**: aggregate expressions with **business-rule filters**, e.g. *Net sales* counts only `transaction_type = 'Sale'`, excluding inter-warehouse transfers and franchise dispatches. They can be composite (`{units_returned} / NULLIF({units_sold},0)`), **semi-additive** (stock on hand uses the latest snapshot in each period) and have synonyms. Also a **glossary** (word → column, value or metric) and dataset-level **business rules**. Metrics are verified against the data when saved. |
| **Reports / charts** | Drag-and-drop builder with shelves for dimensions, measures and filters, date grains, date ranges (presets or custom), period comparison (previous period or last year), sort/limit and an auto-chart choice. Chart types: **KPI, line, area, bar, horizontal bar, stacked bar, bar+line combo (dual axis), pie, donut, scatter, heatmap, table, pivot table**. Click to drill down (month → day, category → value). Export as CSV, Excel or PNG. Multi-fact queries such as "sales and marketing spend by month" align facts on the calendar. |
| **Dashboards** | Drag and resize widgets, KPI cards with change vs the previous period, global **date-range** and **value** filters, period comparison, **drill-down with breadcrumbs** (configurable drill path), expand to full screen, widget PNG/Excel export, **PDF via print**, saved default filter values, duplicate, **templates**. |
| **Ask AI** | Conversational analytics with saved conversations and follow-ups ("only Amazon", "by category", "as a pie"). It handles time phrases, top/bottom N, "excluding X", period-over-period comparisons, "declining X but increasing Y", metric comparisons, and *"create a dashboard showing…"*. Every answer shows the chart, data, **SQL**, assumptions, the business rules applied and auto insights. Unclear questions get a clarification request, never invented numbers. |
| **Insights** | Trend (slope + R²), change, peak, robust anomaly detection (rolling median / MAD, marked on charts), correlation between two measures, top/bottom contributors, and exclusion of the incomplete current period from trend maths. |
| **Admin** | Query history covering charts, dashboards, SQL and AI, including rejected queries. Lineage graph (source → dataset → query table → report/dashboard). A local user switcher for testing roles. |

---

## 3. Architecture

```
frontend/  React 18 + TypeScript + Vite + Tailwind + Apache ECharts + react-grid-layout
backend/   FastAPI + SQLAlchemy 2 + Alembic + Pydantic 2 + pandas + sqlglot + APScheduler + httpx
  app/services/
    ingest.py, typeinfer.py      file reading, header detection, type inference, profiling
    warehouse.py, transforms.py  physical storage (raw table + view per dataset), replayable prep steps
    datasets.py                  workspace/dataset lifecycle, query tables, quality, lineage
    catalog.py, spec.py          semantic model + QuerySpec (shared by charts, dashboards and AI)
    query_engine.py              QuerySpec -> one parameterised SQL (multi-fact CTEs, lookups, rules)
    sql_safety.py, executor.py   static SQL validation + guarded read-only execution
    analytics.py                 run spec, period comparison, chart suggestion, insights
    connectors.py, scheduler.py  external databases, scheduled sync
    nlq/ vocab.py parser.py      offline NL interpreter built from the semantic layer and data values
         llm.py assistant.py     optional OpenAI-compatible LLM, conversation orchestration
PostgreSQL
  ellementry_meta.*        application metadata (18 tables, Alembic-managed)
  ws_<id>._raw_<t>    imported rows (+ _row_id identity) — one schema per workspace
  ws_<id>.<t>         view = raw columns + calculated columns  (query tables are views too)
```

**How a question becomes an answer.**

1. The interpreter maps words to metrics, columns, values and time ranges.
2. It builds a `QuerySpec`.
3. The compiler emits SQL. Each fact table gets one aggregated CTE: joins follow child→parent lookups, and metric rules become `FILTER (WHERE …)` clauses. Facts are then merged on shared dimension keys.
4. The SQL passes the static validator.
5. It runs in a `READ ONLY` transaction with a timeout and a schema-scoped `search_path`.
6. The explanation is built **only from the returned rows**.

If an LLM is configured and the semantic engine cannot answer, the LLM writes SQL from the schema and metric context. That SQL goes through the same validator and runtime guards, and gets one repair attempt.

### AI security model
- **Static validation** (sqlglot AST):
  - Exactly one `SELECT`/CTE/UNION. DML, DDL, `COPY`, `SET`, `SELECT INTO`, `FOR UPDATE` and multiple statements are rejected.
  - Only the workspace's views are allowed: no `_raw_` tables, `pg_catalog`, `information_schema`, `ellementry_meta`, other schemas or cross-database references.
  - Dangerous functions are blocked: `pg_*`, `lo_*`, `dblink`, `set_config`, `current_setting`, sequences and others.
- **Runtime limits**: `SET TRANSACTION READ ONLY`, `statement_timeout`, `lock_timeout`, `work_mem`, a `search_path` limited to the workspace schema, and a row cap.
- **Optional database-level separation**: run `scripts/create_readonly_role.sql` and set `READONLY_DATABASE_URL`.
- **Expressions** (calculated columns, metrics, filters) are parsed against an allow-list and re-rendered. Filter values are always bound parameters.
- **Credentials** come only from the environment, pgpass or Fernet-encrypted connector fields, and are never returned by the API.

### AI configuration: Anthropic Claude
Put your key in `.env` (Docker) or `backend/.env` (local) as `ANTHROPIC_API_KEY=...`, then run `docker compose up -d` (a plain `restart` won't load it).

**Model routing.** The choice is made in code with no extra API call, and each answer shows which model handled it:

| Question | Model | Effort |
|---|---|---|
| Everyday: one metric, a breakdown, a filter, a period, top-N | **Claude Haiku 5.5** | low |
| Genuinely complex: opposing trends ("declining X but increasing Y"), "why"/drivers, cohorts / running totals / share-of-total, top-N within groups, or 2+ weaker signals (comparisons across several time windows, many metrics, dimensions or datasets) | **Claude Sonnet 5.5** | medium |
| A Haiku plan fails validation, or Haiku asks for clarification on an answerable question | one escalation to **Sonnet 5.5** | medium |
| Narrative explanation of the results | Haiku 5.5 | low |

**Opus, Fable and Mythos are never used.**
- `ANTHROPIC_SIMPLE_MODEL` / `ANTHROPIC_COMPLEX_MODEL` accept only Claude Haiku/Sonnet IDs; anything else stops the app at startup.
- Anthropic's server-side refusal fallback is deliberately left off, because it can route requests to those models.

**How answers stay correct.**
- Claude returns a JSON-schema-constrained plan, preferably a semantic-layer QuerySpec, so metric definitions and business rules apply. It returns SQL only when a spec can't express the question.
- Any SQL passes the validator and runs read-only, and explanations are built only from the returned rows.
- The workspace schema prompt is prompt-cached.
- If the API is unreachable, the offline semantic engine answers and says so. Choose *Semantic engine* in the Ask box to force offline mode.

An OpenAI-compatible endpoint (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`; e.g. Ollama) is still supported and is used only when `ANTHROPIC_API_KEY` is empty.

---

## 4. Demo data & validation

`sample_data/generate.py` (deterministic, seed 42) creates a synthetic home & kitchen brand, roughly 280k rows:

- **Tables**: products, warehouses, channels, customers, orders, sales register (consumer sales **plus** inter-warehouse transfers and franchise dispatches), returns, inventory movements, weekly inventory snapshots, dispatch, and daily marketing spend.
- **Built-in story**: festive seasonality, Amazon growth, high glassware return rates, a flash-sale anomaly, and six SKUs whose sales collapse while restocking continues.
- **Deliberate mess**: title rows above the header, a duplicate product, case/space category variants, `Rs.`/`₹`-formatted amounts, mixed date formats, channel spellings (`amazon`, `Amazon.in`, `Website`), 187 duplicate sales rows, empty cities, and an empty unnamed column.

`ground_truth.json` holds answers computed independently with pandas from the clean data. The end-to-end test imports the messy files through the API, cleans them, and checks that AI answers match:

| Question | Validated against |
|---|---|
| What were total sales last month? | ₹64,14,621.05 (excludes transfers/franchise; register total incl. them is ₹77,26,799.81) |
| Compare Shopify and Amazon sales over the last six months | monthly values per channel |
| Which products have the highest return rate? | top-10 product return rates |
| Show inventory movement by warehouse | net movement per warehouse |
| Which products have declining sales but increasing stock? | product set (includes all 6 planted SKUs) |
| Compare marketing spend with sales revenue | monthly series |
| Create a dashboard showing monthly sales, returns and inventory | dashboard with KPI + trend widgets |

Relative dates are resolved against today's date. `TODAY_OVERRIDE=2026-10-17` pins "today" so these
answers can be reproduced on any date.

## 5. Tests

```powershell
cd backend
$env:TODAY_OVERRIDE="2026-10-17"; .venv\Scripts\python -m pytest -q     # uses database ellementry_analytics_test
```

Current result: **328 passed** in about 100 s. That includes roughly 80 s to build the demo workspace once. The suite covers:

- parsing, type inference, persistence, transforms and their replay, relationships, aggregations and multi-fact correctness
- SQL-safety validation and the runtime read-only/timeout guards
- dashboards, filters and drill-down
- NL parsing and follow-ups
- LLM output parsing, retry and rejection, using a mocked OpenAI-compatible endpoint
- API errors and roles
- the full ground-truth workflow

Frontend: `npm run typecheck` and `npm run build`.

---

## 6. Known limitations (honest status)

- **Authentication** is local and identity-only: the user is chosen by email in Settings or the `X-User-Email` header, with no passwords. Roles are enforced, but this isn't meant for multi-tenant internet exposure.
- **The offline NL engine** is rule-based. It understands the vocabulary in your semantic layer (metrics, synonyms, glossary, data values), not arbitrary phrasing. Unsupported questions get a clarification request; configure an LLM for open-ended questions.
- **Not implemented** (from the feature matrix): geo maps, forecasting/AutoML, what-if analysis, scheduled email reports, sharing via public links or embedding, live-connect (query-in-place) connectors, and SaaS app connectors. Data alerts and slideshows are also missing.
- **Known NL quirks**:
  - "by warehouse" on the sales register can group by the warehouse code rather than the name.
  - "this month vs previous period" compares with the same number of days just before it, not the same days of the previous month.
- **Scheduled refresh** applies to database connectors. File datasets are refreshed by uploading a new version (*Replace / Append*).
- **Excel/PNG/PDF export** happens client-side (PDF through the browser's print dialog).

See [`../research/FEATURE_MATRIX.md`](../research/FEATURE_MATRIX.md) for the full matrix with status.
