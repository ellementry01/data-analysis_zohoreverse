# 05 — Security model and rules

The full audit is in `QA_REPORT.md` (dated 2026-10-17). Its verdict: ready for **local or trusted-network use**, but **not for internet exposure**, because there is no password authentication.

## Rules every agent must follow
1. **Never print, copy, log or echo secrets.** That covers `analytics/.env`, `backend/.env`, the Anthropic key, `POSTGRES_PASSWORD`, `ELLEMENTRY_CONN_*` and database URLs with passwords. Mask them (`sed 's/=.*/=<redacted>/'`) when you inspect env files.
2. **Never ask the user for passwords, API keys or auth codes in chat.** Tell them which env var to set and in which file; they edit it themselves.
3. **Never weaken the AI or SQL guards.** Every model- or user-supplied SQL statement goes through `sql_safety.validate_select` and `executor.run_readonly`.
4. **Never use Opus or Fable models** and never enable server-side fallbacks (see 04).
5. **The app reads the Ellementry warehouse read-only.**
   - The app connects only as the `ellementry_metrics` role, which can read only `mart`.
   - The warehouse changes only through `warehouse/` (repo root): `python dw.py …` with the admin login from `warehouse/.env` (never printed), after `python dw.py backup`, with reconciliation afterwards. Tests run only on a disposable database (`dw_test_po`). ERP access is the user's signed-in session: download reports only, never change anything or sign out.
   - `exports/` (repo root, not in git) holds customer data. Never commit it, upload it or print personal fields; the normaliser drops them.
6. **Don't claim a feature works unless it's implemented and tested.**

## Defences in place
- **Static SQL validation** (`sql_safety.py`, sqlglot AST):
  - Exactly one SELECT, CTE or UNION statement.
  - Rejected: DML, DDL, COPY, SET, SELECT INTO, FOR UPDATE, multiple statements and **`WITH RECURSIVE`**.
  - Only the workspace's views are allowed. Rejected references: `_raw_` tables, `pg_catalog`, `information_schema`, `ellementry_meta`, other `ws_*` schemas, `public`, and cross-database names.
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
- **Container:** non-root `ellementry` user, read-only root filesystem, `cap_drop: ALL`, `no-new-privileges`, 2 GB memory and 256 PID limits, ports bound to 127.0.0.1 only.

## Sign-in and access (Phase 3, 2026-11-07)
- `AUTH_MODE=google`: Google Workspace sign-in (OIDC code flow with PKCE, `hd` limited to the company domain). The ID token's RS256 signature is checked against Google's published keys, and its issuer, audience, expiry, nonce, verified email and hosted domain are checked (`services/auth.py`). The browser gets a random session token in an HttpOnly, SameSite=Lax cookie (Secure on https); the database stores only its SHA-256. Sessions end after `SESSION_HOURS` (12) or `SESSION_IDLE_HOURS` (4) without use. Cookie-authenticated writes with a foreign Origin are refused. Redirect targets after sign-in are same-site paths only.
- Scripts use API tokens (`Authorization: Bearer`), created by platform admins, shown once, stored hashed, revocable, 1-365 days.
- `AUTH_MODE=dev` (the `X-User-Email` header) remains for local development and tests; the app **refuses to start** in dev mode unless `PUBLIC_BASE_URL` is localhost, and in google mode without client id, secret and domain, or without https outside localhost.
- Users: switching a user off revokes every session and token at once. `BOOTSTRAP_ADMINS` (emails) become platform admins and workspace admins on sign-in. In google mode, workspace members must be company accounts.
- **Access rules** (`services/permissions.py`): dashboards, domains of dashboards and datasets can be restricted to a minimum workspace role or named people; without rules everything stays visible to members; workspace admins see everything. Enforced at one place: the workspace dependency records who is acting, and `load_catalog`, `dataset_of`, dashboard lookups, lineage and the assistant's tools read it. The assistant never sees more than the person asking (the streaming thread copies the asker onto its own workspace object).
- **Audit log** (`audit_events`): sign-ins and failures, sign-outs, assistant questions, access-rule, membership, user and token changes; viewable by platform admins (Administration page).
- Known limit: a query table built by an admin on a restricted dataset is a dataset of its own; restrict it too.

## Accepted risks (QA_REPORT §4)
- **R1:** identity-only login through the `X-User-Email` header. **Fixed in code (Phase 3)**: closes when `AUTH_MODE=google` is switched on in the live deployment.
- **R2:** npm audit findings remain in Tailwind 3's build-time watcher. Migrate to Tailwind 4 when convenient.
- **R3:** expensive but valid SQL is only bounded by the timeout.
- **R4:** the `/sql` console echoes the first line of the database error.
- **R5:** the dedicated read-only database role is not set up yet.
