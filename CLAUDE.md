# ellementry-analytics workspace

- `analytics/` holds the **Ellementry Analytics** application. Start with [analytics/CLAUDE.md](analytics/CLAUDE.md), then read `analytics/docs/context/01…09`.
- `warehouse/` holds the **ellementry_dw** data warehouse (its own git repo). Read [warehouse/README.md](warehouse/README.md) and `analytics/docs/context/08-ellementry-warehouse.md`.
- `exports/` holds the company's source exports, with `MANIFEST.tsv`. **It contains customer data: never commit it, upload it or print personal fields.**
- `research/` holds the Zoho Analytics public-docs study (REA): `DISCOVERY.md` and `FEATURE_MATRIX.md`.

The old project `C:\Users\Dileep\Desktop\ellementry_source_code\` is superseded. Its warehouse code now lives in `warehouse/`.
