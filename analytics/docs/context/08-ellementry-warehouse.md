# 08 — Ellementry warehouse and its connection (workspace 34)

*Updated 2026-11-02: schema 2.15, ten dashboards.*

## Where things are
- **Warehouse code:** `warehouse/` in this repo (moved from `ellementry_source_code/ellementry_data/ellementry_dw` on 2026-10-22, history kept).
  - Read its `README.md`. Business documents are in `warehouse/docs/`: the PRD, the rules register, the data model, and the **issue log** (`ISSUE_LOG.md` plus `Data_Issues_and_Doubts_Log_2026-10-30.xlsx`, with sheets Summary / Solved (how) / Unsolved (what is needed)).
- **Source exports:** `exports/`, outside git because they hold customer data.
  - One canonical copy per source and period, listed in `MANIFEST.tsv` (file, as-of date, sha256, rows, period, original name). Folders: `transactional/`, `snapshots/` (stock reports, including `stock_month_end`), `master/`, `returns/`, `fulfilment/`, `sellout/`, `state/`, and `_inbox/` for new files.
  - `_originals/` holds every distinct original export as received, with sha256 in `ORIGINALS.tsv`; ERP downloads are in `_originals/erp_2026-11-02/`. The loader never reads this folder.
  - Normalised files (Blinkit/Instamart sell-out, GRN register) have a `NORMALISE_LOG.tsv` next to them.
- **Working reports:** `reports/` (not in git): `S2_mrp_differences_by_location.csv`, `bagru_unexplained_stock.csv`, `bagru_unexplained_stock_explained.csv`.
- **Database:**
  - PostgreSQL 18 on the host (`postgresql-x64-18`, port 5432), database **`ellementry_dw`**, **schema 2.15**.
  - Admin login: `warehouse/.env` → `ADMIN_DATABASE_URL`, read by `dw.py`. Never print it; never ask the user for it.
- **Other databases on the server:**
  - `ellementry_dw_trial`: a full copy; every migration and load is tried here first.
  - `dw_test_po`: the disposable, loaded test database (see 07).
- **Backups:** `C:\Users\Dileep\Desktop\ellementry_backups\ellementry_dw_<date>_<time>.dump`, taken by `python dw.py backup` before every change (the latest is from 2 Nov 2026, before 2.15).

## Layers (one-way flow)
`exports → raw (exact text, contract-checked) → stg (typed) → core (dims, facts, stock ledger) → quality gate → coverage → mart`

- The `mart` views carry the business definitions.
- Ellementry Analytics reads **only `mart`**, through the read-only role `ellementry_metrics`. Its password is in `analytics/.env` as `ELLEMENTRY_CONN_ELLEMENTRY_PASSWORD`.
- New mart views get SELECT for that role through default privileges.
- Contracts are in `loader/contracts/*.json`, with layouts TABLE or STOCK_PIVOT. Loads go through `load_manifest.py`. Platform workbooks are normalised first: `loader/normalise_platform_sales.py` (Blinkit/Instamart) and `loader/normalise_grn_register.py` (ERP MRN Register).
- Settings that change behaviour are in `meta.pipeline_setting`: the period, `po_document_remark_confirmed=true` (BR-031), `goods_receipt_location=BAGRU_WH` (BR-032), and `partner_list_complete=false`.

## Data loaded (live, 2026-11-02)

**Period.** `prototype_period_start` / `_end` = **1 Apr 2025 – 15 Sep 2026** (BR-020). The stock report of 31 Mar 2025 is admitted as opening stock (BR-033).

| Source | Core rows |
|---|---|
| ERP retail + domestic sales (FY 25-26, FY 26-27) | 119,409 invoice lines |
| ERP retail + domestic returns | 18,788 lines |
| ERP stock transfers out / in | 38,064 lines |
| ERP pending PO (with `Document Remark`; exports dated 26 Sep 2026) | 5,895 PO lines |
| **ERP MRN Register (goods receipts, 2.14)** | 5,936 GRN lines (1,457 receipts) |
| ERP stock reports: **19 days** (31 Mar 2025, every month-end to 31 Aug 2026, 15 Sep 2026) | 95,948 rows |
| Product master (Final Master Sep 2026 + ERP item master 13 Oct 2026) | 4,513 products |
| WMS dispatch (this is the OMS report) | 45,246 shipments |
| Blinkit / Instamart sell-out, normalised | 6,867 rows |
| Amazon FBA customer returns (reasons) | 3,499 lines |

**Reconciliation.** `reconcile.py` recomputes totals from the files with pandas. **28 of 28 checks agree to the paisa** on the trial and live databases after every change. The DQ gate adds `grn_rows_reconcile` (ERROR) and `grn_unknown_product_or_supplier` (WARN) for the GRN register.

**Key figures.**
- Stock at cost on 15 Sep 2026: **₹3.86 Cr**; slow stock (no sale for 180+ days): ₹53.2 L.
- Instamart: 6,494 units sold (sell-out); ₹90.8 L invoiced to its accounts; about 3,229 units rebuilt at Instamart (no opening balance).
- Supplier lead time: **87.4 days** on 2,988 receipt lines (real GRN dates).
- Bagru stock check, whole period: "arrived without a document" is 54,541 units (was 1,44,152 before 2.14) and "left without a document" is 100,425 units (was 131,654).

## Schema history (one line each; details in `warehouse/README.md` and the migrations in `warehouse/sql/`)
| Version | Migration | What changed |
|---|---|---|
| 2.3 | 110 | PO Document Remark stored; first full load (22 Oct) |
| 2.4 | 120 | ERP item master fills categories and MRPs; courier groups; tracked-channel RTO and delivery; transfers to FBA split from own locations; `v_purchase_order_lines` |
| 2.5 | 130 | WMS shipments link to ERP bills by Extern Order No, then AWB |
| 2.6 | 140 | A bill is its number within a financial year (recovered ₹26.1 L of FY 25-26 retail) |
| 2.7 | 150 | Exact SKU quantities for multi-SKU dispatch rows |
| 2.8 | 160 | Stock at cost (`current_cost`); the higher MRP wins; category from the ERP item master, else Uncategorised; Ellementry International = B2C export |
| 2.9 | 170 | Goods receipts arrive at Bagru (BR-032) |
| 2.10 | 180 | BR-031 confirmed: PO remark "Purchase" vs "Return" decides purchase vs return-inward |
| 2.11 | 190 | Month-end stock history; month-by-month stock check (`v_stock_movement_check`, step `45_stock_check.sql`) |
| 2.12 | 200 | PO export dates recorded (26 Sep 2026); Instamart July 2025 shifted-rows fix |
| 2.13 | 210 | Amazon return reasons (`v_return_reasons`); `v_slow_stock`; `v_partner_stock_monthly`; cover bands and cost in `v_days_of_cover`; BR-034 Instamart accounts |
| 2.14 | 220 | ERP GRN register: `core.fact_grn_line`; receipts in the stock ledger and lead time come from it when loaded |
| 2.15 | 230 | Store status sheet: 12 franchise accounts and Shoppers Stop (SIS) are sale-or-return partners with partner stock locations (BR-035); own stores' running / closed status |

## Business rules that matter for every number
- **Money excludes GST** (BR-001/002/003). **Net sales = invoices − returns** (BR-004).
- **Quick-commerce sell-out is demand, never revenue** (BR-024).
- **Stock is valued at cost** (ERP item master COST). Where MRPs disagree, the higher one is current. Category comes from the ERP item master, else "Uncategorised".
- **Goods receipts arrive at Bagru** (BR-032). **PO remark Purchase / Return is confirmed** (BR-031).
- **Instamart (BR-034):** Cloudstore Retail, Cloudkart Ventures, Jupiter Kart (Kerala and Tamil Nadu), PJTJ Technologies and Moksh Enterprises are QUICK_COMMERCE_PARTNER accounts. Their stock is pooled at `CONSIGN_INSTAMART`.
- **Franchise and SIS (BR-035):** from the business's store status sheet (`exports/_originals/business_2026-11-02/`). 12 franchise accounts (RLS Enterprise ×5, Design Estate, Home Secrets, Shree Nirmal, Adya, Morghade, B Earth, Glimpsess; 6 running) each have a stock location `CONSIGN_FR_*`; Shoppers Stop Limited bills its 14 counters (8 running) on one account, pooled at `CONSIGN_SIS_SHOPPERS_STOP`. Own stores (COCO): C-Scheme, HYD Banjara Hills and Mansarovar (new, first bill 11 Oct 2026) running; Jaipur Meeraki (= "Jaipur Store") and CG Road closed.
- **Ellementry International = B2C export;** B2B export goes through Dileep.
- **Partner/employee stock is ledger-based, with no opening balance** (G-028), so it stays off the stock tiles.
- **Gaps are shown as "no data", never 0.** Products with no MRP or cost are counted on their own tiles, never valued at 0.
- **Hand-made COO reports used `PRODASSESSABLEVALUE`, which includes GST,** so dashboard sales will be lower than those decks. Explain this once to management.

## Workspace 34 "Ellementry (live warehouse)" in the app

**Connector.** id 1 "ellementry_dw (mart, read-only)". Host `host.docker.internal:5432`, user `ellementry_metrics`, schema `mart`. Every dataset is synced hourly. Physical schema `ws_8304153982f4` in the Docker database `ellementry_analytics`.

**Datasets (29):**
| id | dataset | mart view | rows | date column |
|---|---|---|---|---|
| 53 | net_sales_daily | v_net_sales_daily | 102,937 | calendar_date |
| 72 | sales_orders_daily | v_sales_orders_daily | 9,501 | calendar_date |
| 59 | returns_daily | v_returns_daily | 16,245 | calendar_date |
| 76 | returns_to_sale | v_return_to_sale | 18,788 | return_date |
| 81 | return_reasons | v_return_reasons (Amazon FBA) | 3,499 | return_date |
| 54 | stock_position_latest | v_stock_position_latest | 4,974 | as_of_date |
| 75 | stock_position_daily | v_stock_position_daily (19 stock days) | 95,786 | snapshot_date |
| 78 | stock_movement_check | v_stock_movement_check | 98,863 | month_start_date |
| 58 | days_of_cover | v_days_of_cover | 4,836 | as_of_date |
| 79 | slow_stock | v_slow_stock | 4,731 | as_of_date |
| 80 | partner_stock_monthly | v_partner_stock_monthly | 36 | month_start_date |
| 55 | transfer_in_transit | v_transfer_in_transit | 1,484 | sent_date |
| 56 | open_purchase_orders | v_open_purchase_orders | 625 | po_date |
| 77 | purchase_order_lines | v_purchase_order_lines | 5,895 | po_date |
| 57 | supplier_lead_time | v_supplier_lead_time (from the GRN register) | 2,988 | po_date |
| 73 | fulfilment | v_fulfilment | 45,246 | order_date |
| 74 | quick_commerce_sell_out_daily | v_partner_sellout_daily | 6,003 | calendar_date |
| 60–62, 66–71 | partner_review, data_coverage, data_quality_latest, sources, load_batches, transform_runs, business_rules (35), data_gaps (28), source_notes | portal / data-health views | | |
| 63, 64, 65 | products (4,512), locations (90, incl. 13 franchise / SIS partner stock locations), channels (23) | lookup dimensions | | |

**Relationships (18).** Fact datasets join to products by `sku_code`, to locations by `location_code` and to channels by `channel_code`.

**Metrics (45):**
- **Sales:** net_sales, gross_sales, invoiced_sales, units_sold, bills, orders, average_bill, retail_net_sales, retail_bills, retail_average_bill, b2b_net_sales, sales_return_rate (lower is better).
- **Returns:** returns_value, units_returned, avg_days_to_return, amazon_units_returned.
- **Stock:** stock_on_hand, sellable_stock, **stock_value_cost** (headline), stock_value_mrp (reference only), stock_value_cost_history, cover_stock_value_cost, slow_stock_value_cost, stock_units_no_mrp, stock_units_no_cost, unexplained_stock_qty.
- **Supply:** open_po_qty, over_received_qty, units_in_transit, avg_lead_time_days.
- **Fulfilment:** deliveries, rto_rate (tracked channels only), late_shipment_rate, avg_order_to_ship_hours, avg_ship_to_deliver_days (tracked channels only).
- **Quick commerce / partners:** qc_units_sold, qc_sell_out_value, partner_stock_balance, partner_units_sent, partner_units_sold, partner_units_returned.
- **Data health:** dq_blocking_errors, dq_failed_checks, open_data_gaps, files_loaded.

**Calculated label columns** (made by `configure_warehouse_workspace.py`; the dashboards expect them): `sales_segment` (with "B2C export" for EXPORT_B2C and "B2B & partners (classification pending)" instead of Unknown), `channel` ("Classification pending"), `stock_position_latest.location_group`, `returns_to_sale.return_window`, `transfer_in_transit.route`.

## Dashboards (10, built by `scripts/build_executive_dashboards.py`)
Current ids are 172–181; they change on every rebuild because dashboards with the same names are replaced. The script runs every widget and reports any that come back empty.

| Dashboard | Main datasets | Notes |
|---|---|---|
| Executive overview | net_sales_daily, sales_orders_daily, stock, fulfilment | FY 26-27 to 15 Sep vs the same period last year; stock at cost |
| Sales & channels | net_sales_daily, sales_orders_daily | |
| Returns | returns_daily, returns_to_sale, return_reasons | Amazon FBA reasons and "not delivered" |
| Stock | stock_position_latest, stock_position_daily, stock_movement_check | Snapshot 15 Sep 2026 at cost, month-end history, unexplained-stock check |
| Fulfilment | fulfilment | RTO and delivery time on tracked channels only |
| Purchasing & transfers | open_purchase_orders, purchase_order_lines, supplier_lead_time, transfer_in_transit | Unreceived transfers to own locations vs to FBA |
| Discontinued & slow stock | slow_stock | Days since the SKU last sold anywhere |
| Days of cover | days_of_cover | Cover bands, at cost |
| Instamart | partner_stock_monthly, quick_commerce_sell_out_daily, net_sales_daily | Sell-out, invoiced and rebuilt stock |
| Data health | data_quality_latest, data_gaps, load_batches | |

Choices that keep tiles honest:
- Periods are explicit dates, because the data ends on 15 Sep 2026.
- Stock tiles exclude partner ledger balances (no opening balance). The Blinkit consignment balance (−5,749 units) is hidden.
- "In transit" counts transfers sent in the last 60 days; older unreceived transfers are a separate exception tile.

## Still open (full list in `warehouse/docs/ISSUE_LOG.md`: 90 solved, 37 unsolved)
- **Stock (15 open):**
  - Rest of the Bagru gap (D-124): scrap, stock adjustments, inventory transfers and subcontractor movements are not loaded by date and location. The ERP's detailed movement report fails ("Divide by zero"); the Summary could be run month by month. The Purchase Register needs the ERP login linked to a department.
  - Partner opening stock (D-080, G-028); Instamart opening stock and daily inventory (D-125, the business is on it).
  - Transfer locations only in the document prefix (D-038); daily stock saving from now on (D-004).
  - Decisions: negative ERP stock (D-118, the business is on it), Amazon FBA inventory report (D-052), what DFAL is (D-073).
  - Confirmations of evidence-based location mappings: D-071 (partly answered by the store sheet), D-072, D-075 (Lucknow only), D-127; as-of dates D-103, D-106.
- **Partner list (D-019):** franchise, SIS and Instamart accounts are now classified; ₹5.89 Cr (4,566 lines) is still unclassified, top names Expo Digital India, Blink Commerce, Titan, Natures Basket. Needed: confirm the rest are outright B2B, then switch on `partner_list_complete`. The factory list (G-005) is also still needed.
- **Partner returns on two routes (D-089):** Shoppers Stop and closed franchises send goods back on credit notes (GIR) and on return POs (GRN). Both add stock at Bagru; only credit notes reduce the partner's stock. Partner balances (sent minus credit notes, no opening, no sell-out) are therefore not real stock and stay off the tiles.
- **Fulfilment:** the WMS dispatch report is the OMS report. Missing delivery dates and marketplace RTO must come from seller-panel or courier exports (D-112, D-113); courier codes need confirming (D-111).
- **Blinkit is parked** (D-005, D-050, D-051, D-092) until data from the new seller arrangement arrives. **Zepto** has no data yet.
- **Mappings added from data evidence are `is_confirmed = false`**, with the evidence in the notes, until the business confirms them.
