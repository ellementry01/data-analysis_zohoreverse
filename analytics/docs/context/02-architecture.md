# 02 — Architecture

## Stack
| Layer | Tech |
|---|---|
| Frontend | React 18.3, TypeScript 5.5, Vite 7.3, Tailwind 3.4, ECharts 6.1, React Router 7.18, react-grid-layout 1.4, lucide-react |
| Backend | Python 3.12 (Docker) / 3.11+ (local), FastAPI, SQLAlchemy 2, Alembic, Pydantic 2 / pydantic-settings, pandas, openpyxl, sqlglot, APScheduler, httpx, cryptography (Fernet), python-dotenv, `anthropic>=1.17` |
| Database | PostgreSQL. In Docker it is 16-alpine; on the host it is PostgreSQL 18 (service `postgresql-x64-18`, port 5432) |
| AI | Anthropic Claude: Haiku 5.5 and Sonnet 5.5 only. Fallback order: an OpenAI-compatible endpoint, then the offline rule-based parser |

## Repository layout (`analytics/`)
```
CLAUDE.md                 agent entry point
README.md, QA_REPORT.md   user docs + security audit
docs/context/             these context files
Dockerfile, docker-compose.yml, .dockerignore
.env                      Docker secrets (git-ignored; NEVER print)   .env.docker.example = template
start.bat, scripts/       setup.ps1, start.ps1 (-Dev), create_readonly_role.sql,
                          configure_warehouse_workspace.py (syncs workspace 34, metrics, calculated columns),
                          build_executive_dashboards.py (rebuilds the 10 dashboards; see 08)
docs/                     AI_ASSISTANTS_PLAN.md (phases 0-8), EXECUTIVE_DASHBOARD_PLAN.md, WAREHOUSE_SCHEMA_REVIEW.md, WAREHOUSE_LOAD_FIX_PLAN.md
sample_data/              generate.py (seed 42, ~280k rows), messy CSV/XLSX, ground_truth.json
backend/
  .env / .env.example     local secrets (never print) / template
  alembic/versions/         0001_initial, 0002_assistant_groundwork, 0003_identity_access (ellementry_meta schema)
  evals/                    eval runner (python -m evals run <set>) and sets/: sample, dashboard_basic (80), dashboard_deep (50)
  app/
    main.py               FastAPI app, security headers, opaque 500s, SPA serving, migrations on start
    config.py             Settings (env + backend/.env), check_model() allow-list, today()
    db.py, deps.py        engine/session; current_user (google session / API token, or dev header) + viewer/editor/admin
                          role deps, which record the acting user on the workspace for permission checks
    models.py             18 metadata tables (see 03)
    serializers.py, demo.py (builds demo workspace via public API)
    routers/auth.py       Google sign-in, sign-out, API tokens, users, audit log, access rules
    routers/workspaces.py /api/me, /api/demo, /api/workspaces/*
    routers/data.py       uploads, imports, datasets, columns, transforms, query tables,
                          relationships, lineage, connectors, sync, schedules
    routers/analysis.py   model, query (+export), reports, dashboards/widgets, sql console,
                          saved queries, metrics, glossary, rules, assistant/ask, conversations,
                          dashboard assistant (/dashboards/key/{key}/assistant/ask[/stream]), feedback
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
      naming.py, dashboards.py     identifiers; dashboard keys/domains, applying dashboard filters
      ai_usage.py                  Claude cost ledger and spend caps
      auth.py, permissions.py      Google OIDC, sessions, API tokens; access rules (one check for people and assistant)
      audit.py                     audit log writer
      memory.py                    assistant memory: save, visibility, retrieval, staleness, extraction/profile jobs (Phase 4)
      jobs.py                      background job queue in the app database (Phase 4); app/worker.py runs it on its own
      data_issues.py               the data issue register: what an issue touches, pack lines, status changes (Phase 5)
      worth_a_look.py              "worth a look" items computed in code and cached per dashboard (Phase 5)
      agent/context.py             dashboard pack, screen state, filter inheritance (Phase 1)
      agent/tools.py, engine.py    read-only tools and the tool loop with limits and number check (Phase 2)
      agent/numbers.py             number finding/matching shared with the eval runner
      agent/global_scope.py        the Ask page's global assistant: dashboard index and scope (Phase 6)
      agent/domain_scope.py        the Stock / Operations / Executive assistants opened from the Alerts page (Phase 7)
      domain_agents.py             warehouse alerts, decisions, notices after a sync, the executive briefing (Phase 7)
      nlq/vocab.py, parser.py      offline NL interpreter
      nlq/claude.py                Anthropic routing/planning/explaining
      nlq/llm.py                   OpenAI-compatible fallback
      nlq/assistant.py             orchestration + conversations
  tests/                  pytest, real PostgreSQL DB ellementry_analytics_test (see 07)
frontend/src/
  App.tsx (routes), api/client.ts, components/{Chart,ResultPanel,SpecBuilder,ui,ChatMessage,AssistantPanel,
  UserMenu,AccessRulesCard,MemoryNotes,DataNotes}.tsx, pages/AdminPage.tsx, pages/MemoryPage.tsx, pages/DataIssuesPage.tsx,
  lib/format.ts, pages/*.tsx (see 06)
```

## Physical data model in PostgreSQL
- **`ellementry_meta.*`** holds application metadata (Alembic-managed; see 03 for the tables).
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
5. **`analytics.run_spec`** adds the period comparison, a suggested chart, the date range, warnings and **insights**: trend slope/R², change, peak, MAD anomalies, correlation and contributors, with incomplete periods excluded. Insights use only measures whose values are numbers (a MAX of a date is skipped).

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

## Dashboard assistant flow (Phases 1-2; details in 04)
```
dashboard chat question + screen state (filters, drill, focused widget)
   -> validate screen against the dashboard; recompute what is on screen; dashboard pack (cached)
   -> ASSISTANT_AGENT_LOOP on: tool loop (Haiku/Sonnet) -> read-only tools -> governed queries -> answer
         -> every number checked against tool results / screen / dashboard text (one rewrite, else a warning)
      off: one plan (as Ask AI) with the dashboard's filters inherited
   -> stored in a dashboard-scoped thread (screen state, steps, model, usage); streamed steps via SSE
```
Every Claude call goes through `claude._call` / `claude.call_with_tools`: model allow-list, spend caps, `ai_usage` ledger.

## Global assistant flow (Phase 6; details in 04)
```
Ask page question (admin, ASSISTANT_GLOBAL + agent loop on, engine not "semantic")
   -> scope global: GLOBAL_PROMPT + DASHBOARDS index (only dashboards the person may see; cached by fingerprint)
   -> the same tool loop: get_dashboard_context(key) and get_widget_data(dashboard_key=...) for detail, run_query,
      get_data_issues (all live issues on visible dashboards), memories from every scope -> answer
   -> thread scope_type = global (older "workspace" threads continue); /assistant/ask/stream sends live steps
```

## Scheduled domain agents (Phase 7; details in 04 and 08)
```
warehouse build (dw.py transform run) -> dw.py agents run all -> insight.alert_event (one open event per condition,
   auto-resolved) -> mart.v_agent_alerts / v_agent_rules / v_agent_runs -> hourly sync -> datasets agent_alerts, ...
   -> after the sync: new alerts and failed runs announced once (notifications); briefing queued when BRIEFING_EVERY_DAYS is due
Alerts page (admins) -> Acknowledge / Dismiss -> agent_decisions + a decision memory (the warehouse is never written)
   -> Explain -> Ask page with domain=stock|operations|executive -> the same tool loop + get_alerts
```

## Memory (Phase 4; details in 04)
```
before an answer:  memories the asker may see (this dashboard, its domain, global) ranked by text match, kind,
                   recency, use  -> up to 15 + their profile -> WHAT YOU REMEMBER block in the question turn
during:            propose_memory (active if the USER's words asked, else a proposal), search_memory
after (jobs):      thread summary when long; memory extraction once the chat has been quiet 30 min -> proposals
                   -> user accepts/edits/rejects (panel cards, Memory page); profile rewrite after 10 approvals/weekly
```

## Identity and access (Phase 3; details in 05)
`AUTH_MODE=google`: session cookie from Google sign-in or `Authorization: Bearer` API token; `dev`: X-User-Email header (localhost only). The workspace role dependency records the acting user; `load_catalog`, `dataset_of`, dashboard lookups, lineage and the assistant tools apply access rules from it.

## Background jobs
`scheduler.py` runs APScheduler in-process when `ENABLE_SCHEDULER=true`. It re-syncs connector datasets on `refresh_schedules`; workspace 34 has every dataset scheduled every 60 minutes. Prep transforms and calculated columns are replayed after every refresh or replace.

Since Phase 4 it also works through the **job queue** (`services/jobs.py`, table `jobs`) every 30 seconds (unless `ENABLE_WORKER=false`): conversation summaries, memory extraction and profile rewrites run there, never in a request. A job is claimed with `SELECT ... FOR UPDATE SKIP LOCKED` (so a separate `python -m app.worker` process can share the queue), retried after 2, 4 ... minutes up to 3 attempts, then kept as `failed` with its error; a job left `running` by a dead process is picked up again after 10 minutes; finished jobs are deleted after 14 days. Hourly (memory on): the staleness check and due weekly profile rewrites are queued. After a sync that ran (Phase 5, data issues on), a `worth_a_look` job per workspace recomputes the dashboards whose fingerprint (definitions, metric definitions, row counts, today) changed. Phase 7 (scheduled agents on): the same hook announces new warehouse alerts and failed agent runs once (`agent_sync_state`) and queues a `briefing` job when `BRIEFING_EVERY_DAYS` has passed since the last briefing.
