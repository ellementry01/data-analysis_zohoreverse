# Warehouse load: fix plan

> **Status 2026-10-22: done.**
> - Every fix in §1–§4 is implemented in `ellementry-analytics/warehouse` (git), along with the mart views from the review.
> - All 1.5 years of exports are loaded into `ellementry_dw`. A backup was taken first, and reconciliation gives **28 of 28 checks agree**.
> - Workspace 34 is synced.
> - Still open are the business decisions in §10, plus the items listed at the end of `context/08-ellementry-warehouse.md`.

*Written 2026-10-21. This is a plan only: nothing in the warehouse, its code or the source files has been changed.*
*It builds on `WAREHOUSE_SCHEMA_REVIEW.md`. The work happens in `C:\Users\Dileep\Desktop\ellementry_source_code\ellementry_data\ellementry_dw` (the "warehouse package").*

**How the evidence was gathered**
- **Loader check:** every export was run through the warehouse loader in `--dry-run` mode. That mode parses the file against its contract and never connects to the database. Afterwards, `meta.load_batch` was confirmed to still hold 0 rows.
- **Content checks:** read-only profiling of the PO, Blinkit, Instamart and dispatch files. No customer details were printed.

---

## 0. Dry-run results: where we stand

| Source | File | Result |
|---|---|---|
| ERP Retail Sales | Retail Sales 01-04-2025 to 31-03-2026.xlsx | ✅ 67,646 rows, 1 Apr 2025 – 31 Mar 2026 |
| | Retail Sales FY 26-27.xlsx | ✅ 30,899 rows, 1 Apr – 21 Oct 2026 |
| ERP Domestic Sales | Domestic Sales 01-04-2025 to 31-03-2026.xlsx | ✅ 20,612 rows |
| | Domestic Sales 01-04-2026 to 15-09-2026.xlsx | ✅ 5,251 rows |
| ERP Retail Returns | both files | ✅ 9,308 + 3,729 rows |
| ERP Domestic Returns | both files | ✅ 4,379 + 1,545 rows |
| ERP Transfers out | both files | ✅ 15,842 + 3,706 rows |
| ERP Transfers inward | both files | ✅ 15,479 + 3,037 rows |
| ERP stock report | Inventory report 15 Sept.xls | ✅ 4,162 SKUs → 153,994 location rows. One warning: 7 filtered locations have no column (known issue D-085) |
| Product master | Ellementry Final Mastor - 2026 september updated.xlsx | ✅ 4,020 SKUs |
| ERP Pending PO | 26-27 12.09 **(1)**.xlsx | ✅ 1,350 rows |
| | 25-26 12.22.xlsx and 26-27 12.09 **(2)**.xlsx | ❌ rejected: new column `Document Remark` |
| Blinkit sales | Blinkit all time sales Data.xlsx | ❌ rejected: no `Sheet1` (15 monthly sheets) |
| Instamart sales | Instamart sales.xlsx | ❌ rejected: no `Sales Report` sheet (18 monthly sheets) |
| WMS dispatch | Dispatch order report 1 Apr.2025 to 15 Sep.2026.xlsm | ❌ `.xlsm` files are not accepted by the reader |

**The core ERP sales, returns, transfers, stock and master data pass today.** Four fixes are needed for the rest, plus one hidden bug (§2b).

---

## 1. Clean source folder

**Problem**
- The exports are spread over `Downloads` and `Desktop\return data`.
- Several files exist in two or three copies. I checked content hashes: the copies are identical, e.g. Retail Sales 25-26 ×3, Inventory ×2, Domestic Sales 26-27 ×2, Retail Return Current FY ×2.
- These files hold customer PII.

**Plan**: create one folder **outside both code projects**, e.g. `C:\Users\Dileep\Desktop\ellementry_exports\`. It is never committed, never synced, and restricted to you.

```
ellementry_exports\
  MANIFEST.tsv                 source | file | as_of | sha256 | rows | period | note   (one row per file loaded)
  transactional\
    FY2025-26\  ERP_RETAIL_SALES__2025-04-01_2026-03-31.xlsx, ERP_DOMESTIC_SALES__..., ERP_RETAIL_RETURN__..., ...
    FY2026-27\  ERP_RETAIL_SALES__2026-04-01_2026-10-21.xlsx, ...
  state\        ERP_PURCHASE_ORDER__FY2025-26__asof_<date>.xlsx, ERP_PURCHASE_ORDER__FY2026-27__asof_2026-09-24.xlsx
  snapshots\    ERP_INVENTORY_SNAPSHOT__2026-09-15.xls        (+ one file per day from now on, see §6)
  master\       PRODUCT_MASTER__2026-09-15.xlsx
  sellout\      BLINKIT_SALES__2025-07.csv … , INSTAMART_SALES__2025-04.csv …   (output of §3)
  fulfilment\   WMS_DISPATCH__2025-04-01_2026-09-15.xlsm (or .xlsx, see §4)
  _originals\   untouched copies of the platform workbooks exactly as received
```

**Canonical file per source and period**

| Source | Use | Skip |
|---|---|---|
| Retail Sales FY 25-26 | `Retail Sales 01-04-2025 to 31-03-2026.xlsx` | (1), (2) copies |
| Retail Sales FY 26-27 | **`Retail Sales FY 26-27.xlsx`**: a superset of the 01-04..15-09 file (identical Apr–Aug counts, more Sep, plus Oct) | `Retail Sales 01-04-2026 to 15-09-2026*.xlsx` |
| Domestic Sales | 25-26 file + `Domestic Sales 01-04-2026 to 15-09-2026.xlsx` | the (1) copy |
| Returns, transfers | the 25-26 file + the current-FY file of each | `Desktop\return data` duplicates |
| PO | 25-26 12.22 + **26-27 12.09 (2)** (both carry `Document Remark`) | 26-27 (1): the same rows without the remark |
| Stock report | `Inventory report 15 Sept.xls` | (1) copy |
| Product master | `Ellementry Final Mastor - 2026 september updated.xlsx` | — (the ERP item master is a separate future source, §5) |
| Dispatch | `Dispatch order report 1 Apr.2025 to 15 Sep.2026.xlsm` | (1) copy |

Overlaps are safe. Staging already keeps **the latest batch per document** for sales, returns and transfers, so re-exports replace rather than double-count. Load older periods first.

---

## 2. Purchase orders

### 2a. `Document Remark` column: an opportunity, not just a fix
- Both new PO exports have a 38th column, `Document Remark`, filled on **every** row.
- It holds **`Purchase` or `Return`**: 2,339 / 2,283 lines in FY 25-26, and 666 / 684 in FY 26-27.
- This is exactly the purchase vs return-inward split that BR-013 and gap G-005 (the factory list) were waiting for.

**Changes:**
1. **Contract.** Add `Document Remark` to `ERP_PURCHASE_ORDER`:
   - Regenerate the contract from the 26-27 (2) file through `build_contracts.py` (spec entry → new sample).
   - Keep `exact_set`, so the old 37-column layout is refused from now on.
2. **Raw table.** Two parts:
   - A numbered migration `sql/110_raw_po_document_remark.sql` containing `ALTER TABLE raw.erp_purchase_order ADD COLUMN document_remark TEXT` plus its column comment.
   - Regenerate `070_raw_tables.sql` for fresh builds.
3. **Staging and core:**
   - Carry `document_type` (`PURCHASE` / `RETURN` / `UNKNOWN`) into `stg.purchase_order`.
   - **Use it to classify:**
     - only `PURCHASE` lines count as supplier purchases (open and overdue POs, lead times)
     - `RETURN` lines become return-inwards (movement type `RETURN_INWARD`, BR-013)
     - `UNKNOWN` stays unclassified and is counted by a WARN check
   - Add a `document_type` column to `fact_purchase_order_line`, with its definition in `seeds/column_definitions.tsv`, regenerated into `990`.
4. **Rule register.** Record a new rule, **BR-031 (PROPOSED)**: "The PO report's Document Remark distinguishes purchases from return-inwards". It needs business confirmation before go-live. Update G-005: the factory list is then needed only for supplier names and grouping, not for the split.
5. **Mart.**
   - `v_open_purchase_orders` and `v_supplier_lead_time` filter to `PURCHASE`, appending `document_type` at the end so existing columns are unchanged.
   - Optional: a `v_return_inwards` view.

### 2b. Hidden bug: only the newest PO export is kept
- `transform/sql/11_stg_supply.sql` builds `stg.purchase_order` from **the single latest PO batch** (`ORDER BY as_of_date DESC LIMIT 1`).
- The PO report is **per financial year**. Loading FY 25-26 and then FY 26-27 would silently drop every FY 25-26 PO line.
- **Fix:** keep the latest batch **per PO number**, the same "latest batch per document wins" rule used for sales and transfers. Each line keeps its own batch's `as_of_date`.
- **Test:** two PO batches with different FYs → both present; a re-export of the same FY → the newer one wins.

### 2c. As-of dates
- A PO export is a state snapshot, so the loader requires `--as-of`, and it refuses an as-of earlier than the dates inside the file.
- The real export dates of both files are unknown (open issue D-094: "12.22" and "12.09" in the names).
- **Need from the ERP team:** the date each file was exported. Use 2026-09-24 for 26-27 only if they can't confirm (it is the latest date inside the file).

---

## 3. Blinkit and Instamart sell-out

**What we found**

| | Blinkit (`Blinkit all time sales Data.xlsx`) | Instamart (`Instamart sales.xlsx`) |
|---|---|---|
| Sheets | 15 monthly, Jul 2025 – Sep 2026 | 18 monthly, Apr 2025 – Sep 2026 |
| Layouts | **12 different column layouts** | 3 layouts, plus 4 sheets with **no header row** (Aug–Nov 2025) |
| Sales-report sheets | Sep 2025 – Mar 2026 and May – Sep 2026: contract columns except that the SKU column is named `Elle SKU` / `SKU` / `elle sku` / `SKU ID` (one sheet adds `S.No.` or `Expansion Level`) | 10 sheets match the contract exactly; others name SKU `elle sku` / `SKU ID`; Jul 2025 lacks `Elle SKU` and `COMBO` |
| Settlement sheets | **Jul 2025, Aug 2025, Apr 2026 are payout/settlement reports**: commission, shipping, TCS/TDS, payout, settlement date, **customer name (PII)**; Jul/Aug 2025 have no SKU column at all | — |
| Dates | four different encodings: text "2 July 2025", real dates, Excel serial numbers (46024), ISO text | real dates, but the first column is an unnamed row counter |
| Rows | ≈ 722 | ≈ 6,487 |

**Recommendation: two tracks**
1. **Going forward (no code):** ask the team to export Blinkit and Instamart sales **from the seller panels in the standard report layout**, one file per month (or per day for inventory). The contracts were verified on that layout. Ask also whether past months can be re-exported the same way; if yes, track 2 isn't needed.
2. **History (small tested tool):** add `loader/normalise_platform_sales.py`. It turns each monthly sheet into one CSV in the exact contract layout. The loader already accepts `.csv`.
   - It changes **only**:
     - header names, via an explicit alias table (`Elle SKU`, `SKU`, `elle sku`, `SKU ID` → `ELLE SKU`; `Order ID` → `Order Id`; …)
     - date encoding, to ISO `YYYY-MM-DD`
     - dropping columns the contract doesn't have
   - Cell values are otherwise copied as text, unchanged.
   - Headerless Instamart sheets get the contract header **only after** a check that the sheet has the expected column count and value patterns. Otherwise the sheet is refused.
   - Missing SKUs are left empty, never guessed:
     - Instamart Jul 2025: SKU filled from `ITEM_CODE` only where other months map that code to exactly one SKU
     - Blinkit Jul/Aug 2025: the same, using `Item ID`
   - **Settlement sheets** are not sell-out reports. Load only their sell-out fields (order, item, date, quantity, status, prices) and **drop the customer name**. Keep the payout columns for a later `BLINKIT_SETTLEMENT` source (gap G-019, marketplace settlements).
   - Every output is written to `MANIFEST.tsv` with the source sheet and the transformations applied, and the original workbook stays in `_originals\`.
   - **Tests:** one fixture per layout; date encodings; headerless detection; refusal on an unexpected layout; PII column never written.
3. Business rules are unchanged:
   - Blinkit counts only `DELIVERED` lines (BR-018).
   - Sell-out is demand, never added to revenue (BR-024).
4. **Mart:** add `v_partner_sellout_daily` (day × platform × city × SKU: units, orders, MRP and selling value) so the dashboards can show quick-commerce demand.

*Blinkit and Instamart inventory exports were not found. They need daily saving from now on (§6).*

---

## 4. Dispatch → shipments (order fulfilment)

**What we found** in `Dispatch order report 1 Apr.2025 to 15 Sep.2026.xlsm`:
- 45,246 outbound deliveries covering every month from Apr 2025 to 15 Sep 2026, with **all 46 columns matching the draft contract**.
- `Outbound Delivery No` is unique, and every date is a real Excel date-time.
- Status values: delivered 37,243 · Shipped 4,778 · RTO Delivered 1,905 · Shipped & Cancelled 1,199 · RTO initiated 45 · attempted 38 · in transit 14 · lost 11 · out for delivery 6 · open 4.
- Site Location (channel): Shopify, Amazon Easyship, Myntra, Tata Cliq (+ Mall, Mall-Furniture), Nykaa Fashion, Amazon Flex, Pepperfry, Nykaa.
- Couriers: Delhivery (3 services), ShipRocket, Gati, By Hand. 44% of rows have no transporter.
- **8,263 rows (18%) list several SKUs in one cell** with one combined quantity.
- `Invoice No` (filled on all but 6 rows) has the same form as ERP bill numbers (e.g. `JPR25NF-S002`), so shipments can be linked to invoice lines.
- No scientific-notation IDs were found in this file.

**Changes:**
1. **Reader:** accept `.xlsm` the same way as `.xlsx`. openpyxl reads values only and macros are never run. Add a test. *(Alternative with no code: open the file in Excel and save a copy as `.xlsx`.)*
2. **Contract:**
   - Mark `WMS_DISPATCH` as **verified** against this file.
   - Set the business date format to `excel_datetime`; the draft said `text_mdy_time` (issue D-099).
   - Regenerate it through `build_contracts.py` like the others.
3. **Reference data:**
   - `ref.channel_alias` rows for `WMS_DISPATCH` / `Site Location`.
   - Shipment-status and payment-type code mappings in `seeds/ref_code_mapping.csv`.
   - `coverage_check.py` must then report MISSING = 0.
4. **Staging:** a new `stg.wms_dispatch` step that does the following:
   - Parses the date-times.
   - Maps status to `shipment_status` plus `is_rto`.
   - Maps Order Type to `payment_type`.
   - Maps Site Location to a channel.
   - Maps Transporter, falling back to Ext Transporter Name, to a courier.
   - Keeps the pincode.
   - **Does not carry customer name, address, phone or email** beyond raw.
   - Applies the latest batch per delivery number.
5. **Core** (in `30_facts.sql`, after sales):
   - **`fact_shipment`**: one row per delivery. Fulfilment location = Bagru (BR-017). Order, channel and courier keys are resolved through `dim_order` (WMS order no / extern order no) and the invoice number. Unknowns map to -1 (BR-027).
   - **`bridge_shipment_sku`**: split the SKU cell. Quantity per SKU comes from:
     - the row itself for single-SKU rows (`SINGLE_SKU_ROW`)
     - the matching invoice line, via Invoice No + SKU (`INVOICE_LINE`)
     - otherwise `UNALLOCATED` (never guessed)
   - Add both tables to `CORE_TABLES` in `transform/__main__.py` so the run reports their counts.
6. **Quality checks** (`50_dq.sql`):
   - ERROR `shipment_rows_reconcile`: staged deliveries in the period = fact rows.
   - WARN checks: `unknown_channel` / `unknown_courier` for WMS, `shipment_without_invoice_match`, `multi_sku_unallocated`.
7. **Mart:** `v_fulfilment` with one row per delivery:
   - order → pick → pack → ship hours, ship → deliver days, `shipped_after_ship_by` (SLA)
   - RTO flag
   - channel, courier, payment type, destination pincode and state, month
8. **Registers:**
   - Close gap G-003 (the full dispatch export was received) and update coverage notes.
   - Turn on the fulfilment process.
   - Add column definitions for any new columns.
9. **Tests:**
   - transform fixtures for single and multi-SKU rows
   - an RTO status
   - an unknown courier
   - a missing invoice
   - a rerun that produces stable counts

---

## 5. Other things to settle before or while loading

| Item | Recommendation |
|---|---|
| **Version control** | The warehouse folder is **not a git repository**, but its README relies on "review in git". Run `git init` and make a first commit of the current state before any change, so every fix is reviewable and reversible. Keep `.env` and the exports out of git. |
| **Practice database** | Do the first full load on a **separate trial database** (`createdb ellementry_dw_trial`, `build_db.sh`, `load_seeds.sh`). Only when totals reconcile, repeat on `ellementry_dw`. Take a `pg_dump` of `ellementry_dw` first. |
| **Period end** (`prototype_period_end` = 15 Sep 2026) | Keep 15 Sep for the first load: every source covers it. Move it forward only when all sources are exported to the same later date. Otherwise Sep–Oct would look complete for retail but empty for everything else. |
| **Product master as-of** | `--as-of 2026-09-15` ("september updated"; confirm with the product team). |
| **ERP item master** (`Product Master List 13-10-2026`, 5,711 items, with COST and CATEGORY) | A separate future source (`ERP_ITEM_MASTER`) for product cost (G-021) and attributes (G-011). Not needed for the first load. |
| **Credentials** | Before any loading, remove the plain-text database URLs from the comments in `ellementry_source_code\.env` and rotate those passwords (see the review, §6). Loading and transforms need the admin login; never use it from Ellementry Analytics. |

---

## 6. Do today: start saving stock reports daily
History can't be re-exported (BR-021, G-001). Every day not saved is lost for good.
- Each business day, save the **ERP Channelwise Stock report**, **Blinkit inventory** and **Instamart inventory** into `ellementry_exports\snapshots\YYYY-MM-DD\`.
- This needs no code, only an owner on the ERP team.

---

## 7. Load runbook (after §2–§4 are done; trial database first)

```bash
# from ellementry_dw/, with the admin connection in the environment (never printed)
python -m loader load PRODUCT_MASTER         master/PRODUCT_MASTER__2026-09-15.xlsx         --as-of 2026-09-15
python -m loader load ERP_RETAIL_SALES       transactional/FY2025-26/ERP_RETAIL_SALES__...xlsx
python -m loader load ERP_RETAIL_SALES       transactional/FY2026-27/ERP_RETAIL_SALES__...xlsx
python -m loader load ERP_DOMESTIC_SALES     ... (FY25-26, then FY26-27)
python -m loader load ERP_RETAIL_RETURN      ... (FY25-26, then current FY)
python -m loader load ERP_DOMESTIC_RETURN    ...
python -m loader load ERP_STOCK_TRANSFER_OUT ...
python -m loader load ERP_STOCK_TRANSFER_IN  ...
python -m loader load ERP_PURCHASE_ORDER     state/...FY2025-26...xlsx  --as-of <confirmed date>
python -m loader load ERP_PURCHASE_ORDER     state/...FY2026-27...xlsx  --as-of <confirmed date>
python -m loader load ERP_INVENTORY_SNAPSHOT snapshots/ERP_INVENTORY_SNAPSHOT__2026-09-15.xls --as-of 2026-09-15
python -m loader load WMS_DISPATCH           fulfilment/WMS_DISPATCH__...xlsm
for f in sellout/BLINKIT_SALES__*.csv;   do python -m loader load BLINKIT_SALES   "$f"; done
for f in sellout/INSTAMART_SALES__*.csv; do python -m loader load INSTAMART_SALES "$f"; done
python -m loader batches
python -m transform run ellementry_dw_trial      # ERROR checks must pass; read every WARN
```

---

## 8. How we'll know the numbers are right
1. **Independent totals.** Compute monthly totals directly from the files with pandas, applying the documented rules:
   - retail value `PRODDOCVALUE` and domestic `Taxable` (excl. GST)
   - returns by credit-note date
   - cut-off 15 Sep 2026
   - internal partners excluded

   Compare them with `mart.v_net_sales_daily` / `v_returns_daily` to the rupee. Do the same for units in transit and the stock at Bagru.
2. **PRD control totals.** The sample period (Apr – 15 Sep 2026) must reproduce:
   - retail net sales **₹4,22,80,208.54**
   - Bagru trading stock **82,509** units
   - **2,794** units in transit
3. **Quality checks.** Read every WARN result in `mart.v_data_quality_latest` and log real issues in the Data Issues log. Never adjust numbers to make them match.
4. **Business sign-off.** Two business users compare a sample month against their own Excel (PRD TC-DSH-04).
5. **Existing tests.** The warehouse test suites still pass: 78 schema + 49 loader + 6 seed + 8 transform, plus the new tests from §2–§4.

## 9. After the load: Ellementry Analytics
- **Sync** workspace 34 (or wait for the hourly sync). Then import the new views as datasets: `v_partner_sellout_daily`, `v_fulfilment`, `v_return_inwards`, plus the `v_sales_orders_daily` proposed in the review.
- **Check** the column types, metrics and relationships against real rows.
- **Continue** with `EXECUTIVE_DASHBOARD_PLAN.md`.

---

## 10. Work breakdown and decisions

| # | Work | Where | Size | Depends on |
|---|---|---|---|---|
| 1 | `git init` + first commit; `pg_dump` backup | warehouse | S | — |
| 2 | Clean exports folder + MANIFEST | your PC | S | — |
| 3 | PO: contract, migration 110, `document_type`, per-PO staging fix, mart filters, BR-031 proposed, tests | warehouse | M | 1 |
| 4 | Reader `.xlsm`; WMS contract verified; shipment staging, fact, bridge, DQ, `v_fulfilment`; seeds; tests | warehouse | M–L | 1 |
| 5 | Platform-sales normaliser + tests + `v_partner_sellout_daily` (or re-exports instead) | warehouse | M | 1, business answer |
| 6 | Trial database: build, load (§7), transform, reconcile (§8) | warehouse | M | 2–5 |
| 7 | Load into `ellementry_dw`, sync Ellementry Analytics | both | S | 6 |

**Decisions needed from you or the business:**
1. Confirm that `Document Remark` = Purchase/Return is reliable enough to become rule BR-031.
2. The real export dates of the two PO files (D-094).
3. Blinkit/Instamart history: try re-exports first, or build the normaliser now?
4. Keep the period end at 15 Sep 2026 for the first load (recommended)?
5. Who saves the daily stock reports, starting now?
