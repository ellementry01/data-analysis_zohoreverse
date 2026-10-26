# Release Checklist

Do not treat local schema and UI checks as production approval. Complete these environment-specific gates before loading real business data or sharing the application.

| Gate | Required verification |
|---|---|
| Database target | Use a backed-up staging database. Confirm the warehouse SQL version and migration history; never run the fresh build over a populated database. |
| Source contracts | Compare each current ERP/WMS/marketplace export to its registered contract and test representative files with dry-run before loading. Confirm report grain, explicit dates, exact headers, identifiers, and row counts. |
| Seed mappings | Have business owners review location, channel, partner, product, status, code, UOM, and document-prefix mappings. Keep the partner-list completeness switch false until formally confirmed. |
| Raw-data protection | Restrict `raw` access to the loader/warehouse administrators. Raw files may contain PII; metrics and app roles must not gain access to raw, staging, or core. |
| Quality/reconciliation | Compare source control totals to loader records and transform ERROR/WARN checks. Verify quantity and financial totals independently before relying on marts. |
| Coverage and dates | Validate the configured prototype period, snapshot dates, source timezone, per-process monthly coverage, and incompleteness disclosures. Do not infer historical stock from current snapshots. |
| Roles | Test that the app role can access only `app`, and the read-only metrics role can SELECT marts but cannot write or read `raw`, `stg`, `core`, `meta`, or `app`. |
| Concurrency | Exercise simultaneous file loads, transforms, sessions, and account deactivation on the actual PostgreSQL server. |
| Backup restore | Create an off-host backup and restore it into a new isolated database. Compare table counts, schema migrations, and important business totals. |
| Shared access | For anything beyond loopback use, require HTTPS, secure cookies, exact origins/hosts, firewall review, account lifecycle, session revocation, and approved backup retention. |
| Dependencies | Scan pinned Python and frontend dependencies; patch advisories and rerun the schema, loader, API, and browser acceptance suites. |
| UI acceptance | Check all report filters, 500-row cap behavior, exports, responsive widths, empty/no-data states, and role-specific navigation on supported browsers. |
| Performance | Measure representative load, transform, and report times with realistic source volumes. Current 10-second query and 500-row display bounds are prototype safeguards, not performance guarantees. |

## Current Scope

- App reports read warehouse marts and portal metadata views only.
- File loading and transformations use the schema package's CLI and contracts; the UI is not a file ingestion interface.
- Reports return at most 500 rows; pagination is not implemented.
- The warehouse has a fixed prototype reporting period controlled by `meta.pipeline_setting`.
- No in-app forecasting agent, replenishment automation, scheduled connector, external alert delivery, or purchasing execution is included.
- The app and schema build were locally validated on PostgreSQL 18, but actual company files and production workloads have not been evaluated.
