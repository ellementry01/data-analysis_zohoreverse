# Validation Record

Validation performed on 5 October 2026 against the local PostgreSQL 18 installation and an isolated `ellementry_dw` database. No company source exports or customer transaction rows were loaded.

| Check | Result |
|---|---|
| Canonical warehouse SQL build | Passed; all ordered schema SQL files applied. |
| Reviewed warehouse seed load | Passed; rules, mappings, coverage/process context, and lineage loaded. |
| Warehouse schema acceptance SQL | Passed; transactional assertions completed with exit code 0 and rolled back. |
| Warehouse loader/seed Python tests | 36 passed, 19 skipped. Skips require optional database/sample-file fixtures. |
| Empty-data warehouse transform | Passed; run 1 succeeded and created all documented marts on PostgreSQL 18. |
| Portal migration | Passed; app-only schema and nine portal views installed. |
| Least-privilege role checks | Passed; app role reached its app schema and metrics role read warehouse marts. |
| Warehouse API tests | 4 passed against the separate database and real database roles, including every declared report filter. |
| All report contracts | Passed; all 16 allowlisted reports, readiness, and catalog executed against generated marts. |
| Frontend production build | Passed (`tsc -b` and Vite production build). |
| Local application | `/api/health/ready` returned `ready` for `ellementry_dw`; the rebuilt UI returned HTTP 200. |
| Authenticated browser smoke | Temporary reader login, warehouse overview, and sales report rendered successfully. |
| Responsive browser check | 1440px and 390px viewport checks showed no page-level horizontal overflow. |

## Not Yet Verified

- No real ERP, WMS, marketplace, inventory, sales, returns, or purchasing exports were loaded or reconciled.
- Sample-workbook parsing tests were skipped because the source samples are not configured.
- Not every report was manually browsed; all 16 report queries and their filters were exercised through the authenticated API tests.
- Production concurrency, backup restore, TLS, host firewall, performance, and data retention have not been tested.
- PostgreSQL 18 compatibility was checked for the schema build and empty transform; production acceptance still needs to run against the exact target server version.

These are local compatibility checks, not production certification. Review `RELEASE_CHECKLIST.md` before shared deployment or loading business data.
