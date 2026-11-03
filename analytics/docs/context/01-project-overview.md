# 01 — Project overview

## What this is
**Ellementry Analytics** is a local-first, AI-assisted business analytics platform, similar in spirit to Zoho Analytics.

- It imports Excel/CSV files and SQL tables into PostgreSQL.
- It cleans the data, relates tables, and defines governed metrics in a semantic layer.
- It builds dashboards.
- It answers plain-English questions. Every answer is computed from the database and shows the SQL behind it.

The product is **Ellementry Analytics**; the name is used throughout, from the UI to the database, schema, Docker project and environment variables (renamed from an earlier working name on 2026-10-26; see [09-decisions-and-gotchas.md](09-decisions-and-gotchas.md)).

- **Owner:** the user, `ea@ellementry.com`, on a Windows 10 PC. They are building it for their company, Ellementry, a home and kitchen brand.
- **Location:** `C:\Users\Dileep\Desktop\lumen-analytics\` (the folder name is old; the user may rename it later; nothing inside uses it).
- **Git:** one repository at the folder root, pushed to GitHub `ellementry01/data-analysis_zohoreverse` (public, branch `main`). `exports/` and `reports/` are not in git.

```
lumen-analytics/   (repo root)
  analytics/   the application
  warehouse/   the ellementry_dw warehouse code (moved here 2026-10-22, see 08)
  research/    the Zoho Analytics study (public pages only), made with the REA tool
  exports/     the company's source exports + MANIFEST.tsv (not in git: customer data)
  reports/     working CSV reports from the warehouse (not in git)
```

The old project `C:\Users\Dileep\Desktop\ellementry_source_code\` is superseded: its warehouse code now lives in `warehouse/`. The PostgreSQL 18 database `ellementry_dw` on the host is what Ellementry Analytics reads through a read-only connector. See [08-ellementry-warehouse.md](08-ellementry-warehouse.md).

## Origin: the master prompt
The user pasted a "master prompt" asking for the following:
1. Study Zoho Analytics with the REA reverse-engineering tool, using **public docs only**.
2. Build a functional AI analytics platform with:
   - a React/TS/Vite/Tailwind frontend and a FastAPI/SQLAlchemy/PostgreSQL backend
   - Excel/CSV import, SQL connectors, cleaning, relationships and a semantic layer
   - dashboards and NL→safe SQL
   - demo data validated against independently computed ground truth
   - tests, Docker, and a Windows README

The prompt sets these rules. They still apply:
- Do not bypass authentication, entitlements or rate limits. Do not extract proprietary code, internal APIs or credentials.
- **Never request passwords or authentication codes in chat.** The user does any authentication themselves.
- Keep all credentials in environment variables. Never hardcode secrets.
- **Do not sacrifice security in the AI query system.** That means read-only permissions, SQL validation, scoped access, timeouts and resource limits.
- Do not copy proprietary code, branding or visual assets.
- **Do not claim unsupported features are implemented.**

The research output is in `research/`: `DISCOVERY.md`, `FEATURE_MATRIX.md` (each feature with its built status), the captured help pages and the REA JSON.

## Timeline (October – November 2026)
1. **Research and build.** REA study of Zoho's public site, followed by the full build: backend, frontend, demo data with ground truth, and tests.
2. **Move to the Desktop.** The project moved to the Desktop (today `Desktop\lumen-analytics`). The user also asked why some features are only partly built; the answer is in `research/FEATURE_MATRIX.md` and README §6.
3. **Docker and QA.** Dockerised with a hardened compose file, followed by a senior-QA security and quality audit. The findings and fixes are in `QA_REPORT.md`; the critical one was SEC-1, a cross-workspace leak through CTE shadowing, now fixed.
4. **Connected the Ellementry warehouse.** Connected `ellementry_dw` (schema `mart`) through a read-only connector. This created workspace **34, "Ellementry (live warehouse)"**: 19 datasets, 11 relationships, 11 metrics and hourly sync.
5. **Rebrand and demo removal.** Rebranded to Ellementry in the UI and docs, and deleted the **demo workspace in the app**. The bundled demo generator and the "Load demo workspace" button still exist.
6. **Claude for Ask AI (Anthropic).** Claude replaced the generic LLM path, with routing: **Haiku 5.5** for simple questions and **Sonnet 5.5** for genuinely complex ones. **Opus and Fable are never used.** See [04-ai-layer.md](04-ai-layer.md).
7. **Live check (2026-10-21).** The user put their Anthropic key in `analytics/.env`. A live check of simple and complex questions passed. Two accuracy fixes came out of it: computed facts for the narrative, and a counting rule in the prompt.
8. **These context docs written** (2026-10-21).
9. **Executive-dashboard plan and warehouse review (2026-10-21).** Written to `docs/EXECUTIVE_DASHBOARD_PLAN.md`, `docs/WAREHOUSE_SCHEMA_REVIEW.md` and `docs/WAREHOUSE_LOAD_FIX_PLAN.md`. The user's goal is dashboards and reports of all company data for senior management, viewed on the office network. Multi-agent AI isn't needed.
10. **Warehouse 2.3 and the first full data load (2026-10-21/22).**
    - The warehouse moved into `warehouse/` next to `analytics/` (git).
    - Fixes and additions: PO Document Remark plus a per-PO staging fix; shipments from WMS dispatch; a Blinkit/Instamart normaliser; executive mart views; evidence-based location mappings.
    - Load: all 1.5 years of exports went in, and **28 of 28 file-vs-warehouse checks agree**.
    - App: workspace 34 is synced, with 5 new datasets, 23 metrics and 18 relationships. Connector sync now adds columns that appear in a source view.
11. **Executive dashboards and schema 2.4 (2026-10-22).** Six dashboards built by script; supply, fulfilment and stock fixes.
12. **Name cleanup and GitHub (2026-10-26).** The old working name was removed everywhere (see 09). The whole folder became one git repo, pushed to `ellementry01/data-analysis_zohoreverse`, with a root README.
13. **Schemas 2.5–2.7 (2026-10-26).** WMS shipments link to ERP bills; bill numbers keyed by financial year; exact SKU quantities on multi-SKU dispatch rows.
14. **Business answers (2026-10-27), schemas 2.8–2.10.** Stock valued at cost; higher MRP wins; category from the ERP item master; Ellementry International = B2C export; goods receipts arrive at Bagru (BR-032); BR-031 confirmed.
15. **Stock history (2026-10-30), schemas 2.11–2.12.** 19 month-end stock reports loaded; month-by-month stock check; issue log with Solved / Unsolved sheets (`warehouse/docs/ISSUE_LOG.md`).
16. **Instamart and four new dashboards (2026-11-02), schema 2.13.** BR-034 (six Instamart billing accounts); Discontinued & slow stock, Days of cover, Instamart and Data health dashboards; Amazon FBA return reasons.
17. **ERP report downloads (2026-11-02), schema 2.14.** The user logged into the ERP in the built-in browser; the MRN (goods-receipt) register was loaded, and the Document Wise Stock Movement report explained 80% of Bagru's unexplained stock.
18. **Store status sheet (2026-11-02), schema 2.15.** The business sent the list of all stores (own / franchise / SIS, running / closed): franchise and Shoppers Stop accounts classified as sale-or-return partners; own-store status applied.
19. **COO readiness review (2026-11-03).** All 10 dashboards checked on live data: six can be shown, three need app-side fixes first (segment labels, partner stock in days of cover, return rate), Data health is for the team. Fixes deferred by the user; details in 08.

## Current status (2026-11-03)
- Docker stack (`ellementry-db-1`, `ellementry-app-1`) is running and healthy on http://localhost:8000, with Claude enabled.
- Backend test suite: **406 passed**. Warehouse suite: **85 passed, 7 skipped** (see 07). The README and QA_REPORT counts are older (328 and 363).
- Only one workspace exists in the Docker app: **34 Ellementry (live warehouse)**, with 29 datasets, 45 metrics, 18 relationships and **10 dashboards** (ids 172–181). Not all are ready for management: see "COO readiness review" in 08.
- The warehouse (`ellementry_dw`, **schema 2.15**) holds **real data for 1 Apr 2025 – 15 Sep 2026**: sales, returns, transfers, POs, goods receipts, shipments, Instamart sell-out, Amazon return reasons, and stock for **19 days** (31 Mar 2025, every month-end to 31 Aug 2026, and 15 Sep 2026). `reconcile.py` agrees on **28 of 28** checks.
- Issue log: **90 solved, 37 unsolved** (`warehouse/docs/ISSUE_LOG.md`). Open business inputs are summarised at the end of 08.

## What is built and what isn't
Built:
- Workspaces with admin/editor/viewer roles.
- File import with header detection and type inference.
- Database connectors with schedules.
- Data grid, profiling, quality checks, prep recipes, calculated columns, relationships, query tables and a SQL console.
- Semantic layer: metrics, glossary, rules; semi-additive and composite metrics.
- Report builder with 14 chart types, plus dashboards with filters and drill-down.
- Ask AI: offline parser plus Claude, with insights, lineage and query history.

Not built:
- Geo maps, forecasting/AutoML, what-if analysis, scheduled email reports.
- Public sharing/embedding, live-connect (query-in-place), SaaS connectors, alerts, slideshows.
- **Real authentication.** Identity is chosen by email header with no passwords; see [05-security.md](05-security.md).
