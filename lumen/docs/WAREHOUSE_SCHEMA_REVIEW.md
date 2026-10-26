# Ellementry warehouse: schema and data review

*Written 2026-10-21. Read-only review: nothing in the warehouse, the source files or the app was changed.*

**How the review was done**
- **Database:** read through the read-only `ellementry_metrics` role (the `mart` views) plus PostgreSQL's own table statistics for row counts.
- **Source files:** profiled in place under `C:\Users\Dileep\Downloads` and checked against the loader contracts in `ellementry_dw/loader/contracts/`. No customer data was printed.
- **Code:** read from `ellementry_source_code/ellementry_data/ellementry_dw/` (sql, transform, seeds, contracts) and `migrations/003_warehouse_portal.sql`.

---

## 1. Summary

1. **The schema is well designed and matches our use case.**
   - It has one checked source of truth and a business rule register (BR-001…BR-030).
   - Gaps are explicit (G-001…G-028), and a `mart` layer carries the business definitions.
   - Ellementry Analytics should keep reading only `mart`, exactly as it does now.
2. **The warehouse database is empty.**
   - Every `raw`, `stg`, `core` fact and `insight` table has 0 rows, and `meta.load_batch` has 0 rows.
   - Only reference and context data is loaded: 76 locations, 22 channels, 16 listed partners, 30 rules, 28 gaps, the date calendar, and 1 product (the "unknown" placeholder).
   - The one successful build (2026-10-05) ran on no data. Its "all quality checks PASS" means nothing yet.
3. **Most of the data already exists on this PC**, in `Downloads`. Every main ERP export covers **Apr 2025 – Sep 2026**, which is the full 1.5-year period the PRD was waiting for (D-002). Most files match their loader contract exactly.
4. **What blocks loading is small:**
   - PO files carry one extra column.
   - Blinkit and Instamart files are monthly-sheet workbooks rather than the contract layout.
   - Duplicate copies of several files exist.
   - The build never fills the shipments table even though the dispatch file is complete.
5. **What can't be fixed by loading:**
   - Stock history: there is only one stock day, 15 Sep 2026.
   - Partner and factory lists.
   - Return reasons.
   - Marketing, finance, cost, settlements and Amazon/Shopify platform reports.

---

## 2. Schema at a glance

```
source files ─▶ raw (exact text, per source) ─▶ stg (typed) ─▶ core (dims + facts + stock ledger)
                                                       │
                       quality gate (ERROR = roll back the whole build) + coverage per month
                                                       ▼
                         mart (business definitions)  ◀── Ellementry Analytics reads ONLY this
                         insight (agent outputs: not needed for our use case)
```

| Schema | What it holds | Rows today |
|---|---|---|
| `meta` | 14 registered sources, load batches, transform runs, DQ results, 30 rules, 28 gaps, 24 business processes, 414 monthly coverage rows, 64 source notes, column lineage | context only; **0 load batches** |
| `ref` | Reviewed mappings: 76 locations (+171 spellings), 22 channels (+70 spellings), 21 document prefixes, 16 listed partners, 11 partner types, code mappings, GST states | loaded |
| `raw` | 14 landing tables, one per source, all text, with customer PII (restricted) | **all 0** |
| `stg` | 11 typed staging tables | **all 0** |
| `core` | 10 dimensions + 9 facts + 4 bridges + stock ledger (below) | dims seeded; **facts 0** |
| `mart` | 10 business views + 9 portal views (§5) | views exist, return no fact rows |
| `insight` | model runs, forecasts, recommendations, alerts | 0 (out of scope for us) |
| `app` | the old portal's login and sessions (1 account) | not used by Ellementry Analytics |

### Core model
- **Dimensions:**
  - `dim_date`: FY 2024-25 … 2030-31, with Indian fiscal year and month.
  - `dim_product`: rich attributes are reserved (collection, material, room, colour, size, set flag, MRP, lifecycle). Only the basics are fed today.
  - `dim_product_history`, `bridge_product_component` (sets).
  - `dim_location`: type, operator, system of record, sellable flag.
  - `dim_channel`: channel, sub-channel, group, fulfilment model, sale-or-return.
  - `dim_partner`: role, type, related-party, internal, classification method.
  - `dim_order`, `dim_courier`, `dim_return_reason`.
  - `dim_movement_type`: 16 signed movement types.
- **Facts:**

| Fact | Grain | Fed from | Built by transform? |
|---|---|---|---|
| `fact_sales_line` | invoice line | ERP Retail + Domestic Sales | yes |
| `fact_return_line` (+ receipts bridge) | return / credit-note line | ERP Retail + Domestic Returns | yes |
| `fact_stock_transfer_line` | transfer document line (OUT and IN) | ERP Stock Transfer out / inward | yes |
| `fact_purchase_order_line` | PO line, latest state | ERP Pending PO report | yes |
| `fact_goods_receipt_line` (+ GRN bridge) | receipt per PO line | ERP Pending PO report | yes |
| `fact_partner_sellout` | partner × day × store × SKU | Blinkit + Instamart sales | yes |
| `fact_inventory_snapshot` | day × location × SKU | ERP stock report, Blinkit + Instamart inventory | yes |
| `fact_stock_movement` | signed ledger row | derived from the facts above | yes |
| `fact_shipment` (+ SKU bridge) | outbound delivery | WMS dispatch | **no: the transform only empties it** |

---

## 3. What data is present (files found on this PC)

All of these are in `C:\Users\Dileep\Downloads`. Row counts and date ranges come from reading each file. "Contract" says whether the columns match what the loader will accept.

| Source | File (one copy each) | Rows | Business dates | Contract |
|---|---|---|---|---|
| ERP Retail Sales | Retail Sales 01-04-2025 to 31-03-2026.xlsx | 67,646 | 1 Apr 2025 – 31 Mar 2026 | ✅ exact |
| | Retail Sales 01-04-2026 to 15-09-2026.xlsx | 25,899 | 1 Apr – 15 Sep 2026 | ✅ |
| | **Retail Sales FY 26-27.xlsx** (newest, 21 Oct) | 30,899 | 1 Apr – **21 Oct 2026** | ✅ (overlaps the file above; use one, not both) |
| ERP Domestic Sales | Domestic Sales 01-04-2025 to 31-03-2026.xlsx | 20,612 | Apr 2025 – Mar 2026 | ✅ |
| | Domestic Sales 01-04-2026 to 15-09-2026.xlsx | 5,251 | Apr – 14 Sep 2026 | ✅ |
| ERP Retail Returns | Retail Sales Return 01-04-2025 to 31-03-2026.xlsx | 9,308 | Apr 2025 – Mar 2026 | ✅ |
| | Retail Sales Return Current FY.xlsx | 3,729 | Apr – 22 Sep 2026 | ✅ (the period cut-off drops 16–22 Sep) |
| ERP Domestic Returns | Domestic Sale Return 01-04-2025 to 31-03-2026.xlsx | 4,379 | Apr 2025 – Mar 2026 | ✅ |
| | Domestic Sale Return Current FY.xlsx | 1,545 | Apr – 22 Sep 2026 | ✅ |
| ERP Stock Transfer (out) | Stock Transfer 01-04-2025 to 31-03-2026.xlsx | 15,842 | Apr 2025 – Mar 2026 | ✅ |
| | Stock Transfer 01-04-2026 to 15-09-2026.xlsx | 3,706 | Apr – 15 Sep 2026 | ✅ |
| ERP Stock Transfer Inward | Stock Transfer Inward 01-04-2025 to 31-03-2026.xlsx | 15,479 | Apr 2025 – Mar 2026 | ✅ |
| | Stock Transfer Inward 01-04-2026 to 15-09-2026.xlsx | 3,037 | Apr – 15 Sep 2026 | ✅ |
| ERP Pending PO | Pending Purchase Order 25-26 12.22.xlsx | 4,622 | POs Apr 2025 – Mar 2026 | ❌ extra column `Document Remark` |
| | Pending Purchase Order 26-27 12.09 (1).xlsx | 1,350 | POs Apr – 24 Sep 2026 | ✅ |
| | Pending Purchase Order 26-27 12.09 (2).xlsx | 1,350 | same | ❌ extra `Document Remark` (a newer re-export of the file above) |
| ERP stock report | Inventory report 15 Sept.xls | 4,163 SKUs × ~37 locations | **one day: 15 Sep 2026** | ✅ (the verified sample) |
| Product master | Ellementry Final Mastor - 2026 september updated.xlsx (Sheet1) | 4,020 SKUs | as of Sep 2026 | ✅ (leading columns; the stale stock columns are ignored by design) |
| | Product Master List 13-10-2026 11.51.xlsx (ERP item master) | 5,711 items | as of 13 Oct 2026 | ➖ different layout; **contains COST, CATEGORY, GST %, ACTIVE/INACTIVE**, which could fill G-011 and G-021 |
| WMS dispatch | Dispatch order report 1 Apr.2025 to 15 Sep.2026.xlsm | 45,246 | **Apr 2025 – 15 Sep 2026, every month** | ✅ matches the draft contract; closes gap G-003 |
| Blinkit sell-out | Blinkit all time sales Data.xlsx | ~722 rows | Jul 2025 – Sep 2026 | ❌ 15 monthly sheets with **12 different column layouts**; the contract expects one `Sheet1` |
| Instamart sell-out | Instamart sales.xlsx | ~6,487 rows | Apr 2025 – Sep 2026 | ❌ 18 monthly sheets; the contract expects a `Sales Report` sheet |
| Blinkit inventory | — | — | — | **not found** |
| Instamart inventory | — | — | — | **not found** |

**Duplicates.** Several files exist as identical `(1)` / `(2)` copies. These include Retail Sales ×3, Inventory ×2, Dispatch ×2, Transfers ×2, and returns also under `Desktop\return data`. Before loading, pick one canonical copy per source and period into a dated folder, as PRD §2.1 suggests.

### Coverage this gives (once loaded)

| Business process | Apr 2025 – Mar 2026 | Apr – Sep 2026 | After 15 Sep 2026 |
|---|---|---|---|
| Company sales (retail + domestic) | full | full | retail to 21 Oct (needs the period end moved) |
| Returns and credit notes | full | full (to 22 Sep) | — |
| Stock transfers | full | full | — |
| Purchasing / goods receipts | state at FY end | state at 24 Sep | — |
| Order fulfilment (WMS) | full | full | — |
| Quick-commerce sell-out | Instamart full; Blinkit from Jul 2025 | full | — |
| Stock position | ❌ none | **15 Sep 2026 only** | — |
| Stock ledger (movements) | full, but **no opening balance** at partner and employee locations (G-028) and no adjustments or write-offs (G-002) | | |

---

## 4. What is missing

### 4a. Blocks loading what we have (warehouse-side fixes, small)
1. **PO contract.** The PO export now has a `Document Remark` column. The contract uses `exact_set`, so the loader would reject it. Update the contract plus a raw-table migration (the README's documented procedure), or re-export without it.
2. **Blinkit and Instamart sell-out.**
   - The files are monthly workbooks whose columns differ from month to month.
   - Two options: either the team re-exports them in the seller-panel layout the contracts were verified on, or we add a small, tested "flatten monthly sheets" step before the loader.
   - Instamart's date column didn't parse with the expected format either.
3. **Fulfilment.** `fact_shipment` / `bridge_shipment_sku` are never populated. The dispatch contract is still marked *draft*, and the transform has no build step.
   - Needed: a staging and fact step plus a fulfilment mart view.
   - The data covers the whole period (45k deliveries).
4. **Period cut-off.** `prototype_period_end = 2026-09-15` (BR-020). The newest retail file runs to 21 Oct 2026. Keeping dashboards current means moving this setting and agreeing on a routine (daily or weekly loads).
5. **Load order.** Product master first (with `--as-of`), then sales, returns, transfers, PO (with `--as-of` = its real export date, open issue D-094), stock report (`--as-of 2026-09-15`), dispatch, then `python -m transform run`.

### 4b. Data the business has to provide (from the gap register and issue log)

| Gap | Effect on dashboards until provided | Owner |
|---|---|---|
| G-001 / D-004 **Daily stock history** | No stock trend, no ageing, no "stock vs last month". Only 15 Sep exists. Every day not saved is lost for good. | ERP team: start saving daily **now** |
| G-004 / D-019 **Franchise, SIS, quick-commerce billing names** | Their invoices stay UNCLASSIFIED, so the B2B and consignment split is unreliable (≈ ₹204 lakh in the sample) | Business |
| G-005 / D-044 **Factory list** | Can't tell purchases from return-inwards on the PO report, so supplier lead times and overdue POs are unreliable | Business |
| G-028 **Opening stock at partners on 1 Apr 2025** | Partner and employee stock balances are "movements only" and can go negative | Business |
| G-002 **Adjustments, write-offs, production receipts** | The ledger can't fully balance against the stock report | ERP team |
| G-009 **Return reasons** | No "why" on returns. The domestic reason column exists but is empty; the Amazon FBA returns report is a candidate (D-105) | Business |
| G-007 **Amazon FBA inventory and inbound reports** | FBA stock is only the ERP's view | Business |
| G-011 **Product hierarchy** (collection, material, room) | No collection or material breakdowns. **The ERP item master in Downloads has CATEGORY and other attributes**; review whether it can fill part of this | Business / product |
| G-010 Set composition, G-013 store opening and closing dates, G-016 festive calendar | Sets counted as their own SKU; no Diwali-aware comparisons (the 2025 vs 2026 Diwali shift is exactly what the recent COO channel report had to explain by hand) | Business |
| D-094 **Real export dates of the PO files** | Needed for the `--as-of` load date | ERP team |
| D-089 Shoppers Stop returns on two routes; D-092 Blinkit supply route | Risk of double-counted returns; quick-commerce stock unclear | Business |

39 issues are still open in the Data Issues log (2026-10-15). Those blocking real use: D-002 (now largely solvable with the files above), D-004, D-019, D-044, D-080, D-089, D-094, D-095.

### 4c. "All company data" the schema designs for but has no source yet
These processes are designed and marked LATER, with no data:
- **Ad spend and performance** (Google, Meta): G-017
- **Traffic and listing health**: G-018
- **Marketplace settlements and fees**: G-019
- **Ledger, P&L, receivables**: G-020
- **Product cost**: G-021. *The ERP item master's COST column may give a first version.*
- **Reviews**: G-022
- **Customer identity**: G-023
- **Team data**: G-024
- **Courier cost**: G-012
- **Marketplace order reports including cancellations**: G-014

Leadership reports on revenue, ROAS, margin and EBITDA need these. They should come in through the warehouse (new source + contract + fact + mart view), not as one-off uploads.

---

## 5. How the warehouse fits Ellementry Analytics

Workspace 34 already imports every `mart` view through the read-only connector and re-syncs it hourly. Once the warehouse is loaded and built, the data flows in with no app change. Here is what each mart view will support.

| Mart view (dataset in workspace 34) | Grain | Gives managers | Limits |
|---|---|---|---|
| `v_net_sales_daily` | day × channel × location × SKU × partner type | Gross sales, returns, **net sales excl. GST**, units, by channel / sub-channel / group, location, product, category, fiscal year/month, related-party and sale-or-return flags | **No bill or order count**, so no "bills" or "average bill" (the COO channel report used both); product attributes beyond category are empty |
| `v_returns_daily` | day × channel × reason × location × SKU | Return units and value by channel, location, product | Reason always "not recorded" (G-009); no days-from-sale (the COO deck's "median 15 days" needs `original_sales_line_id`, which is in core but not exposed) |
| `v_stock_position_latest` | location × SKU (latest) | Stock units, sellable units, **stock value (units × MRP)**, by location type, lifecycle | Latest day only (G-001); partner / employee balances are ledger-based with no opening |
| `v_days_of_cover` | location × SKU | Cover per location | PRD notes it overstates Bagru cover (ignores transfers out); the PRD's `v_stock_demand` / `v_network_stock` are not built |
| `v_transfer_in_transit` | transfer line | Units and value in transit, by route and age | No transit-history view (PRD) |
| `v_open_purchase_orders`, `v_supplier_lead_time` | PO line / receipt | Open and overdue POs, lead times | Suppliers vs return-inwards not separated until the factory list arrives |
| `v_partner_review`, `v_data_quality_latest`, `v_data_coverage`, portal views | — | Data health, coverage, rules and gaps pages (D8) | — |
| *(none)* | — | **Quick-commerce sell-out** | `fact_partner_sellout` has no mart view |
| *(none)* | — | **Fulfilment**: order-to-ship, SLA, RTO, courier | `fact_shipment` not built, no view |
| *(none)* | — | **Stock trend / history** | needs daily snapshots plus a history view |

### Mart additions the executive dashboards will need (warehouse project, `mart` only)
1. **`v_sales_orders_daily`:** distinct bills and orders per day × channel (from `fact_sales_line.order_key` / `bill_number`), for order count and average bill value.
2. **`v_partner_sellout_daily`:** Blinkit and Instamart consumer sell-out (demand, never added to revenue: BR-024).
3. **`v_fulfilment`** (after the shipment build step): order-to-ship, ship-to-deliver, RTO, by courier, channel and pincode.
4. **`v_stock_position_daily`:** every saved snapshot, so trends appear as daily saving builds history.
5. **`v_return_to_sale`:** days from sale to return, per channel.
6. From PRD §3.2 if wanted: `v_stock_demand`, `v_network_stock`, `v_transfer_transit_history`.

### Consistency note for leadership
The recent hand-made **Channel Sales Comparison** (21 Oct) used `PRODASSESSABLEVALUE`, which **includes GST**. BR-001 and BR-002 say headline sales exclude GST (`PRODDOCVALUE`). Warehouse-based dashboards will therefore show **lower** figures than those reports. That's expected, and it should be explained to management once, before the dashboards replace the hand-made reports. The **Retail Return Analysis (COO)** deck already used values excluding GST, so it should reconcile.

---

## 6. Suggested next steps for the data foundation (nothing done yet)

1. **Fix the credential exposure first.** `ellementry_source_code\.env` contains **commented-out lines with plain-text database URLs and passwords** (postgres superuser, `ellementry_app`, `ellementry_metrics`). They showed up during this review.
   - Delete those comment lines.
   - Rotate the `postgres` password, plus the other two if they are still in use. If `ellementry_metrics` changes, update `LUMEN_CONN_ELLEMENTRY_PASSWORD` in `lumen\.env` and recreate the app container.
2. **Start saving the stock report daily** (ERP, Blinkit, Instamart) into a dated folder. This is the one gap that gets worse every day.
3. **Make a clean source folder:** one canonical copy per source and period, named with its as-of date where needed.
4. **Small warehouse changes, each with tests:**
   - the PO contract's `Document Remark`
   - a Blinkit / Instamart monthly-sheet adapter or re-exports
   - promote the WMS contract from draft
   - the shipment build step
   - move `prototype_period_end` when ready
5. **Load and build** on a copy of the database first, then compare control totals with the team's Excel. PRD control totals for the sample: retail net sales ₹4,22,80,208.54; Bagru trading stock 82,509 units; 2,794 units in transit.
6. **Add the mart views** in §5, then sync workspace 34. The dashboards from `EXECUTIVE_DASHBOARD_PLAN.md` can then be built on real data.
7. **Chase the business inputs** in §4b, especially the partner list, the factory list and opening partner stock.
