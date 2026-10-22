# 02 — Architecture

## Stack
| Layer | Tech |
|---|---|
| Frontend | React 18.3, TypeScript 5.5, Vite 7.3, Tailwind 3.4, ECharts 6.1, React Router 7.18, react-grid-layout 1.4, lucide-react |
| Backend | Python 3.12 (Docker) / 3.11+ (local), FastAPI, SQLAlchemy 2, Alembic, Pydantic 2 / pydantic-settings, pandas, openpyxl, sqlglot, APScheduler, httpx, cryptography (Fernet), python-dotenv, `anthropic>=1.17` |
| Database | PostgreSQL. In Docker it is 16-alpine; on the host it is PostgreSQL 18 (service `postgresql-x64-18`, port 5432) |
| AI | Anthropic Claude: Haiku 5.5 and Sonnet 5.5 only. Fallback order: an OpenAI-compatible endpoint, then the offline rule-based parser |

## Repository layout (`lumen/`)
```
CLAUDE.md                 agent entry point
README.md, QA_REPORT.md   user docs + security audit
docs/context/             these context files
Dockerfile, docker-compose.yml, .dockerignore
.env                      Docker secrets (git-ignored; NEVER print)   .env.docker.example = template
start.bat, scripts/       setup.ps1, start.ps1 (-Dev), create_readonly_role.sql
sample_data/              generate.py (seed 42, ~280k rows), messy CSV/XLSX, ground_truth.json
backend/
  .env / .env.example     local secrets (never print) / template
  alembic/versions/0001_initial.py   the single migration (lumen_meta schema)
  app/
    main.py               FastAPI app, security headers, opaque 500s, SPA serving, migrations on start
    config.py             Settings (env + backend/.env), check_model() allow-list, today()
    db.py, deps.py        engine/session; current_user + viewer/editor/admin role deps
    models.py             18 metadata tables (see 03)
    serializers.py, demo.py (builds demo workspace via public API)
    routers/workspaces.py /api/me, /api/demo, /api/workspaces/*
    routers/data.py       uploads, imports, datasets, columns, transforms, query tables,
                          relationships, lineage, connectors, sync, schedules
    routers/analysis.py   model, query (+export), reports, dashboards/widgets, sql console,
                          saved queries, metrics, glossary, rules, assistant/ask, conversations
    services/
      ingest.py, typeinfer.py      read files, header detection, type inference, profiling
      warehouse.py, transforms.py  physical storage + replayable prep steps
      datasets.py                  dataset lifecycle, query tables, quality, lineage, import_dataframe()
      catalog.py, spec.py          semantic catalog + QuerySpec
      query_engine.py              QuerySpec -> parameterised SQL
      expressions.py, filters.py   allow-listed expression parsing, filter compile
      sql_safety.py, executor.py   static validation + guarded read-only execution + query log
      analytics.py                 run_spec, comparison, chart suggestion, insights, fmt
      connectors.py, scheduler.py  external DBs, scheduled sync
      naming.py
      nlq/vocab.py, parser.py      offline NL interpreter
      nlq/claude.py                Anthropic routing/planning/explaining
      nlq/llm.py                   OpenAI-compatible fallback
      nlq/assistant.py             orchestration + conversations
  tests/                  pytest, real PostgreSQL DB lumen_analytics_test (see 07)
frontend/src/
  App.tsx (routes), api/client.ts, components/{Chart,ResultPanel,SpecBuilder,ui}.tsx,
  lib/format.ts, pages/*.tsx (see 06)
```

## Physical data model in PostgreSQL
- **`lumen_meta.*`** holds application metadata (Alembic-managed; see 03 for the tables).
- **`ws_<random>`** is one schema per workspace. Workspace 34's schema is `ws_8304153982f4`.
  - `_raw_<table>` holds the imported rows, plus a `_row_id` identity column.
  - `<table>` is a **view** over the raw columns plus any calculated columns. Query tables are views too.
  - Users, the AI and the SQL console only ever see the views. `_raw_` tables are blocked by the validator.

## How a question or chart becomes numbers
1. A UI shelf, a dashboard widget or the AI produces a **`QuerySpec`**: dimensions, measures/metrics, filters, time_range, compare, sort and limit.
2. **`query_engine.compile_query`** turns the spec into one parameterised SQL statement:
   - Each fact (base) dataset gets one aggregated CTE.
   - Dimensions are reached by **child→parent LEFT JOINs** along many-to-one relationships, so rows never fan out.
   - Metric business rules become `agg(...) FILTER (WHERE …)`.
   - **Semi-additive** metrics (stock) use the latest snapshot in each period.
   - Multi-fact queries merge the CTEs on shared dimension keys and on the calendar.
3. **`sql_safety.validate_select`** checks the SQL with the sqlglot AST. See 05.
4. **`executor.run_readonly`** runs it in a `READ ONLY` transaction with `statement_timeout`, `lock_timeout`, `work_mem`, `search_path` set to the workspace schema only, and a row cap. Every query is written to `query_history`.
5. **`analytics.run_spec`** adds the period comparison, a suggested chart, the date range, warnings and **insights**: trend slope/R², change, peak, MAD anomalies, correlation and contributors, with incomplete periods excluded.

## Ask AI flow (summary; details in 04)
```
question -> offline interpret() (intent: chitchat/help/dashboard/query, hints)
   ├─ Claude enabled & engine auto|llm -> route() -> Haiku or Sonnet plan (JSON schema)
   │      spec -> QuerySpec -> run_spec      |  sql -> validate_select -> run_readonly
   │      failure -> 1 escalation to Sonnet  |  explain() with Haiku + computed facts
   │      API unreachable -> offline engine with a note
   ├─ else OpenAI-compatible LLM (if LLM_BASE_URL set)
   └─ else offline semantic engine
```

## Background jobs
`scheduler.py` runs APScheduler in-process when `ENABLE_SCHEDULER=true`. It re-syncs connector datasets on `refresh_schedules`; workspace 34 has every dataset scheduled every 60 minutes. Prep transforms and calculated columns are replayed after every refresh or replace.
