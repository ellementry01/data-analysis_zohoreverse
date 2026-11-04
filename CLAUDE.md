# ellementry-analytics workspace

Everything for this project lives in this one folder, `C:\Users\Dileep\Desktop\ellementry-analytics\` (one git repo, GitHub `ellementry01/data-analysis_zohoreverse`).

- `analytics/` holds the **Ellementry Analytics** application. Start with [analytics/CLAUDE.md](analytics/CLAUDE.md), then read `analytics/docs/context/01…09`.
- `warehouse/` holds the **ellementry_dw** data warehouse code. Read [warehouse/README.md](warehouse/README.md) and `analytics/docs/context/08-ellementry-warehouse.md`.
- `exports/` holds the company's source exports, with `MANIFEST.tsv` (originals as received in `exports/_originals/`, listed with sha256 in `ORIGINALS.tsv`). **It contains customer data: never commit it, upload it or print personal fields.**
- `backups/` holds database dumps: `ellementry_dw_<date>.dump` (warehouse, made by `python dw.py backup`) and `ellementry_analytics_<date>.dump` (the app's own database in Docker). Not in git.
- `archive/` holds the superseded folders kept for reference: the old project `ellementry_source_code` (with its git history, without its virtualenv) and the early design folders (`ellementry`, `ai data analysis`, `ellementry data schema`). Not in git; nothing in it is used by the code.
- `research/` holds the Zoho Analytics public-docs study (REA): `DISCOVERY.md` and `FEATURE_MATRIX.md`.
- `reports/` holds working CSV reports from the warehouse. Not in git.

The live databases run outside the folder: the warehouse in PostgreSQL 18 on this PC (`C:\Program Files\PostgreSQL\18\data`), the app's database in Docker volume `ellementry_pgdata`. The folder holds their backups.

`C:\Users\Dileep\Desktop\ellementry-intelligence\` is a **different** app (Ellementry Intelligence, GitHub `quickmonk_reverse`); it is not part of this project.
