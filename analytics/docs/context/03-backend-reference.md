# 03 — Backend reference

## Metadata tables (`ellementry_meta`, see `backend/app/models.py`)
| Table | Purpose |
|---|---|
| workspaces, workspace_members | Workspaces and members, each member with role `viewer` < `editor` < `admin` |
| datasets | `kind` is file, connector or query; also `slug`, `source_info` (connector id, source schema/table), `default_date_column` and `query_sql` |
| dataset_columns | Name, type, display name, description, hidden flag, calculated expression |
| transforms | Ordered prep recipe steps that are replayed after each refresh |
| relationships | Many-to-one lookups (`from_dataset.col → to_dataset.col`) |
| connectors | `kind` and a `config` JSON (host, port, database, user, schema, `password_env` or an encrypted password) |
| metrics | name, label, `expression`, `dataset_id`, `filters` (business rules), `time_column`, `semi_additive`, `synonyms`, `format`, `higher_is_better` |
| glossary_terms, business_rules | Word → column/value/metric mappings; dataset-level rules |
| reports, dashboards, dashboard_widgets | Saved charts; dashboards hold layout, filters and drill paths. Each dashboard has a stable **`key`** (unique per workspace, e.g. `stock`; survives renames and rebuilds, unlike the id) and a **`domain`** (`stock`, `operations`, `sales`, `executive`, `data`, …) |
| saved_queries | SQL console saves |
| query_history (`QueryLog`) | Every chart, dashboard, SQL and AI query, including rejected ones |
| conversations, messages | Assistant threads. `scope_type` says where a thread lives: `workspace` (the Ask page), `dashboard` (+ `dashboard_key`) or `global`; also `summary` (compacted older turns) and `archived`. Each message stores its spec for follow-ups, plus `screen_state`, `tool_trace`, `model`, `usage` and `feedback` (filled from Phase 1 of the assistants plan) |
| ai_usage (`AIUsage`) | One row per Claude call: user, workspace, conversation, purpose (`chat`, `explain`, …), model, tokens, estimated cost in rupees. The spend caps read it |
| refresh_schedules | Per-dataset sync interval, with last run and status |
| users, auth_sessions, login_states, api_tokens | Phase 3 sign-in: people who signed in (active, platform admin), sessions (token hashes, expiry), pending Google sign-ins (state, nonce, PKCE), script tokens (hashes) |
| access_rules | Restrict a dashboard, a domain or a dataset to a minimum role or named people (see 05) |
| audit_events | Who did what and when (sign-ins, assistant questions, rule, member, user, token and memory changes) |
| memories | Phase 4: what the assistants remember. `layer` personal / shared (team fact) / decision; `kind` preference, fact, decision, caveat, open_question; `scope` global, `dashboard:<key>` or `domain:<name>`; `owner_email`; `visibility` (decisions: private/shared); `status` proposed, active, rejected, retired, needs_review (+ `review_reason`); `origin` explicit, inferred, manual; `share_status` (team-fact approval); source conversation, message and excerpt; `depends_on` (metric fingerprints); use count and last use. Full-text index on text + rationale |
| user_profiles | One "how this person works" note per user and workspace, rewritten from their memories (version, sources, whether the user edited it) |
| jobs | The background job queue (kind, payload, dedupe key, status, attempts, run_after, error, result) |
| data_issues | Phase 5 issue register: `code` (D-124), title, area, `status` open / awaiting / parked / solved (+ the log's wording), `severity`, summary (what is needed), `note` (one line for tiles), `affects` {dashboards, metrics, datasets}, owner, `source` manual / import / watchdog, opened/solved dates |
| notifications | Owner notices (issue opened / solved / reopened / imported; later the watchdog's), read per person (`read_by`) |
| dashboard_insights | Cached "worth a look" items per dashboard key, with the fingerprint they were computed for |

Migrations run automatically on app start: `0001_initial.py`, `0002_assistant_groundwork.py` (dashboard keys backfilled from names, conversation scopes, message details, `ai_usage`), `0003_identity_access.py` (users, sessions, login states, API tokens, access rules, audit), `0004_memory.py` (memories, user profiles, jobs, `conversations.memory_scanned_upto_message_id`), `0005_data_issues.py` (data issues, notifications, dashboard insights).

- **Phase 7 tables:** `agent_decisions` (workspace, warehouse alert id and code, acknowledged | dismissed, note, who, when, the alert's message, the decision memory), `briefings` (facts JSON, fingerprint, data date, text, written by Sonnet or `code`, usage), `agent_sync_state` (the newest alert and run already announced). Migration `0006_domain_agents`.

- `eval_runs` (Phase 8, migration 0007): one row per evaluation-set run posted by `python -m evals run` (set, live or offline, passed/total, numbers checked/correct, invented, cost, median time, failures as case ids and problems with no answer texts, git commit, note, who, when). Read by the Monitoring tab and `python -m evals gate`.

## API (all under `/api`; workspace routes are `/api/workspaces/{ws_id}/…`)
- **Auth:** `AUTH_MODE=google`: a session cookie from Google sign-in, or an API token (`Authorization: Bearer`); `AUTH_MODE=dev`: the `X-User-Email` header, defaulting to `DEFAULT_USER=owner@local` (see 05). Each route declares the role it needs through `deps.viewer/editor/admin`. A dataset id is always checked against the workspace (`dataset_of`).
- **auth.py (Phase 3):** `GET /api/auth/config` (public: sign-in mode), `GET /api/auth/login?next=` -> Google, `GET /api/auth/callback`, `POST /api/auth/logout`; platform admins: `GET/POST/DELETE /api/admin/tokens`, `GET /api/admin/users`, `PATCH /api/admin/users/{email}` (`active`, `is_platform_admin`), `GET /api/admin/audit?action=&who=&before=&limit=`; workspace admins: `GET/POST/DELETE /api/workspaces/{ws}/access-rules`.
- **agents.py (Phase 7, `ASSISTANT_SCHEDULED`, workspace admins):** `GET /agents/summary` (rules with open / critical / undecided counts, latest runs, the data date, the latest briefing); `GET /agents/alerts?domain=stock|operations&status=OPEN|RESOLVED|ALL&code=&q=`; `POST /agents/alerts/{id}/decision` `{decision: acknowledged|dismissed, note}` (409 on an alert that is no longer open, 404 unknown); `GET /agents/decisions?alert_id=`; `GET /agents/briefings`; `POST /agents/briefing` (writes one unless the facts are unchanged; 409 without the views). Alerts are read from datasets `agent_alerts`, `agent_rules`, `agent_runs` through `validate_select` + `run_readonly`.
- **analysis.py, domain assistants (Phase 7):** `POST /assistant/ask` and `/assistant/ask/stream` take an optional `domain` (stock | operations | executive): admins with scheduled agents and the agent loop on get that domain assistant (thread `scope_type` `domain:<name>`, listed with the Ask page's threads); otherwise the global assistant or the old path.
- **analysis.py, Ask page (Phase 6):** `POST /assistant/ask` answers with the global assistant for workspace admins when `ASSISTANT_GLOBAL` and the agent loop are on (engine `semantic` keeps the offline engine); `POST /assistant/ask/stream` is the same as server-sent events; `GET /conversations` lists the Ask page's `workspace` and `global` threads (with `scope_type`).
- **memory.py (Phase 4, `ASSISTANT_MEMORY`; per person):** `GET /memory?status=&layer=&scope=&q=` (yours plus team facts and shared decisions), `POST /memory` (manual, active), `PATCH /memory/{id}`, `POST /memory/{id}/{accept|reject|retire|restore|keep|share|unshare|approve_share|reject_share}`, `DELETE /memory/{id}`, `GET /memory/proposals?dashboard_key=`, `GET /memory/share-queue` (workspace admins), `GET|PUT /memory/profile`, `POST /memory/profile/rewrite` (queues a job), `GET /memory/stats` (acceptance rate of learned suggestions).
- **data_issues.py (Phase 5, `ASSISTANT_DATA_ISSUES`):** `GET /data-issues?status=live|open|awaiting|parked|solved` (members), `POST /data-issues` and `PATCH /data-issues/{code}` (workspace admins; status changes notify and send memories naming the issue to review), `POST /data-issues/import` (admins; used by `scripts/import_issue_log.py`: adds missing codes, marks solved ones, never overwrites edits), `GET /dashboards/key/{key}/insights` (members: live issues with the tiles they touch, and the cached "worth a look" items; queues a recompute when stale, never computes in the request), `GET /notifications`, `POST /notifications/read` (admins).
- **workspaces.py:**
  - `GET /me` returns the user and LLM info: provider, simple/complex model labels and the base-URL host, plus `features` (the assistant feature flags, all off until their phase is signed off).
  - `POST /demo` builds the demo workspace.
  - Workspaces have CRUD, members (`PUT/DELETE members`) and `GET history`.
- **data.py:**
  - `POST /uploads`: streamed, with a size cap.
  - `GET /uploads/{id}/preview` and `POST /imports` (modes new, append and replace).
  - Datasets: CRUD, `rows`, `profile`, `quality`, and `export` (CSV/Excel with formula-injection guards).
  - Columns: `PATCH`, `POST` (calculated columns), `DELETE`.
  - `transform-kinds`, `transforms`, and `query-tables`.
  - `relationships` (plus `/suggestions`) and `lineage`.
  - `connector-kinds` and `connectors`, with `test`, `tables`, `preview` and `import`.
  - `datasets/{id}/sync`, `datasets/{id}/schedule` and `schedules`.
- **analysis.py:**
  - `GET /model`.
  - `POST /query` and `/query/export`.
  - CRUD for `reports` and `dashboards`.
  - Dashboard extras: widgets CRUD, layout, `widgets/{wid}/data`, `duplicate` and `values`; `GET /dashboards/key/{key}` finds a dashboard by its stable key. Create and update take optional `key` and `domain` (create derives the key from the name when omitted; update keeps it).
  - `GET /conversations` lists only the user's Ask-page threads (`scope_type = workspace`), and Ask never continues a dashboard or global thread. `GET /conversations/{cid}` returns the thread's scope and each message's `feedback`.
  - `POST /conversations/{cid}/messages/{mid}/feedback` with `{feedback: "up"|"down"|null, note}`: thumbs on an answer; only the thread's owner.
  - **Dashboard assistant (Phase 1):** `POST /dashboards/key/{key}/assistant/ask` with `{question, conversation_id?, engine?, screen_state: {filters: [{id, value}], drill: {widget_id: [{field, value}]}, focus_widget_id}}`, and `GET /dashboards/key/{key}/assistant/conversations` (the user's threads on that dashboard). `POST /dashboards/key/{key}/assistant/ask/stream` is the same as server-sent events (steps, then the answer). All need `ASSISTANT_DASHBOARD_CHAT=true` (403 otherwise) and, until real sign-in exists, the workspace **admin** role. The screen state is validated against the dashboard's own filters, widgets and drill fields (400 otherwise).
  - `POST /sql` (the console), plus `saved-queries`.
  - CRUD for `metrics`, `glossary` and `rules`.
  - `POST /assistant/ask` with `{question, conversation_id?, engine: auto|semantic|llm}`, and `GET /assistant/suggestions`.
  - `conversations`.
- **`GET /api/health`** is used by the Docker health check.

## QuerySpec (`services/spec.py`)
```python
Dimension(field="dataset.column" | "@time", grain=day|week|month|quarter|year, alias, label)
Measure(metric="net_sales") | Measure(field="dataset.col" | "dataset.*", agg=sum|avg|count|count_distinct|min|max|median)
Filter(field, op="eq"|..., value)        # values always bound parameters
time_range: preset str | {"preset"} | {"last": n, "unit"} | {"from","to"};  time_field
compare: previous_period | previous_year;  sort: [{field: alias, dir}];  limit;  apply_rules=True
```
- `"dataset.*"` with `agg=count` counts rows.
- `"@time"` means "each measure's own date column": the metric's `time_column` or the dataset's `default_date_column`.

## Ingestion notes
- Header-row auto-detection skips title rows and supports a manual override.
- Type inference handles `₹`/`Rs.`/commas/`(neg)`/`%`, booleans, and leading-zero IDs (kept as text).
- Mixed `YYYY-MM-DD` and `dd/mm/yyyy` dates are handled. For the unmatched remainder of the values, the best format is detected, so dd/mm is not parsed month-first.
- Pre-import warnings cover empty values, type conflicts, duplicates, spelling variants and missing headers.
- **Connector imports** pass `conn.column_types()` (`source_types`) into `datasets.import_dataframe`. This keeps date and number types correct even when a source view is empty.

## Connectors (`services/connectors.py`)
- The `postgresql` kind connects read-only. Any SQLAlchemy URL also works, through an extensible registry.
- The password comes from one of:
  - (a) an env var named in `config.password_env`, which **must match `^ELLEMENTRY_CONN_[A-Z0-9_]{1,60}$`**. It is read from the process env, then from `backend/.env` via dotenv.
  - (b) a Fernet-encrypted password, using `ELLEMENTRY_SECRET_KEY`.
  - (c) pgpass.
- A password inside a URL is rejected. Passwords are never returned by the API and never logged.

## Offline NL engine (`nlq/vocab.py`, `nlq/parser.py`)
- The vocabulary is built from the following, normalised and tokenised:
  - metric names, labels and synonyms
  - column names and display names
  - glossary terms
  - distinct data values (≤300 per column)
- `interpret()` returns an `Interpretation`:
  - `kind`: query, trend_compare, dashboard, help, chitchat or clarify
  - plus `spec`, `assumptions`, `clarification` and `suggestions`
- It handles:
  - time phrases
  - top/bottom N
  - "excluding X", which produces a negative filter
  - "this year vs last year"
  - "declining X but increasing Y"
  - counting: a counting cue plus a dataset name gives a `dataset.*` count, before any value match
  - follow-ups ("only Amazon", "by category", "as a pie"), which modify the previous spec
  - "create a dashboard showing…"
- When Claude is on, the parser is still used for chitchat, help and dashboard intents, and as routing hints.

## Monitoring and evaluation runs (Phase 8, `routers/monitor.py`, platform admins)
- `GET /api/admin/monitor?days=14`: AI cost (total, per day in India time, per person with questions asked and questions refused by the limit, per purpose, per model), answers (count, median and 95th-percentile time overall and per engine, answers with a number warning, thumbs up/down; the newest 5,000 answers), tool calls and errors per tool with the latest error, the job queue (by status, oldest waiting, recent failures).
- `GET /api/admin/monitor/thumbs-down?days=30`: answers marked wrong, with the question, the answer, the note, model, time, warnings and the steps (tool, input, ok, error, row count; no data rows).
- `POST /api/admin/eval-runs` (the runner records each run), `GET /api/admin/eval-runs?set_name=&live=`.
- Per-person question limits (`services/rate_limit.py`): the four ask routes and `POST /agents/briefing` answer 429 with a plain message and `Retry-After` past `ASSISTANT_RATE_PER_MINUTE` / `ASSISTANT_RATE_PER_HOUR`; counted from `audit_events` (`assistant_ask`, `briefing`), so it holds across processes; questions with the offline engine (or without Claude) are neither limited nor counted; a refusal is audited as `rate_limited`.
