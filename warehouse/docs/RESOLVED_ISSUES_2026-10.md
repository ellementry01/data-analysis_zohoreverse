# Resolved data issues — October 2026

> **Current log:** [`ISSUE_LOG.md`](ISSUE_LOG.md) / [`Data_Issues_and_Doubts_Log_2026-10-30.xlsx`](Data_Issues_and_Doubts_Log_2026-10-30.xlsx), with every issue under Solved or Unsolved. This write-up covers schemas 2.4-2.7 only.

The issues fixed in the warehouse (schemas 2.4 to 2.7, 22–26 Oct 2026) for the Stock, Fulfilment and Purchasing &
transfers dashboards, and how each was fixed.

- **Status in the issue log:** each one is recorded in [`Data_Issues_and_Doubts_Log_2026-10-26.xlsx`](Data_Issues_and_Doubts_Log_2026-10-26.xlsx).
- **Still open:** issues that need information from the business or the ERP team stay open in that log. They're listed
  at the end.

**How every change was made:**
1. Back up `ellementry_dw`.
2. Add a numbered, additive migration (`sql/1x0_*.sql`).
3. Test on the trial copy `ellementry_dw_trial`.
4. Apply to `ellementry_dw`.
5. Run the transform and reconcile against the export files (28 of 28 checks).
6. Re-check the dashboard KPIs against direct SQL.

The original Excel exports are kept unchanged in `exports/_originals/`, with checksums in `ORIGINALS.tsv`.

---

## Summary

| Log ID | Issue | Fix | Schema | Result |
|---|---|---|---|---|
| D-110 | Retail bill numbers restart every April, so FY 25-26 bills were dropped | Bill = number + financial year | 2.6 | +2,086 lines, +₹26.1 lakh |
| D-109 | WMS invoice numbers don't match ERP bills | Link by marketplace order ID, then AWB | 2.5 | 24,893 → 45,171 of 45,246 linked |
| D-059 | Several SKUs in one dispatch row | Quantities from linked bills + two exact rules | 2.5–2.7 | 2,799 → 4 unknown |
| D-053 | Products without a category | Fill from the ERP item master | 2.4 | 2,278 → 60 |
| D-116 (part) | Stock value silently ₹0 for SKUs with no MRP | Leave them out of value; own tile | 2.4 | 14,474 units shown apart |
| D-112 (part) | RTO rate understated (4.3%) | Measure on channels that record RTO | 2.4 | 7.9% (website) |
| D-113 (part) | Delivery time included untracked channels | Measure on channels that report deliveries | 2.4 | Nykaa, FNP, Flipkart excluded |
| D-111 | 39 courier spellings | Map to about 10 companies | 2.4 | Confirmation pending |
| D-114 | Weights up to 265,650 kg | Drop weights over 100 kg | 2.4 | 85 rows |
| D-039 (part) | "Never received" transfers mixed FBA with real gaps | Split Amazon FBA vs own locations | 2.4 | 1,441 real exception units |
| D-083/094 (part) | Overdue days from an assumed PO export date | Label them | 2.4 | 26 lines flagged |
| D-121 (part) | PO lines with no due date | Label "No due date" | 2.4 | 223 lines |
| D-120 | Over-received PO lines hidden | New view and dashboard table | 2.4 | 24 lines, 5,056 units |
| D-119 | Days of cover overstated Bagru | Count transfers out as demand | 2.4 | Realistic cover |

"(part)" means the dashboard now shows the number correctly, but the missing data itself still has to come from the business.

---

## 1. Retail bill numbers restart every financial year (D-110, schema 2.6)

**Problem.**
- The ERP restarts bill series every April, so `IN-1` exists in FY 25-26 and again in FY 26-27.
- Staging kept, per bill number, only the rows from the newest file.
- 1,911 FY 25-26 bills whose numbers reappeared in FY 26-27 were silently replaced: 2,086 lines, ₹26.1 lakh excl. GST, all in Apr–Jul 2025.
- `reconcile.py` built its totals with the same "latest file per bill number" rule, so it agreed with the warehouse and reported 28/28.

**How it was found.**
- 1,927 Amazon deliveries would not link to any bill, although their order IDs were present in the raw FY 25-26 sales file.

**Fix.**
- **Line identity:** a bill is its number within a financial year. `fact_sales_line.bill_fy_start` (2025 = FY 25-26) is part of the line's identity.
- **Staging:** keeps the latest file per (bill number, financial year).
- **Returns:** link to the latest bill of that number dated on or before the return.
- **Deliveries:** link to bills by (number, financial year).
- **`reconcile.py`:** builds its totals with the same key. Lesson: a check must not reuse the logic it is checking.

**Files.** `sql/140_bill_financial_year.sql`, `transform/sql/10_stg_sales_returns.sql`, `transform/sql/30_facts.sql`, `reconcile.py`.

**Result.**
- Retail invoice lines: 91,460 → 93,546.
- Retail sales Apr 2025 – Sep 2026: ₹13.66 Cr → ₹13.92 Cr.
- Returns linked to their sale: 15,848 → 16,229.

## 2. WMS invoice numbers don't match ERP bills (D-109, schema 2.5)

**Problem.**
- For marketplace orders, the WMS "Invoice No" is the marketplace's own invoice: `M25-…`, `M26-…`, `M44-…`.
- Only website invoices matched an ERP bill: 24,893 of 45,246 deliveries.

**Common key found.**

| WMS column | ERP column | Deliveries matched |
|---|---|---|
| Extern Order No | Retail `ORDER_NUMBER` / `DOCREFNUM` (domestic `DOCREFNUM`), i.e. the marketplace order ID such as `171-1241224-6101921~TgbV8dh2V` | 45,240 of 45,246 |
| Tracking No | the bill's `AWB` / `AWBNO` | 45,229 |

**Fix.**
- **Linking order:** each dispatch row links to its ERP bill(s) by Invoice No first, then Extern Order No, then the AWB.
- **New columns:** `fact_shipment.sales_bill_number` and `sales_link_method` (`INVOICE` / `ORDER` / `AWB` / `NONE`).
- **Mart:** both columns are exposed in `v_fulfilment`.

**Files.** `sql/130_shipment_sales_link.sql`, `transform/sql/10_stg_sales_returns.sql` (staging now carries the order reference and AWB), `transform/sql/30_facts.sql`, `transform/sql/50_dq.sql`, `transform/sql/70_marts.sql`.

**Result.** After the 2.6 fix, 45,171 of 45,246 deliveries link to a bill. The 75 left have their bill outside the loaded period, or the bill wasn't exported.

## 3. Several SKUs in one dispatch row (D-059, schemas 2.5–2.7)

**Problem.** A dispatch row can list several SKUs with one combined quantity.

**Fix, in order:**
1. **Single SKU:** the row quantity.
2. **Invoice line:** the SKU's quantity on the linked bills, now including bills found through the order ID (2.5) and FY 25-26 bills (2.6).
3. **One each (2.7):** the row quantity equals the number of SKUs listed, so each SKU shipped exactly 1.
4. **Remainder (2.7):** only one SKU is unknown, so it gets the row quantity minus the others.
5. **Otherwise:** left `UNALLOCATED`, never split by guess.

**Files.** `sql/150_shipment_sku_quantity_rules.sql`, `transform/sql/30_facts.sql`.

**Result.**
- Unknown SKU lines: 2,799 → 338 (2.5) → 31 (2.6) → 4 (2.7).
- The 4 left are two deliveries of 2 SKUs sharing 3 units, which the data can't split.

## 4. Products without a category (D-053, schema 2.4)

**Problem.** 2,278 products had no category in any loaded source.

**Fix.**
- **New source:** the ERP item master (`Product Master List 13-10-2026 11.51.xlsx`, source `ERP_ITEM_MASTER`), with a contract and a raw table.
- **Fills gaps only:** it fills category, sub-category, HSN, EAN and MRP only where no better source has a value. It never overrides the Final Master, the stock report or invoices.
- **Labels:** `category_label` reads "Uncategorised" for the rest.

**Files.** `sql/120_supply_dashboard_fixes.sql`, `loader/contracts/ERP_ITEM_MASTER.json`, `transform/sql/11_stg_supply.sql`, `transform/sql/20_dims.sql`.

**Result.** 2,278 → 60 without a category. No trading stock is uncategorised.

## 5. Stock with no MRP was valued at ₹0 (D-116, schema 2.4)

**Problem.** 103 trading SKUs (14,474 units) have no MRP in any source, so they added nothing to stock value, silently.

**Fix.**
- `v_stock_position_latest.stock_value_mrp` is NULL, not 0, for these items, and `mrp_status` says "MRP missing".
- A new metric, `stock_units_no_mrp`, drives a "Units with no MRP" tile on the Stock dashboard.
- The item master supplied MRPs for 2 SKUs.

**Still open.** MRPs for the 103 SKUs, and finance's decision on the MRPs that differ between locations (828 SKUs; list in `reports/S2_mrp_differences_by_location.csv`).

## 6. RTO and delivery time measured on channels that don't report them (D-112, D-113, schema 2.4)

**Problem.**
- Marketplace returns-to-origin never reach the WMS, so the all-channel RTO rate read 4.3%, while the website alone is 7.9%.
- Nykaa, FNP and Flipkart send no delivery dates.

**Fix.** Tracking scope is computed per channel from the data at each build:

| Flag | A channel counts as tracked when… |
|---|---|
| `is_rto_tracked` | RTO is recorded on at least 1% of its deliveries |
| `is_delivery_tracked` | at least half its shipped deliveries carry a delivery date |

- **Metrics:** the `rto_rate` and `avg_ship_to_deliver_days` metrics filter on these flags.
- **Labels:** untracked channels show blank, not 0%, and the dashboard says why.

**Still open.** Marketplace RTO and delivery reports.

## 7. Courier names (D-111, schema 2.4)

**Problem.** 39 spellings for about 10 couriers.

**Fix.**
- `ref.code_mapping` domain `COURIER` maps each spelling to `dim_courier.courier_group`.
- Marketplace codes were mapped from evidence, for example:
  - **ATS → Amazon Shipping:** it appears only on Amazon orders.
  - **XC → Xpressbees:** its tracking numbers start with 1413.
- A WARN check, `courier_unmapped`, catches new spellings.

**Still open.** The mappings are marked unconfirmed until the business reviews them.

## 8. Weight outliers (D-114, schema 2.4)

**Problem.** 85 deliveries over 100 kg; the largest is 265,650, probably grams typed as kilograms.

**Fix.**
- `v_fulfilment.weight_kg` is NULL above 100 kg.
- A WARN check, `shipment_weight_suspect`, reports them.

## 9. Transfers "never received" (D-039, schema 2.4)

**Problem.** Transfers with no inward entry mixed two different things:
- shipments to Amazon FBA, which Amazon receives without posting an ERP entry
- real gaps at own locations

**Fix.** `v_transfer_in_transit` gains three columns:
- **`destination_group`:** To Amazon FBA / To own locations
- **`transit_status`:** 60 days or less / not received after 60 days
- **`receipt_note`**

The dashboard shows FBA apart, and lists own-location exceptions by route.

**Result.** The real exceptions are 1,441 units at own locations. 3,350 FBA units are likely received but unconfirmed.

## 10. Purchase-order flags (D-083/D-094, D-120, D-121, schema 2.4)

- **Export date assumed.**
  - `meta.load_batch.as_of_is_assumed` records it: the loader's `--as-of-assumed` flag, set automatically from the manifest note.
  - Open lines from that export show `due_status` "Overdue (export date assumed)".
- **No due date:** `due_status` reads "No due date".
- **Over-received:** a new view, `v_purchase_order_lines`, adds `is_over_received` and `over_received_qty`. A table on the Purchasing & transfers dashboard lists the 24 lines.

## 11. Days of cover (D-119, schema 2.4)

**Problem.** Cover counted only sales, so Bagru, which feeds the stores and FBA by transfer, looked like years of stock.

**Fix.** Cover = sellable stock ÷ (sales + transfers out) per day over the last 30 days. `avg_daily_transfer_out_30d` is shown alongside.

---

## Still open: needs the business or the ERP team

The issue log has the full list and owners. The main items for these dashboards:

| Issue | What's needed | From whom |
|---|---|---|
| Daily stock history | Save the stock report every day (G-001, D-004) | ERP / ops |
| SKUs with no MRP | MRPs for 103 SKUs | Merchandising |
| MRP differs by location | Which MRP is official (D-117) | Finance |
| Missing stock-report locations | Include the 7 locations (D-085) | ERP team |
| Blinkit / Instamart / Amazon stock | Their inventory reports (D-052) | Marketplace team |
| Partner opening stock | Balances at 1 Apr 2025 (D-080) | Accounts |
| Marketplace RTO and delivery dates | Seller-panel reports (D-112, D-113) | Marketplace team |
| Supplier classification | Factory list (D-044) | Purchasing |
| Purchase vs return PO lines | Confirm rule BR-031 (D-100) | Purchasing |
| PO export date | Real date or a fresh export (D-094) | ERP team |
| Receiving location on goods receipts, GRN register | ERP export changes (D-047) | ERP team |
| Courier and location mappings | Review the unconfirmed mappings (D-111) | Ops |
| "Ellementry International" channel | Which channel it is (D-115) | Sales |
