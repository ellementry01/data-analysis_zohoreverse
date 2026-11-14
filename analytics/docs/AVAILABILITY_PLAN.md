# Stock availability: plan (14 Nov 2026)

**Goal.** For every product we keep selling, show the stock we have, the stock we should have (the "ideal"), and how much to reorder when we are below the ideal. A **Check availability** button on the Stock dashboard opens this comparison.

Status: **plan agreed by the owner on 14 Nov 2026 (section 6), nothing built yet.**

## 1. The rule in plain words

- A new order takes about **45 days to make** (MLT, manufacturing lead time) plus **15 days in transit and buffer**: 60 days in all.
- So at any time we should hold at least **60 days of sales** of each product. That is the **ideal stock**.
- If what we have (in the warehouse, plus what suppliers still owe us on open purchase orders) is below the ideal, a **reorder** is due.
- The reorder quantity is the shortfall, **rounded up to the supplier's MOQ** (minimum order quantity).

```
daily sales      = units sold in the last 12 months, every channel except B2B bulk / 365
target days      = MLT of the product + 15 days transit and buffer       (45 when the sheet has no MLT)
ideal stock      = daily sales x target days
we have          = sellable stock at Bagru + pending quantity on open purchase orders
shortfall        = ideal stock - we have                                 (nothing to do when 0 or less)
reorder quantity = shortfall rounded up to a multiple of the MOQ
status           = Reorder now     (we have < ideal)
                   OK              (ideal up to 3 x ideal)
                   Too much stock  (more than 3 x ideal: candidates to push or liquidate)
                   No recent sales (sold nothing in the window: no ideal can be worked out)
```

## 2. What the attached file is

`12-11-26 (1).xls` (dated 12 Nov 2026) is the reorder sheet the team keeps by hand. It has **485 products**, all of them already known to the warehouse:

| What the sheet gives | Filled | Used for |
|---|---|---|
| Factory (supplier) name, 28 factories | 481 of 485 | grouping the reorder list by supplier |
| MOQ (15 to 300, mostly 100 / 200 / 300) | 475 | rounding the reorder |
| MLT in days (45: 210 products, 60: 138, 75: 21, 90: 99, 30: 4) | 475 | target days |
| Grade (A, B, C), top 40, replacement product, launch date | most | filters and sorting |
| Warehouse stock and PO pending on 12 Nov | all | see choice 4 |
| Sales: shop-in-shop, own stores, franchise stores only | all | see choice 1 |

How the sheet works today (worked out from its numbers, it matches on every row):
- daily sales = one year of shop-in-shop + own-store + franchise sales / 365. **Online, Amazon, Instamart and B2B sales are not in it.**
- it keeps **2.25 months of sales, doubled** (about 135 days), then reorder = stock + PO pending - that amount.

The new screen replaces this with the 60-day rule above, worked out from the warehouse every time the data is refreshed.

The sheet lists 472 products the warehouse calls continued, 10 discontinued and 3 not in the product master. Discontinued products are left out of the reorder check (they are not reordered); they still show on the Stock dashboard.

## 3. What it would show today

Rough check on the warehouse data (stock on 15 Sep 2026, open purchase orders, continued products only):

| Sales counted | Daily units | Products below ideal (MLT + 15) | Reorder units, MOQ-rounded |
|---|---|---|---|
| All channels, last 6 months | 308 | 104 | 15,387 |
| All except B2B bulk and unknown, last 6 months | 198 | 94 | 13,386 |
| All except B2B bulk and unknown, last 12 months | 240 | 107 | 14,949 |
| Only shop-in-shop, own and franchise stores, 12 months (as the sheet) | 147 | 99 | 14,027 |

A flat 60 days instead of MLT + 15 gives 5 to 10 fewer products below ideal.

**Two numbers do not agree and need explaining before the screen is trusted:**
- Stock: the sheet says **117,308 units** in the warehouse on 12 Nov; the ERP's Bagru report says **49,338 sellable** on 15 Sep. Either a lot arrived in two months, or the sheet counts more than Bagru's sellable stock.
- Open orders: the sheet has **75,894 units** pending; the warehouse's open purchase orders have **103,732** (some may be old orders that will never arrive).

## 4. How it will be built

**Warehouse (`ellementry_dw`, schema 2.18, tried on the trial copy first):**
1. A normaliser for the sheet (`loader/normalise_planning_master.py`): keeps only the planning columns (product code, factory, MOQ, MLT, grade, top 40, replacement, launch date, status group) and drops prices and margins. It fails loudly if the layout changes. Contract `SKU_PLANNING_MASTER`; the file goes to `exports/master/` (never into git).
2. Table `core.dim_product_planning`: one row per product per sheet date, so a new sheet each month keeps the history.
3. Settings in `meta.pipeline_setting`: transit and buffer days (15), MLT when missing (45), sales window, which channels count, "too much stock" multiple (3).
4. View `mart.v_stock_availability`: one row per continued product with stock, on order, daily sales, target days, ideal, shortfall, MOQ-rounded reorder, status, supplier, grade, and the date the stock figure is from.
5. Data checks: products with no MLT or MOQ (10 today), products in the sheet unknown to the warehouse, continued products missing from the sheet.
6. Tests for the normaliser and the formula (MOQ rounding, missing MLT, no sales, discontinued left out).

**App (workspace 34):**
1. Dataset `stock_availability`, and metrics such as *products below ideal stock*, *reorder units*, *reorder value at cost* and *ideal stock*, so Ask AI can answer "what should we reorder from <factory>?".
2. A new dashboard **Stock availability** (key `stock-availability`):
   - tiles: products checked, below ideal, reorder units, reorder value
   - a bar chart of reorder units by factory
   - a table of every product: stock, on order, sales per month, ideal, shortfall, reorder (MOQ-rounded), status
   - filters for factory, status, grade and category; export to Excel for placing orders
3. A **Check availability** button in the Stock dashboard's header that opens it. The Stock dashboard keeps its id 195 and its widgets; only the button is added.
4. Optional later: an alert rule "fell below ideal stock" in the existing agents, once the numbers have been checked for a month.

**Monthly routine:** download the reorder sheet (or just the planning columns) with the monthly exports, run the load, and the screen updates.

## 5. Order of work

1. Owner answers the four choices below.
2. Warehouse 2.18 on the trial copy, numbers checked against the sheet for a handful of products, then on the live warehouse after a backup.
3. App dataset, metrics, dashboard and button; checked in the browser.
4. Tests, docs, one branch, merge on the owner's sign-off.

## 6. Owner's choices (14 Nov 2026)

1. **Sales counted:** every channel except B2B bulk orders (website, Amazon, Instamart, marketplaces, own, franchise and shop-in-shop stores). Sales with an unknown channel are left out too and counted in a data check.
2. **Period:** the last 12 months.
3. **Target days:** each product's own MLT + 15 days transit and buffer. Purchase orders not delivered yet count as stock on its way: *we have = stock + pending on open purchase orders*.
4. **Stock and open orders:** from the ERP exports in the warehouse, so the figures match the Stock dashboard. The sheet's "PO PENDING" column is loaded as well and used as a cross-check: a data check lists products where the sheet and the ERP disagree on what is still to arrive (75,894 units in the sheet, 103,732 in the ERP's open purchase orders today; old orders that will never arrive should be closed in the ERP).

**Needed from the team:** a November stock report and purchase order report from the ERP (the same reports as every month). Until they are loaded the screen shows stock as of 15 Sep 2026 and says so.
