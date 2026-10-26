# Executive dashboards & reports — gap analysis and plan

> **Status 2026-10-22:**
> - **Done:** the six dashboards (Executive overview + D1–D9 grouped into Sales, Returns, Stock, Fulfilment, Purchasing & transfers) are built on real data in workspace 34. See `context/08` for the details.
> - **Not done:** the "as of" date anchor, financial-year grains, viewer logins and trust labels per tile (Phases 1 and 3 of the prototype plan).

*Written 2026-10-21. It compares the old project's documents with Ellementry Analytics. No code was changed.*

**Sources read** (in `C:\Users\Dileep\Desktop\ellementry_source_code\docs\`):
- PRD-001 AI Hub Prototype
- Data Context & Business Rules Register
- Target Data Model v2
- Our Data Foundation
- AI Hub Architecture
- How the Schema Works
- ARCHITECTURE.md, VALIDATION.md, RELEASE_CHECKLIST.md
- Data Issues and Doubts Log (2026-10-15)
- Reference Mappings v1.2
- the warehouse mart SQL

**Use case** (from the user): dashboards and reports covering all of the company's data, for senior management. They will view them **from other computers on the office network**. Multi-agent AI isn't needed.

## Verdict
The foundation is right, but managers can't use it yet. Four things are missing:
- **company data** in the warehouse
- **real logins**
- **the executive dashboards themselves**
- **trust features** on each tile, so a viewer can tell a real zero from missing data

None of this needs a redesign.

## What the old documents say is needed
The register states the primary output plainly: "executive dashboards and BI reporting, then agents on top".

- **Executive view.** Net sales excluding GST by channel, orders, average order value, stock value and cover, top and bottom products, and return rate, all compared with last week and last year.
- **Nine dashboards (PRD D1–D9):**
  - D1 Stock overview
  - D2 Cover
  - D3 Discontinued and slow stock
  - D4 Transfers
  - D5 Purchasing and suppliers
  - D6 Returns
  - D7 Fulfilment
  - D8 Data health
  - D9 Sales validation, i.e. reconciliation against the team's Excel
- **Trust rules:**
  - FR-DSH-01: every tile shows its "data as of" date.
  - FR-DSH-02: missing data shows "no data yet" with the gap ID, never 0.
  - FR-DSH-03: partner and employee stock is labelled "movements since 1 Apr 2025, no opening balance".
  - FR-DSH-04: related-party exports and unclassified partners appear on their own lines.
- **A weekly executive report.**
- **Named logins with roles.** These include a read-only "management viewer". Passwords are stored hashed, and every decision records the account.

## What already fits
- **Read-only warehouse access.** The app reads only the approved `mart` views, through the `ellementry_metrics` role. The business rules (GST excluded, invoices minus returns, each location counted once) stay defined in the warehouse, and the app doesn't redefine them.
- **Dashboards.** Drag-and-drop layout, KPI cards compared with the previous period or last year, global filters, drill-down, 14 chart types, CSV/Excel/PNG export, PDF via print, and lakh/crore formatting.
- **Report builder and SQL console** for analysts.
- **Ask AI** with governed answers that show their SQL (Claude Haiku 5.5 / Sonnet 5.5).
- **Workspace roles:** admin, editor and viewer.
- **Hourly sync** of all 19 warehouse views into workspace 34.

## Gaps, in priority order

### A. Blockers: managers would see empty dashboards
1. **No company data in the warehouse.**
   - The sales, stock, returns, PO and transfer facts are all empty, and `ellementry_data/data` is empty.
   - Work happens in the warehouse project: load the full 1.5-year export (open issue D-002) and run the transform.
   - Business dependencies:
     - save the stock report every day (D-004), because past days can't be re-exported
     - the partner list (D-019); about ₹204 lakh stays "unclassified" without it
     - the factory list (D-044)
2. **Relative dates are measured from today, but the data ends 15 Sep 2026.**
   - "Last 30 days" and similar presets would be empty.
   - The app needs an "as of" anchor that can be the latest successful warehouse build (`meta.transform_run.period_end`). *Small app change.*
3. **No real logins.**
   - Anyone on the network could pick any email and act as admin.
   - Needed:
     - named accounts with hashed passwords and sessions
     - a **management viewer** role: dashboards only, with no SQL console, imports or settings
     - an audit log of views and exports
   - The old portal's design (Argon2, CSRF, rate limits) can be reused. *App change.*

### B. Needed before managers rely on the numbers
4. **Trust labels on every tile.**
   - "Data as of" on each widget.
   - "No data yet" plus the gap ID when the month has no coverage (`v_data_coverage`).
   - The stock basis (snapshot or ledger) on stock tiles.
   - *App change.*
5. **Missing warehouse views.** All of these are *warehouse project* work:
   - order count and average order value (the sales view has invoice lines, not orders)
   - quick-commerce sell-out
   - daily stock history
   - network stock
   - transfer transit history
   - fulfilment, once the WMS dispatch file arrives

   Once each view exists, the app picks it up with a connector import.
6. **Indian financial year.** Add April-start financial-year and quarter grains; the warehouse already supplies `fiscal_year_label` and `fiscal_month`. *Small app change.*
7. **Build the dashboards.** This is configuration, not code:
   - an Executive overview, plus D1–D9
   - metrics for orders, AOV, stock value (units × MRP), return rate by channel, and cover
   - glossary terms such as Bagru, FBA, SIS and quick commerce
8. **Sync on build.** Today every view is re-copied each hour, while the warehouse is rebuilt by hand. Sync when a new successful `transform_run` appears instead. *Small app change.*

### C. Office-network deployment
9. **Network exposure.**
   - Publish the app on the PC's LAN address instead of `127.0.0.1`. The database stays local-only.
   - Serve it over HTTPS with a certificate the office PCs trust.
   - Add a Windows firewall rule for the app port only.
   - Restrict it to an exact list of allowed hostnames.
10. **Operations.**
    - The host PC must be always on.
    - The Docker stack must start at boot.
    - Take a daily backup of the app database and of `ellementry_dw`.

### D. Later or optional
11. **Weekly executive report by email.** This needs server-side PDF generation and a schedule.
12. **Phone layout for dashboards.** Not checked yet.
13. **Marketing, finance and Amazon/Shopify data.** Add these through the warehouse, not app uploads, so there's one source of truth.
14. **Stock AI and Operations AI recommendations and alerts.** Intentionally out of scope.

## Order of work
1. **Data, in the warehouse project and with the business.**
   - Understand the full schema and what data exists and what's missing. *In progress; see `WAREHOUSE_SCHEMA_REVIEW.md`.*
   - Load the full export and start the daily stock saves.
   - Get the partner and factory lists.
   - Add the missing mart views.
2. **App, which can run in parallel.** Logins and the viewer role, the as-of date anchor, trust labels, financial-year grains, and sync-on-build.
3. **Office-network deployment.** HTTPS, firewall, auto-start, backups.
4. **Build the dashboards.** The Executive overview plus D1–D9. Then a reconciliation session: two business users confirm in writing that the numbers match their Excel (PRD TC-DSH-04).
5. **Later.** The emailed weekly report, phone layout, and more data sources.
