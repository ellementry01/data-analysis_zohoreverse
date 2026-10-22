# 03 — Backend reference

## Metadata tables (`lumen_meta`, see `backend/app/models.py`)
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
| reports, dashboards, dashboard_widgets | Saved charts; dashboards hold layout, filters and drill paths |
| saved_queries | SQL console saves |
| query_history (`QueryLog`) | Every chart, dashboard, SQL and AI query, including rejected ones |
| conversations, messages | Ask AI threads; each message stores its spec for follow-ups |
| refresh_schedules | Per-dataset sync interval, with last run and status |

There is a single Alembic migration, `0001_initial.py`, and migrations run automatically on app start.

## API (all under `/api`; workspace routes are `/api/workspaces/{ws_id}/…`)
- **Auth:** the user comes from the `X-User-Email` header, defaulting to `DEFAULT_USER=owner@local`. Each route declares the role it needs through `deps.viewer/editor/admin`. A dataset id is always checked against the workspace (`dataset_of`).
- **workspaces.py:**
  - `GET /me` returns the user and LLM info: provider, simple/complex model labels and the base-URL host.
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
  - Dashboard extras: widgets CRUD, layout, `widgets/{wid}/data`, `duplicate` and `values`.
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
  - (a) an env var named in `config.password_env`, which **must match `^LUMEN_CONN_[A-Z0-9_]{1,60}$`**. It is read from the process env, then from `backend/.env` via dotenv.
  - (b) a Fernet-encrypted password, using `LUMEN_SECRET_KEY`.
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
