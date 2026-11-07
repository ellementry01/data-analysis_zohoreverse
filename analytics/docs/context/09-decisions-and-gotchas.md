# 09 — Decisions, gotchas, known issues and next steps

## Decision log
| Decision | Why |
|---|---|
| Old working name removed everywhere (2026-10-26): compose project `ellementry`, image `ellementry-analytics`, schema `ellementry_meta`, DB `ellementry_analytics`, `ELLEMENTRY_*` env vars (`ELLEMENTRY_CONN_*`, `ELLEMENTRY_SECRET_KEY`), app folder `analytics/`, container user `ellementry`. Done with backups first, then the schema, database and role renamed in place and the Docker volumes copied, so no data was lost | The user asked for the old name to be removed from everywhere |
| Deleted only the **demo workspace in the app**; kept the generator, `/api/demo` and the button | This was the user's choice, from an explicit question. Tests depend on the demo |
| Claude routes **Haiku 5.5 (simple) / Sonnet 5.5 (complex)**; never Opus or Fable; no server-side fallbacks; model allow-list checked at startup | The user's explicit instruction |
| Routing is deterministic regex/heuristics in code, not an LLM classifier | It's free, instant and testable, and the routing reasons are visible in the UI |
| Claude returns a **QuerySpec first**, with SQL only as a fallback | Governed metrics and business rules then apply automatically, and the arithmetic stays in the engine |
| Narrative arithmetic is done in code (`_facts`), never by the model | In the live check the model miscounted (75 vs 76) |
| An explicit counting rule is in the prompt | Sonnet once counted distinct names (7) instead of rows (12) |
| Connector passwords are referenced by env var **name** (`ELLEMENTRY_CONN_*` only) | Secrets never pass through the API, the database or chat, and the prefix stops a connector from reading arbitrary server secrets |
| Connector imports keep the source column types | Empty views would otherwise import as all-text |
| Ports are bound to 127.0.0.1; identity-only auth | It's a local-first tool; real auth is a prerequisite for sharing (R1) |
| The warehouse lives in `warehouse/` (moved 2026-10-22, history kept) and the exports in `exports/` (outside git), both at the repo root | One place for the whole product; the exports hold customer data |
| Platform workbooks are normalised into the contract layout rather than loosening the contracts | Contracts stay strict; every change the normaliser makes is logged, personal data and payout columns are never written |
| Mappings added from data evidence are `is_confirmed = false` with the evidence in the note | Same rule as the original reviewed seeds: nothing is assumed confirmed until the business says so |
| PO Document Remark is stored but decides nothing until BR-031 is confirmed (`po_document_remark_confirmed`) | A PROPOSED rule is never treated as confirmed (PRD convention) |
| Executive dashboards are built by a script (`scripts/build_executive_dashboards.py`), not by hand | Rebuildable after any data or metric change, and every widget is checked for data on each build |
| KPI cards and tables colour a change by the metric's `higher_is_better` (the query engine now passes it on each measure column) | A rising return or RTO rate was shown green |
| Warehouse 2.4 fixes data-side problems in the warehouse, not in app calculated columns (courier groups, transit status, MRP status, tracked channels) | One definition for dashboards, Ask AI and any later report; the app only filters on the new columns |
| RTO rate and delivery time are measured only on channels that report them (`is_rto_tracked`, `is_delivery_tracked`, derived from the data each build) | Marketplace RTO never reaches the WMS and Nykaa/FNP/Flipkart send no delivery dates: an all-channel rate showed 4.3% instead of the website's 7.9% |
| Items with no MRP in any source are left out of stock value and counted on their own tile, never valued at 0 silently | 14,474 trading units (mostly discontinued) have no MRP anywhere |
| The ERP item master only fills gaps; it never overrides the Final Master, stock report or invoices | It is the least curated source, but it had a category for almost every product that lacked one |
| Raw exports are kept twice: canonical copies listed in `MANIFEST.tsv`, and every distinct original as received in `exports/_originals/` (`ORIGINALS.tsv` holds their sha256) | The user asked for the original files to be kept; renamed canonical copies alone lose the received names and the superseded re-exports |
| A sales bill is identified by its number and financial year (2.6) | The ERP restarts bill numbers every April; keying by number alone dropped FY 25-26 bills, and the reconciliation shared the same key so it could not see it. Lesson: a check must not reuse the logic it checks |
| WMS shipments link to ERP bills by Extern Order No, then AWB (2.5) | The WMS Invoice No of marketplace orders is the marketplace's own invoice |
| Stock is valued at cost, not MRP (business, 2026-10-27); where MRPs disagree the higher one is current; category from the ERP item master only | Business rules: the company values stock at cost; prices were raised, so the lower MRP is old stock's label |
| The stock report of the day before the period (31 Mar 2025) is kept as opening stock (BR-033); month-end reports are stock history; a month-by-month movement check replaces the single implied-opening check | With saved stock days, gaps can be dated to a month instead of guessed over the whole period |
| Slow stock is judged by days since the SKU last sold anywhere (all channels), not at the location holding it | A product selling in the website or B2B channel is not dead stock just because one store holds a unit |
| Return reasons come from Amazon's FBA customer-returns report only; the Shopify returns export is not loaded | The ERP records no reasons; the Shopify export says "other-reason" on every row |
| Insights skip a measure whose values are not numbers (e.g. MAX of a date) | A "latest as-of date" column crashed the dashboard insights (TypeError) |
| BR-031 confirmed (2026-10-27): the PO remark "Purchase" vs "Return" decides purchase vs return-inward; all goods receipts arrive at Bagru (BR-032) | Business answers; they replaced a proposed rule and an unknown receiving location |
| The six Instamart billing accounts are one quick-commerce partner with pooled stock (BR-034) | The business confirmed the list; Instamart's facilities can't be told apart in our invoices |
| Instamart rows pasted one column left are dropped only when the same order exists correctly elsewhere; otherwise the normaliser refuses the file | July 2025 showed 59,550 units instead of 310; a silent drop could hide real orders |
| Goods receipts come from the ERP MRN Register when it is loaded (2.14); the Pending PO export's receipts are used only without it | The register has every GRN with its own date, including closed POs the Pending PO export drops; the memo-repeated item rows are kept once |
| Franchise and SIS partners come from the business's store status sheet (BR-035): one partner stock location per franchise account, Shoppers Stop pooled (one billing account for 14 counters); return-PO receipts from partners are not taken off partner stock until D-089 is answered | The sheet's franchise names match the ERP billing names exactly; subtracting both return routes could count the same goods twice |
| The COO-readiness fixes (segment labels, partner stock out of days of cover, retail-only return rate) were found on 2026-11-03 and deliberately left for later | The user said "Not now"; see the review in 08 |
| Compare is left empty when the previous period starts before the data (tiles say "Not compared: data starts …") | 15 Sep 2025 - 15 Sep 2026 vs "previous period" set 12 months against the 5½ months of data before it and showed +94% orders. The data start is the earliest date of the dataset(s) the date range filters on (`analytics._data_start`) |
| Dashboard descriptions are shown on the dashboard (under the title, and in the PDF) | Caveats such as "RTO is website-only" were only in the API; a COO reading the screen never saw them |
| Dashboard values filters use shared lookup fields (`locations.*`, `products.*`) when widgets come from several datasets | A filter on a field of one dataset is applied to every widget and gave wrong month-end figures on the other dataset |
| Focus on Instamart; Blinkit kept but parked; Zepto later | The business's priority; Blinkit has a new seller arrangement, so the old data is set aside |
| AI assistants plan (2026-11-07, `docs/AI_ASSISTANTS_PLAN.md`): one assistant engine with scopes (dashboard / domain / global) instead of nine separate agents; read-only tools; memory proposed and approved by the user; our own tool loop on the Anthropic SDK (no LangGraph); built in phases 0–8, each tested and signed off before the next | The user wants a chat per dashboard with memory, a global assistant, and production software for many employees; the earlier AI Hub plan's nine agents become scopes and scheduled jobs of one engine, and domains are added only when their data exists |
| Assistants Phase 0 (2026-11-07): dashboards have a stable `key` and a `domain`; threads carry a scope; every Claude call is written to `ai_usage` with a rupee estimate, and per-user daily / company monthly caps switch to the offline engine; feature flags gate each phase | Threads and memories must survive dashboard rebuilds (ids change), costs must be visible before many employees use AI, and each phase ships switched off until its gate is signed off |
| Eval expected values are computed at run time (SQL or QuerySpec through the app's own guarded endpoints), and live eval runs need `EVAL_LIVE_OK=1` | Hand-typed answers go stale as data changes; live runs cost money |
| Everything in one folder `Desktop\ellementry-analytics` (2026-11-04): backups and archived old folders inside it, both git-ignored; the live databases stay where their servers run them | The user asked for all info, code, warehouse and database in one folder and the unrelated folders gone; moving PostgreSQL's data directory was judged too risky, so the folder holds verified dumps instead |
| Whole folder is one git repo pushed to `ellementry01/data-analysis_zohoreverse` (public, by the user's choice); `exports/` and `reports/` stay out | One place for the product; customer data is never committed |
| ERP reports are downloaded only by the agent in the built-in browser, in the user's own signed-in session; nothing in the ERP is changed | The user authorised downloads only |
| The project moved off the scratch workspace to the Desktop | The scratch path was a redirected AppData folder that broke mkdir, Alembic, npm/esbuild and Vite |

## Gotchas
- **`.env` changes need `docker compose up -d --force-recreate app`.** A plain `up -d` or `restart` may not reload them. This has bitten twice: once for the ELLEMENTRY_CONN password and once for the Anthropic key.
- After changing code, rebuild with `docker compose up -d --build`. The UI is baked into the image.
- `pip` on PATH belongs to another interpreter; use `python -m pip`.
- Shell heredocs once mangled `\b` into backspace characters. Use the Edit/Write tools for code changes.
- Importing `claude` from `config` causes a circular import. That is why `check_model` lives in `config.py`.
- Tests import with `from conftest import …`.
- Prompt caches are per model, so the first Sonnet question pays its own cache write.
- The README and QA_REPORT test counts (328 and 363) are stale; the current count is **407**.
- The README "Quick start" still mentions "Load demo workspace". The button still works.
- **Port 8000 can be taken** by another app (a uvicorn from another project once held it). Start the stack with `APP_PORT=8001` temporarily, or stop the other app.
- **Migration numbers can clash with another session's.** Check `warehouse/sql/` and `meta.schema_version` before naming one; the next free number is 240 (schema 2.16).
- **New `source_table` or `source_system` values hit CHECK constraints** (`fact_stock_movement_source_table_check`, the source_system check). The migration must drop and re-add the constraint.
- **A new mart view used by a DQ check must exist before step 50**; the stock check view lives in `45_stock_check.sql` for that reason.
- **The test database `dw_test_po` must get every new migration too**; otherwise the transform tests fail at setup (see 07).
- **Metric expressions can't use `AND`**; use a nested CASE. **Sorting by a dimension field** needs an alias.
- **ERP (Expand smERP) reports:** widen the browser to 1400×900 first (the size resets every turn). With Consolidated ticked the channel list doesn't open. See 07 for the download steps and the reports that fail inside the ERP.

- **After a hard shutdown**, the app's PostgreSQL container runs a long crash-recovery sync (about 10 minutes). The app can exit first; once the db is healthy, run `docker compose restart app`.
- **After a reboot `Get-Service postgresql-x64-18` can say Stopped while the warehouse runs** (port 5432 answers). Check with `python dw.py psql -c "select 1"`; starting the service needs administrator rights.
- **Docker Desktop doesn't start by itself after a reboot.** Launch `%LOCALAPPDATA%/Programs/DockerDesktop/Docker Desktop.exe`.
- **Warehouse commands go through `python dw.py …`** from `warehouse/`, so the admin login never appears in a command line. Tests: `DW_DATABASE=<disposable db> python dw.py pytest`; the script refuses `ellementry_dw`.
- **Windows Python writes CRLF line endings** unless told otherwise. The generators now write LF. Check `git diff --stat` for whole-file diffs.
- **Relative dates in the app are measured from today, but the warehouse period ends on 15 Sep 2026.** "Last 30 days" is empty until the as-of anchor (dashboard plan, item A2) is built or the period is moved.
- **New partner types reach the app's calculated columns silently.** `sales_segment` and `location_group` are CASE expressions in the app; a new `partner_type` or `location_type` in the warehouse falls into their ELSE branch (2.15's franchise / SIS went to "B2B - other"). Check them after every warehouse release that adds a type.
- **Warehouse tests can be stale, not the data.** In 2.15 two failed only because a test used Shoppers Stop as its "unlisted" example and another still joined shipments on the WMS invoice number (shipments link by `sales_bill_number` since 2.5). Read the assertion before changing data.
- **Checking numbers through the app:** `POST /api/workspaces/34/query` takes a QuerySpec (dimensions, measures, filters, sort, limit); sorting needs an alias. Dataset names in `GET /datasets` are display names ("Net sales daily"), while fields use the table name (`net_sales_daily.x`).
- **A dashboard values filter applies to every widget.** Pick a field every widget's dataset can reach (a shared lookup such as `locations.location_name` or `products.category`), and check each widget with the filter set; a field from one fact dataset silently distorts widgets on another.
- **Measure and dimension `label`s override column headers** in widget specs; use them rather than renaming metrics.
- **Keep the Stock (195) and Fulfilment (196) ids stable:** the user shares these with the COO. After changing their definitions in `build_executive_dashboards.py`, run `python scripts/update_dashboard_widgets.py Stock Fulfilment` (updates in place). A full `build_executive_dashboards.py` run deletes and recreates all ten, so tell the user the new ids if you must run it.
- **Dashboard ids change on every rebuild** (`build_executive_dashboards.py` replaces by key, else name). Don't hard-code them; use the dashboard's **key** (`DASHBOARD_META` in that script: `stock`, `fulfilment`, `days-of-cover`, …), which never changes. A new dashboard in the script needs a `DASHBOARD_META` entry. `update_dashboard_widgets.py --meta-only --all` sets keys and domains without touching widgets.
- **New Claude-calling code must run inside `ai_usage.ai_context(...)`** (user, workspace, conversation, purpose), or its ledger rows are booked to "system".

## Known functional limitations
- "By warehouse" on a sales register can group by the warehouse code instead of the name. This is a demo-data quirk.
- "Previous period" compares with the same number of days immediately before the range (whole months shift by months), not the same days of the previous month. Ranges whose previous period starts before 1 Apr 2025 get no comparison (see the decision log).
- Compare changes KPI tiles (arrow and %), adds "(previous)" bars to single-level bar charts and columns to tables; stacked two-level charts ignore it.
- The offline engine understands only semantic-layer vocabulary. Open-ended phrasing needs Claude.
- Scheduled refresh applies to connectors only; files are refreshed by Replace or Append.
- Excel, PNG and PDF exports run client-side (PDF via print).

## Sensible next steps (none in progress; ask the user before starting)
Done since 2026-10-22: real facts loaded, stock history (month-ends), ten dashboards, store status sheet (2.15).
- **AI assistants:** Phase 0 (Groundwork) of `docs/AI_ASSISTANTS_PLAN.md` is built (2026-11-07) and awaits the owner's sign-off; Phase 1 (dashboard chat) is next when the user says go. A data-watchdog plan and a production-foundation plan run alongside it and are not written yet.
0. **Make the other dashboards COO-ready** (when the user asks). Stock and Fulfilment are done (2026-11-03) and are what the user shows the COO; the remaining work is the three fixes listed under "COO readiness review" in 08 (Executive overview / Sales & channels, Days of cover, Returns). Then also normalise the Instamart city case and explain Bagru's May 2025 drop (16,677 units with no document).
1. Load the rest of Bagru's stock movements (scrap, adjustments, inventory transfers, subcontract) by running the ERP Document Wise Stock Movement *Summary* month by month (18 downloads), or the Purchase Register once the ERP login has a department (D-124).
2. Get the business's answers to the open confirmations in `warehouse/docs/ISSUE_LOG.md` (locations, courier codes, partner list, negative stock) and apply them through seeds.
3. Start the daily stock save (D-004) and the Instamart daily inventory download (D-125) into `exports/_inbox/`.
4. Build the "as of" anchor for relative dates (dashboard plan A2), so "last 30 days" works against 15 Sep 2026.
5. Add glossary terms for Ellementry vocabulary (channel and location names) to help Ask AI.
6. Configure `READONLY_DATABASE_URL` with `scripts/create_readonly_role.sql` (R5).
7. Add real authentication (OIDC or an SSO proxy) before any shared or network deployment (R1).
8. Migrate to Tailwind 4 to clear the build-time npm audit findings (R2).
9. Refresh the test counts in the README and QA_REPORT.
