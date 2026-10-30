# 08 — Ellementry warehouse and its connection (workspace 34)

*Updated 2026-10-22, after the first full data load.*

## Where things are
- **Warehouse code:** `C:\Users\Dileep\Desktop\ellementry-analytics\warehouse\`.
  - It is its own git repo, copied with its history from `ellementry_source_code/ellementry_data/ellementry_dw`; the old folder is no longer used.
  - Read its `README.md`. Business documents (PRD, rules register, data model, issue log) are in `warehouse/docs/`.
- **Source exports:** `ellementry-analytics\exports\`, outside git because they hold customer data.
  - One canonical copy per source and period, listed in `MANIFEST.tsv` (file, as-of date, sha256, rows, period, original name).
  - `_originals/` holds every distinct original export as received (original file names, including superseded
    re-exports), with sha256 in `ORIGINALS.tsv`. The loader never reads this folder.
  - `sellout/` holds the normalised Blinkit and Instamart monthly files, with `NORMALISE_LOG.tsv`.
- **Database:**
  - PostgreSQL 18 on the host (`postgresql-x64-18`, port 5432), database **`ellementry_dw`**, **schema 2.12**.
  - Admin login: `warehouse/.env` → `ADMIN_DATABASE_URL`, read by `dw.py`. Never print it; never ask the user for it.
- **Other databases on the server:**
  - `ellementry_dw_trial`: a full copy used to test loads.
  - `dw_test_po`: a disposable test database.
  - Both can be dropped or rebuilt with `dw.py build`.
- **Backups:** `C:\Users\Dileep\Desktop\ellementry_backups\`, e.g. `ellementry_dw_2026-10-22_1025.dump`, taken just before the first load.

## Layers (one-way flow)
`exports → raw (exact text, contract-checked) → stg (typed) → core (dims, facts, stock ledger) → quality gate → coverage → mart`

- The `mart` views carry the business definitions.
- Ellementry Analytics reads **only `mart`**, through the read-only role `ellementry_metrics`. Its password is in `analytics/.env` as `ELLEMENTRY_CONN_ELLEMENTRY_PASSWORD`.
- New mart views get SELECT for that role through default privileges.

## Data loaded (live, transform run 2, 2026-10-22)

**Period.** `prototype_period_start` / `_end` = **1 Apr 2025 – 15 Sep 2026** (BR-020). The FY 26-27 retail file runs to 21 Oct 2026, but the extra rows stay in raw only.

| Source | Files | Core rows |
|---|---|---|
| ERP retail + domestic sales | FY25-26 + FY26-27 | 117,323 invoice lines |
| ERP retail + domestic returns | FY25-26 + current FY | 18,788 lines |
| ERP stock transfers out / in | FY25-26 + FY26-27 | 38,064 lines |
| ERP pending PO (with `Document Remark`) | FY25-26 (as-of **assumed** 2026-03-31) + FY26-27 (as-of 2026-09-24) | 5,895 PO lines, 4,906 receipts |
| ERP stock report | **15 Sep 2026 only** | 4,866 rows (no stock history: G-001) |
| Product master | Sep 2026 | 4,512 products |
| WMS dispatch | Apr 2025 – 15 Sep 2026 | 45,246 shipments |
| Blinkit / Instamart sell-out | Jul 2025 / Apr 2025 – Sep 2026, normalised | 6,903 rows |

**Reconciliation.** `reconcile.py` recomputes totals from the files with pandas. **28 of 28 checks agree to the paisa**, on both the trial and the live database. Examples:
- Retail invoices excl. GST (in period): ₹13,88,05,395.06 (2.6; ₹13,61,90,938.06 before the financial-year fix)
- Domestic invoices (Taxable): ₹12,16,24,694.18
- Retail returns: ₹1,77,86,234.78
- 1,950 RTO shipments
- 65,734 Instamart units

**Control totals.** The PRD controls reproduce on the sample files: retail ₹4,22,80,208.54, Bagru stock 82,509, 2,794 units in transit. The newer FY 26-27 export differs slightly for the same months because invoices were revised in the ERP; the latest export wins.

## Workspace 34 "Ellementry (live warehouse)" in the app

**Connector.** id 1 "ellementry_dw (mart, read-only)". Host `host.docker.internal:5432`, user `ellementry_metrics`, schema `mart`. Every dataset is synced hourly.

**Physical schema.** `ws_8304153982f4` in the Docker database `ellementry_analytics`.

| id | dataset | mart view | rows | date column |
|---|---|---|---|---|
| 53 | net_sales_daily | v_net_sales_daily | 101,338 | calendar_date |
| 72 | sales_orders_daily | v_sales_orders_daily (bills, orders) | 9,384 | calendar_date |
| 59 | returns_daily | v_returns_daily | 16,243 | calendar_date |
| 76 | returns_to_sale | v_return_to_sale (days from sale) | 18,788 | return_date |
| 54 | stock_position_latest | v_stock_position_latest | 4,932 | as_of_date |
| 75 | stock_position_daily | v_stock_position_daily | 4,856 | snapshot_date |
| 58 | days_of_cover | v_days_of_cover | 4,794 | as_of_date |
| 55 | transfer_in_transit | v_transfer_in_transit | 1,484 | sent_date |
| 56 | open_purchase_orders | v_open_purchase_orders (+document_type) | 682 | po_date |
| 57 | supplier_lead_time | v_supplier_lead_time (+document_type) | 4,906 | po_date |
| 73 | fulfilment | v_fulfilment | 45,246 | order_date |
| 74 | quick_commerce_sell_out_daily | v_partner_sellout_daily | 6,025 | calendar_date |
| 60–62, 66–71 | partner_review, data_coverage, data_quality_latest, sources, load_batches, transform_runs, business_rules, data_gaps, source_notes | portal / data-health views | — | — |
| 63, 64, 65 | products (4,512), locations (76), channels (22) | lookup dimensions | | |

**Relationships (18).** Fact datasets join to products by `sku_code`, to locations by `location_code` and to channels by `channel_code`.

**Metrics (23):**
- **Sales:** net_sales, gross_sales, units_sold, sales_return_rate (lower is better), bills, orders, invoiced_sales, **average_bill**.
- **Returns:** returns_value, units_returned, avg_days_to_return.
- **Stock:** stock_on_hand, sellable_stock, **stock_value_mrp** (semi-additive).
- **Supply:** open_po_qty, units_in_transit, avg_lead_time_days.
- **Fulfilment:** deliveries, **rto_rate** (4.3%), **late_shipment_rate** (10.7%), avg_order_to_ship_hours, avg_ship_to_deliver_days.
- **Quick-commerce demand:** qc_units_sold.

## Executive dashboards (prototype, built 2026-10-22)
- **Build and rebuild:** `python scripts/build_executive_dashboards.py` (from `analytics/`). It replaces dashboards with the same names, so their ids change, then runs every widget and reports any widget that comes back without data.
- **The dashboards:**
  - **Executive overview** (period FY 26-27 to 15 Sep, compared with the same period last year): net sales, retail net sales, retail bills, retail average bill, return rate, stock value, sales by month and segment, retail channels, top products, fulfilment KPIs.
  - **Sales & channels**
  - **Returns**
  - **Stock** (snapshot of 15 Sep 2026)
  - **Fulfilment**
  - **Purchasing & transfers**
- **Calculated label columns** (defined in the app on the synced datasets; the script expects them):
  - `net_sales_daily` / `sales_orders_daily`: `sales_segment`, which reads "B2B & partners (classification pending)" instead of "Unknown".
  - `channel`, which reads "Classification pending".
  - `stock_position_latest.location_group`, `returns_to_sale.return_window`, `fulfilment.courier`, `transfer_in_transit.route`.
- **Extra metrics:** retail_net_sales, retail_bills, retail_average_bill (retail = partner_type D2C_CHANNEL_ACCOUNT), b2b_net_sales.
- **Choices made to keep tiles honest:**
  - Periods are explicit dates, because the data ends on 15 Sep 2026.
  - Stock tiles exclude partner ledger balances, which have no opening balance (G-028).
  - "In transit" counts transfers sent in the last 60 days. The 4,791 units sent earlier and never received are a separate exception tile.
  - Lead time and open POs use lines the PO export marks "Purchase". This is a filter on the export's remark; BR-031 itself is not applied.
- **Verification:** every KPI was checked against direct SQL on the warehouse and matched exactly. The FY 26-27 YTD story: retail +4.9% vs the same period last year, 9.7% fewer bills, average bill +14.7%, return rate up from 10.3% to 10.7%.

## Schema 2.4 (2026-10-22): supply, fulfilment and stock fixes
Applied with `warehouse/sql/120_supply_dashboard_fixes.sql`, seeds, the new ERP item master load and a transform run;
the app side with `scripts/configure_warehouse_workspace.py`, then `build_executive_dashboards.py`.
- **Stock:** the ERP item master (Product Master List, 13 Oct 2026) fills missing categories (2,278 products without
  one → 60) and two MRPs. `category_label` is never blank. 110 trading SKU-locations / 14,474 units still have no MRP
  anywhere: `stock_value_mrp` leaves them out, and the Stock dashboard shows them as "Units with no MRP".
  Days of cover now counts transfers out as well as sales.
- **Fulfilment:** `courier_group` maps the 39 WMS spellings to about 10 companies (all mappings unconfirmed, with
  evidence). `rto_rate` uses only channels that record RTO (website, Pepperfry): 7.9% instead of the misleading 4.3%.
  `avg_ship_to_deliver_days` uses only channels that report deliveries. Weights over 100 kg are dropped (85 rows).
- **Purchasing & transfers:** unreceived transfers split into "To Amazon FBA" (Amazon records the receipt, G-007) and
  "To own locations" (the real exceptions: 526 lines / 1,441 units over 60 days). Open PO lines carry `due_status`
  ("Overdue (export date assumed)" for the FY 25-26 export, "No due date"). New dataset `purchase_order_lines`
  (`v_purchase_order_lines`): 24 over-received lines, 5,056 units.
- **New metrics:** `stock_units_no_mrp`, `over_received_qty`. `rto_rate` and `avg_ship_to_deliver_days` gained
  tracked-channel filters. The `fulfilment.courier` calculated column is no longer used by the dashboards.

## Schema 2.8 (2026-10-27): business answers applied
- **Stock value is at cost** (metric `stock_value_cost`, unit cost from the ERP item master): ₹3.86 Cr on 15 Sep 2026.
  The Stock and Executive dashboards show cost; `stock_value_mrp` stays as a metric for reference only.
- **Higher MRP wins** where sources disagree (price rise); **category = ERP item master only** (top level), with
  `sub_category_label` as the drill level.
- **Ellementry International = B2C export** (channel `EXPORT_B2C`, segment "B2C export"); B2B export = via Dileep.
- **Quick commerce:** Instamart is the focus; Blinkit stays loaded but is not worked on for now; Zepto has no data yet.
- **Goods receipts arrive at Bagru** (BR-032, schema 2.9; G-025 closed). **BR-031 confirmed** (schema 2.10): open
  POs and lead time cover purchase lines only, and receipts are in the stock ledger. Open question: 284 Bagru SKUs
  (~20,700 units) received with no recorded way out (superseded in 2.11, see below).
- **Stock history (schema 2.11):** month-end stock reports 31 Mar 2025 - 31 Aug 2026 loaded (19 stock days with 15 Sep).
  Stock dashboard: "Stock value at cost, month-end" (metric `stock_value_cost_history`, dataset `stock_position_daily`).
  New dataset `stock_movement_check` (metric `unexplained_stock_qty`): opening + movements vs closing per period. Bagru,
  whole period: 55,188 units left and 71,350 arrived with no document (non-PO purchases, gift-set assembly, packaging
  use): `reports/bagru_unexplained_stock.csv`. What would explain it: an ERP item-wise stock ledger or GRN register
  that includes non-PO inwards, assembly and consumption.
- **Schema 2.12 / 30 Oct:** PO exports dated 26 Sep 2026 (no more "export date assumed"); Instamart July 2025 fixed
  (59,550 -> 310 units; total Instamart sell-out 6,494 units). Issue log: `warehouse/docs/ISSUE_LOG.md`.
- **Blinkit:** old Blinkit data is set aside (new seller arrangement); the negative consignment ledger stays hidden.
- **Negative ERP stock and Instamart inventory:** the business is handling both.
- **The WMS dispatch report is the OMS report:** there is no richer OMS export. Missing delivery dates and marketplace
  RTO must come from marketplace seller-panel reports or courier MIS exports by AWB.
- **Coming from the business:** ERP inventory for chosen past days (see the stock-history plan), Instamart daily
  inventory.

## Rules that matter for every number
- **Money excludes GST** (BR-001/002/003).
- **Net sales = invoices − returns** (BR-004).
- **Quick-commerce sell-out is demand, never revenue** (BR-024).
- **Partner/employee stock is ledger-based, with no opening balance** (G-028).
- **Gaps are shown as "no data", never 0.**
- **Hand-made COO reports used `PRODASSESSABLEVALUE`, which includes GST,** so dashboard sales will be lower than those decks. Explain this once to management.

## Still open (business inputs; see warehouse/docs/Data_Issues_and_Doubts_Log)
- **Partner list (G-004):** 25,743 domestic lines, ₹11.5 Cr, are unclassified, so their channel is unknown. Top names: Shoppers Stop, RLS Enterprise.
- **Rule BR-031 (PROPOSED):** the PO `Document Remark` (Purchase/Return) separates purchases from return-inwards. The switch `po_document_remark_confirmed` stays false until the business confirms.
- **PO export dates (D-094):** the FY25-26 as-of date is assumed.
- **Dispatch invoice series (resolved in 2.5):** `M25-`/`M26-`/`M44-` are the marketplaces' own invoice numbers. Shipments now link to ERP bills through the Extern Order No (the marketplace order ID, = ERP ORDER_NUMBER), with the AWB as fallback.
- **Retail bill numbers restart each financial year (fixed in 2.6):** the warehouse used to drop 2,086 FY 25-26 retail lines (₹26.1 lakh excl. GST, Apr-Jul 2025) whose numbers reappeared in FY 26-27. Retail sales Apr 2025 - Sep 2026 are now ₹13.92 Cr (was ₹13.66 Cr); 45,171 of 45,246 deliveries link to a bill.
- **Unmapped names:** "Ellementry International" (channel), and the Mumbai PPOB / Delhi retail contacts (location known, channel unknown).
- **Daily stock saving (G-001):** must start, or trends are impossible.
- **Partner opening stock (G-028), receiving location on goods receipts (G-025), return reasons (G-009).**
- **New mappings are unconfirmed.** Mappings added on 2026-10-22 from data evidence are all `is_confirmed = false`, and their evidence is in the notes. Examples: "Pvt Ltd Bagru" → Bagru Popup, "Lucknow" → DEPL Lucknow, "Jaipur Store" → Meeraki, CG Road, the FBA codes, and prefixes such as AHM4/DC and LUC9/DC. The business should review them in the reference-mappings workbook.
