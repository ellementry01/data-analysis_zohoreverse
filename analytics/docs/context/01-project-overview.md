# 01 — Project overview

## What this is
**Ellementry Analytics** is a local-first, AI-assisted business analytics platform, similar in spirit to Zoho Analytics.

- It imports Excel/CSV files and SQL tables into PostgreSQL.
- It cleans the data, relates tables, and defines governed metrics in a semantic layer.
- It builds dashboards.
- It answers plain-English questions. Every answer is computed from the database and shows the SQL behind it.

The product is **Ellementry Analytics**; the name is used throughout, from the UI to the database, schema, Docker project and environment variables (renamed from an earlier working name on 2026-10-26; see [09-decisions-and-gotchas.md](09-decisions-and-gotchas.md)).

- **Owner:** the user, `ea@ellementry.com`, on a Windows 10 PC. They are building it for their company, Ellementry, a home and kitchen brand.
- **Location:** `C:\Users\Dileep\Desktop\ellementry-analytics\` (renamed from `lumen-analytics`; if it is still called that, the rename is pending and nothing breaks, as all paths inside are relative). Everything for the project is in this one folder: code, warehouse, exports, database backups and archived old folders.
- **Git:** one repository at the folder root, pushed to GitHub `ellementry01/data-analysis_zohoreverse` (public, branch `main`). `exports/` and `reports/` are not in git.

```
ellementry-analytics/   (repo root)
  analytics/   the application
  warehouse/   the ellementry_dw warehouse code (moved here 2026-10-22, see 08)
  research/    the Zoho Analytics study (public pages only), made with the REA tool
  exports/     the company's source exports + MANIFEST.tsv (not in git: customer data)
  reports/     working CSV reports from the warehouse (not in git)
  backups/     dumps of the warehouse (ellementry_dw_*.dump) and the app database (ellementry_analytics_*.dump) (not in git)
  archive/     superseded folders kept for reference: ellementry_source_code, early design docs (not in git)
```

The old project `ellementry_source_code` is superseded: its warehouse code lives in `warehouse/`, and a copy of the old folder (with its git history) is in `archive/`. The live databases run outside the folder (warehouse in PostgreSQL 18 on the host, app database in Docker); `backups/` holds their dumps. `Desktop\quicmonk_reverse\` is a different app (Ellementry Intelligence, GitHub `quickmonk_reverse`), not part of this project. The PostgreSQL 18 database `ellementry_dw` on the host is what Ellementry Analytics reads through a read-only connector. See [08-ellementry-warehouse.md](08-ellementry-warehouse.md).

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
2. **Move to the Desktop.** The project moved to the Desktop (`Desktop\lumen-analytics`, renamed `ellementry-analytics` on 2026-11-04). The user also asked why some features are only partly built; the answer is in `research/FEATURE_MATRIX.md` and README §6.
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
20. **Stock and Fulfilment made COO-ready (2026-11-03).** The user will show these two. Descriptions now appear on dashboards; readable order status; COD vs prepaid RTO; monthly RTO / late trend; Stock filters by location and category; closed stores marked; top products table. Compare no longer shows a change when the previous period starts before the data.
21. **One folder (2026-11-04).** The folder was renamed `ellementry-analytics`; the backups moved into `backups/` (plus fresh dumps of both databases); the old `ellementry_source_code` and the design folders were copied to `archive/` and deleted from the Desktop; new return exports went into `exports/_originals/return_data_2026-11-03/`. The other app that had the name `ellementry-analytics` was renamed; the user later named its folder `Desktop\quicmonk_reverse`. The project folder rename (from `lumen-analytics`) is done by the user after closing the session, because Windows locks a folder a running session uses. (As of 2026-11-07 the folder is `Desktop\ellementry analytics`, with a space; nothing depends on the name.)

22. **Strategy for AI assistants (2026-11-07).** The user asked for a chat on every dashboard with memory that learns their decisions, a global assistant, scheduled domain agents (the earlier "AI Hub" plan's nine agents in `warehouse/docs/*AI Hub*.pdf` and PRD-001), a data watchdog for when pulls are automated, and production-standard software for many employees. Decisions: one assistant engine with scopes, not nine agents; read-only assistants; memory proposed and approved by the user; Claude Haiku/Sonnet only, own tool loop (no LangGraph); company sign-in with Google Workspace; data alerts to the owner, in the app only; ERP moves from smERP to ERP Daddy (API) after Diwali. Written as `docs/AI_ASSISTANTS_PLAN.md`: phases 0-8, each built on its own branch, tested, live-evaluated with the owner's OK, signed off, then merged.
23. **Assistants Phase 0, groundwork (2026-11-07, merged).** Stable dashboard keys and domains (ids still change on rebuilds), conversation scopes, the `ai_usage` cost ledger with daily/monthly spend caps, feature flags, a scripted fake Claude that enforces the rules, and the eval runner.
24. **Phase 1, dashboard chat (2026-11-07, merged).** An Ask panel on every dashboard that knows its description, filters, widgets, metric definitions, data dates and what is on screen (recomputed on the server); questions keep the dashboard's filters; answers show values as ₹ Cr/L and %. Live eval `dashboard_basic`: 78/80, every number right.
25. **Phase 2, multi-step answers (2026-11-07, merged).** A read-only tool loop (run_query, get_widget_data, describe_metric, list_values, get_dashboard_context, get_data_issues), limits per answer, escalation to Sonnet, a number check with one rewrite, live steps in the panel, long-thread summaries. Live eval `dashboard_deep`: 50/50 after fixes (the chat must match the tiles exactly).
26. **Phase 3, sign-in and access (2026-11-07, signed off and merged, NOT switched on).** Google Workspace sign-in, sessions, API tokens for scripts, users and deactivation, access rules on dashboards/domains/datasets for people and the assistant, audit log, Administration page. The owner signed it off before creating the Google OAuth client; the live app runs `AUTH_MODE=dev` until then (07, "Company sign-in").
27. **Phase 4, memory (2026-11-07, signed off and merged).** The dashboard assistants remember: "remember ..." saves at once (with undo); things learned from a quiet conversation become "Remember this?" suggestions the user accepts, edits or rejects; decisions keep their reason and date; team facts need an admin; each answer gets the most relevant memories and the user's profile and cites them ("memory #12"); a memory whose metric changed waits for review. Memory page, background job queue in the app database. 555 tests; live eval `memory`: 7/7 after widening two checker word lists (Rs 6.07).
28. **Phase 5, data issues and "worth a look" (2026-11-07, signed off and merged).** The issue register in the app (37 open issues imported from `warehouse/docs/ISSUE_LOG.md` by `scripts/import_issue_log.py`, then edited on the Data issues page), a note on affected tiles and a "Known data issues" strip on each dashboard, the dashboard assistant names the issue when it quotes an affected number (`get_data_issues` is live), "worth a look" items worked out in code (change on last year, unusual months, record months, missing months, data age) and cached until the data changes, owner notifications, memories naming an issue go to review when it is solved. 572 tests; live eval `issues`: 20/20 after two checker fixes (Rs 7.11, every number right).
29. **Phase 6, global assistant (2026-11-10, signed off and merged).** The Ask page becomes the assistant that knows every dashboard the person may see: a short index card per dashboard (purpose, headline tiles, metrics, open data issues, top "worth a look" lines; about 5,900 characters for the 10 dashboards), `get_dashboard_context` / `get_widget_data(dashboard_key=...)` for detail, memories from every scope (each labelled with where it came from), live steps, "Remember this?" cards; older Ask threads continue; "create a dashboard" still works; admins only like the dashboard chat. 587 tests; live eval `global`: 25/25 after one prompt fix (24/25 on the full run, Rs 18.93; the one miss named the right dashboard but quoted a "worth a look" month instead of reading the tile; re-run after the fix Rs 0.17; every number right, none invented, permissions 100%).
30. **Phase 7, scheduled domain agents (2026-11-10, signed off by the owner and merged).** Rules run in the warehouse after each build (`python dw.py agents run all`, schema 2.16) and write alerts to `insight.alert_event`; the owner chose to start with three rules on PRD-001's proposed thresholds: **stock-out with demand** (STK-A01), **low cover** below 7 days (STK-A02) and **purchase order overdue** (OPS-A02, one per PO, critical after 14 days). First run on the 15 Sep 2026 build: 131 stock-outs, 19 low-cover, 148 overdue POs (113 critical). The app imports the views (`agent_alerts`, `agent_rules`, `agent_runs`) and shows them on a new **Alerts** page (admins): rule cards, Acknowledge / Dismiss with a note (stored in the app and saved as a decision memory; refused on a resolved alert), "Explain" opens the Stock / Operations / Executive assistant on the Ask page, and the **executive briefing** (facts computed in code, worded by Sonnet, numbers checked, on request). New alerts and failed runs are announced once in the bell. 609 app tests + 14 warehouse agent tests; live eval `domain` 2026-11-10 (owner's OK): 20/20 after one fix, every number right, no invented numbers; one live briefing by Sonnet, every number from the facts, Rs 0.96; about Rs 3.43 in all.

## Current status (2026-11-10)
- Docker stack (`ellementry-db-1`, `ellementry-app-1`) serves the app on http://localhost:8000, with Claude enabled. After a PC restart Docker Desktop must be started by hand (see 09); the warehouse PostgreSQL starts by itself.
- **The user is showing the Stock (id 195) and Fulfilment (id 196) dashboards to the COO.** Keep those ids stable (see 09).
- Backend test suite: **609 passed**. Warehouse suite: **85 passed, 7 skipped** (see 07), plus `tests/test_agents.py` **14 passed** on a restored copy. The README and QA_REPORT counts are older (328 and 363).
- **AI assistants** (`docs/AI_ASSISTANTS_PLAN.md`): Phases 0-7 done and merged (sign-in not switched on yet); the running app is built from main. The app has migration 0006 and 37 issues imported; the warehouse is at schema 2.16 with 298 open alerts. In `analytics/.env`: `ASSISTANT_DASHBOARD_CHAT=true`, `ASSISTANT_AGENT_LOOP=true`, `ASSISTANT_MEMORY=true`, `ASSISTANT_DATA_ISSUES=true`, `ASSISTANT_GLOBAL=true`, `ASSISTANT_SCHEDULED=true` (chat, memory, the global assistant and alerts admins only; `BRIEFING_EVERY_DAYS` unset, so the briefing is written on request; issue notes and "worth a look" for every member), daily AI cap Rs 100 per user and Rs 3,000 per month (placeholders until the owner sets a budget). AI spend on 2026-11-07, mostly evals: about Rs 67.
- **Waiting on the owner:** the Google OAuth client for company sign-in (07, "Company sign-in": steps 1-4 are the owner's; then restart, sign in, create an API token for scripts). Hosting with https for access from other devices is not decided yet.
- Only one workspace exists in the Docker app: **34 Ellementry (live warehouse)**, with 32 datasets, 45 metrics, 18 relationships and **10 dashboards** (ids 192–201; Stock 195, Fulfilment 196). Not all are ready for management: see "COO readiness review" in 08.
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
- Dashboard assistants (Phases 0-2): a chat on every dashboard that knows it, multi-step read-only tool answers with live steps, number checks, cost ledger and caps, eval sets with live results.
- Company sign-in and access (Phase 3, built, not yet switched on): Google Workspace OIDC, sessions, API tokens, access rules, audit log, Administration page.

Not built:
- Geo maps, forecasting/AutoML, what-if analysis, scheduled email reports.
- Public sharing/embedding, live-connect (query-in-place), SaaS connectors, alerts, slideshows.
- **Real authentication in the live app.** The code exists (Phase 3) but the live app still runs in dev mode (identity by email header) until the Google client is set up; see [05-security.md](05-security.md).
- The remaining alert rules of PRD-001 (reorder, transfer and liquidate recommendations, transit, returns spike, data freshness...), the data watchdog and production hosting (Phase 8 and the separate tracks in `docs/AI_ASSISTANTS_PLAN.md`). Memory (Phase 4) is done; data issues and "worth a look" (Phase 5) are done; the global assistant (Phase 6) is done; scheduled agents (Phase 7) are done with three rules (signed off 2026-11-10).
