# 05 — Security model and rules

The full audit is in `QA_REPORT.md` (dated 2026-10-17). Its verdict: ready for **local or trusted-network use**, but **not for internet exposure**, because there is no password authentication.

## Rules every agent must follow
1. **Never print, copy, log or echo secrets.** That covers `lumen/.env`, `backend/.env`, the Anthropic key, `POSTGRES_PASSWORD`, `LUMEN_CONN_*` and database URLs with passwords. Mask them (`sed 's/=.*/=<redacted>/'`) when you inspect env files.
2. **Never ask the user for passwords, API keys or auth codes in chat.** Tell them which env var to set and in which file; they edit it themselves.
3. **Never weaken the AI or SQL guards.** Every model- or user-supplied SQL statement goes through `sql_safety.validate_select` and `executor.run_readonly`.
4. **Never use Opus or Fable models** and never enable server-side fallbacks (see 04).
5. **The app reads the Ellementry warehouse read-only.**
   - The app connects only as the `ellementry_metrics` role, which can read only `mart`.
   - The warehouse changes only through `lumen-analytics/warehouse`: `python dw.py …` with the admin login from `warehouse/.env` (never printed), after `python dw.py backup`, with reconciliation afterwards. Tests run only on a disposable database.
   - `lumen-analytics/exports` holds customer data. Never commit it, upload it or print personal fields; the normaliser drops them.
6. **Don't claim a feature works unless it's implemented and tested.**

## Defences in place
- **Static SQL validation** (`sql_safety.py`, sqlglot AST):
  - Exactly one SELECT, CTE or UNION statement.
  - Rejected: DML, DDL, COPY, SET, SELECT INTO, FOR UPDATE, multiple statements and **`WITH RECURSIVE`**.
  - Only the workspace's views are allowed. Rejected references: `_raw_` tables, `pg_catalog`, `information_schema`, `lumen_meta`, other `ws_*` schemas, `public`, and cross-database names.
  - **CTE names are resolved per scope.** This is the SEC-1 fix: a fake CTE called `pg_stats` used to unlock the real `pg_stats` in other scopes and leak other workspaces' values.
  - Blocked functions include `pg_*`, `lo_*`, `dblink`, `set_config`, `current_setting`, sequence functions, `repeat`, `current_database` and `current_query`.
- **Runtime guards** (`executor.run_readonly`):
  - `SET TRANSACTION READ ONLY`, `statement_timeout` (15 s; 10 s for AI), `lock_timeout` and `work_mem`.
  - `search_path` is set to the workspace schema only.
  - Row cap: `QUERY_ROW_LIMIT=5000`; AI SQL is wrapped in `LIMIT 500`.
- **Optional database-level separation:** run `scripts/create_readonly_role.sql` and set `READONLY_DATABASE_URL`. This is recommended (R5) but not configured now.
- **Expressions** (calculated columns, metric expressions, filters) are parsed against an allow-list and re-rendered. Filter values are always bound parameters.
- **Uploads:**
  - Streamed in 1 MB chunks with the `MAX_UPLOAD_MB` cap enforced while reading.
  - `.xlsx` zip bombs are caught by checking the declared uncompressed size and ratio before parsing.
- **Exports:** cells starting with `= + - @` are prefixed with `'` (CSV-injection guard, `_csv_safe`).
- **HTTP:**
  - CSP `script-src 'self'`, `frame-ancestors 'none'`, nosniff, `X-Frame-Options: DENY`, Referrer-Policy.
  - The API sends `Cache-Control: no-store`. The SPA `index.html` is served with `no-cache`.
  - 500 responses are opaque and carry a reference id; details go only to the server log.
  - The SPA static route has a path-traversal guard.
- **Frontend:** `escapeHtml` is applied to every ECharts tooltip and graph label (FE-1 stored-XSS fix).
- **Cross-workspace access (IDOR):** every id-scoped route checks the workspace; conversations also check the user.
- **Container:** non-root `lumen` user, read-only root filesystem, `cap_drop: ALL`, `no-new-privileges`, 2 GB memory and 256 PID limits, ports bound to 127.0.0.1 only.

## Accepted risks (QA_REPORT §4)
- **R1:** identity-only login through the `X-User-Email` header. Add OIDC or an SSO proxy before any shared deployment.
- **R2:** npm audit findings remain in Tailwind 3's build-time watcher. Migrate to Tailwind 4 when convenient.
- **R3:** expensive but valid SQL is only bounded by the timeout.
- **R4:** the `/sql` console echoes the first line of the database error.
- **R5:** the dedicated read-only database role is not set up yet.
