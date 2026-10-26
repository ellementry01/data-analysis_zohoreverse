# Ellementry Analytics — Security & Quality Report

**Date:** 2026-10-17. **Build:** Docker image `ellementry-analytics:latest` with PostgreSQL 16.

**Verdict:** ready for **local / trusted-network use**. All critical, high and medium findings are fixed and
covered by regression tests. Ellementry is **not** ready for exposure to the internet, because it has no password
authentication by design.

## 1. What was tested

| Area | Method | Result |
|---|---|---|
| Automated backend suite | 363 pytest tests against a real PostgreSQL test DB | **363 passed** (≈2 min) |
| Answer correctness | 7 business questions vs. independently computed ground truth, in Docker | **All match** (₹64,14,621.05; 12/12 monthly values; return-rate top 10; 45/45 products…) |
| SQL-injection / validator bypass | Adversarial queries: CTE shadowing, schema-qualified names, catalog access, writable CTEs, DoS functions | 1 critical found → **fixed** |
| Cross-workspace access (IDOR) | Every id-scoped route probed as a non-member | **No issue** |
| Role enforcement | viewer / editor / admin on mutating routes | **No issue** |
| Uploads | Size limits, path traversal, malformed and zip-bomb workbooks | 2 issues → **fixed** |
| Exports | CSV/Excel formula injection | 1 issue → **fixed** |
| Frontend XSS | ECharts HTML tooltips with malicious data values / names | 1 high → **fixed** |
| Error handling / info leaks | Fuzzed invalid inputs; 500 bodies | 2 issues → **fixed** |
| HTTP hardening | Headers, CSP, CORS, SPA path traversal | Headers **added**; traversal guard OK |
| Dependencies | `pip-audit`, `npm audit` | Python **clean**; npm: runtime libraries upgraded, build-tool residue accepted (§4) |
| Performance | Key endpoints on ≈280k-row demo | All **< 300 ms** (nothing near the 2 s budget) |
| Container | Non-root, read-only rootfs, health check, restart persistence | **Pass** |

## 2. Findings and fixes

| ID | Severity | Finding | Fix | Test |
|---|---|---|---|---|
| SEC-1 | **Critical** | The SQL validator treated a CTE name as safe in **every** scope. A dummy CTE named `pg_stats` let a query read the real `pg_stats` elsewhere, exposing **other workspaces' data values** through column statistics. | Scope-aware CTE resolution in `sql_safety.py` | `test_security_audit.py` |
| FE-1 | **High** | Stored XSS: ECharts renders tooltips as HTML. Scatter/heatmap tooltips and lineage/model graph labels interpolated raw data values and dataset names. | `escapeHtml` applied to every tooltip interpolation | frontend build + review |
| SEC-2 | Medium | CSV/Excel exports kept cells starting with `= + - @` as live spreadsheet formulas (CSV injection). | Prefixed with `'` on export | `test_security_audit.py` |
| SEC-3 | Medium | The upload size limit was checked only after the whole file was read into memory (memory-exhaustion DoS). | Streamed in 1 MB chunks, cap enforced while reading | `test_security_audit.py` |
| SEC-5 | Medium | Query amplification: `repeat('x', 1e9)` (memory not bounded by `work_mem`), unbounded recursive CTEs, and fingerprinting via `current_database()`/`current_query()`. | Functions blocked; `WITH RECURSIVE` rejected | `test_hardening.py` |
| SEC-6 | Medium | `.xlsx` decompression bombs: only the compressed size was limited. | Declared uncompressed size and ratio checked before parsing | `test_hardening.py` |
| SEC-7 | Low | Unhandled errors returned the first line of the internal exception to the client. | Opaque message + reference id; details only in the server log | `test_hardening.py` |
| SEC-8 | Low | No security headers. | CSP (`script-src 'self'`, `frame-ancestors 'none'`…), nosniff, `X-Frame-Options: DENY`, `Referrer-Policy`, `Cache-Control: no-store` on the API | `test_hardening.py` |
| SEC-4 | Low | `?filters=123` (valid JSON, not a list) caused a 500. | Now 400 | `test_security_audit.py` |
| DEP-1 | Medium | Vulnerable frontend libraries: ECharts < 6.1 (XSS), React Router (open redirect), Vite 5 (dev-server path traversal). | Upgraded to **ECharts 6.1.0, React Router 7.18.4, Vite 7.3.7** | build + browser check |

### Checked and found safe
- **Cross-workspace access:**
  - Every route that takes an id checks that it belongs to the caller's workspace (and to the user, for conversations).
  - Schema-qualified access (`"ws_other".t`, `ellementry_meta`, `pg_catalog`, `information_schema`, `public`) and `_raw_` tables are rejected.
  - Quoted-identifier tricks such as `"set_config"(...)` don't resolve.
- **Connectors:** passwords are never returned or logged. A password inside a URL is rejected, and saved passwords are Fernet-encrypted.
- **LLM path:** generated SQL always passes the validator and runs in a READ ONLY transaction with a timeout. Prompt injection hidden in data values can't escape those checks.
- **Static file route:** path traversal is blocked by a `commonpath` guard.

## 3. Container hardening (verified)
- The image is multi-stage and contains no compilers or Node. The runtime is `python:3.12-slim`, 575 MB.
- The app runs as the unprivileged user `ellementry` (uid 999). Writes to the root filesystem fail; only the `uploads` volume is writable.
- `cap_drop: ALL`, `no-new-privileges`, a 2 GB memory limit and a 256-process limit are set.
- Ports are published on **127.0.0.1 only**. The database password is required (Compose refuses to start without it) and is stored in a git-ignored `.env`.
- A health check runs on `/api/health`.
- Data survives `docker compose down` / `up`, because it lives in the named volumes `pgdata` and `uploads`.

## 4. Accepted risks and open recommendations

| # | Risk | Why accepted | Recommendation |
|---|---|---|---|
| R1 | **Identity-only login.** Users are picked by email (`X-User-Email`), with no passwords. | Local-first design. Ports are bound to localhost. | Before any shared deployment, add real auth (OIDC, or a reverse proxy with SSO) and derive the user from it. |
| R2 | 7 `npm audit` findings (5 high, 2 moderate) remain, all in **Tailwind 3's build-time file watcher** (braces/micromatch ReDoS). | They never ship to the browser and only process our own source files during `npm run build`. | Migrate to Tailwind 4 when convenient. This is a styling-system migration and needs a visual regression pass. |
| R3 | Expensive but valid SQL (cartesian joins, huge `lpad`) can still run until `statement_timeout` (15 s) stops it. | Bounded by the timeout, row cap and container memory limit. | Optionally lower timeouts for the SQL console and AI. |
| R4 | `/sql` error messages echo the first line of the database error. | Users need it to fix their SQL, and it never contains other tenants' data. | Keep. |
| R5 | AI/SQL queries use the app's database login, protected by READ ONLY transactions and the validator. | Defence in depth is already in place. | For stronger isolation, create the `ellementry_reader` role (`scripts/create_readonly_role.sql`) and set `READONLY_DATABASE_URL`. That would have contained SEC-1 at the database layer. |

## 5. Known functional limitations (non-security)
- "By warehouse" on the sales register can group by the warehouse code rather than the name.
- "This month vs previous period" compares with the same number of days just before it.
- See `README.md` §6 for features not yet implemented.

## 6. How to reproduce
```powershell
cd backend;  $env:TODAY_OVERRIDE="2026-10-17"; python -m pytest -q        # 363 tests (needs DB ellementry_analytics_test)
pip install pip-audit; pip-audit -r requirements.txt                        # Python dependencies
cd ..\frontend; npm audit; npx tsc --noEmit; npm run build                  # frontend
cd ..; docker compose up -d --build                                         # container stack
```
