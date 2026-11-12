# Warehouse review, 12 Nov 2026

A read-only review of `ellementry_dw` (schema 2.16), the files in `exports/` and the issue log, against how the app is used now. Nothing was changed. Numbers are from the live warehouse on 12 Nov 2026.

**Status, 12 Nov 2026 (after the owner's reply):** everything in section 5 that needed no decision is done in warehouse schema 2.17 and is live: Amazon self-shipped returns loaded, the ERP stock movement summary loaded (59,450 of 86,832 gap units explained), Instamart stock shown as a floor (at least 4,770 units), Titan, Culver Max, Expo Digital and Natures Basket classified as B2B (unclassified sales Rs 5.89 Cr -> Rs 2.17 Cr), registers tidied (92 solved, 35 unsolved). Still with the owner: near-free lines, one-off B2B buyers, the discontinued split, the monthly refresh.

Limits the owner has stated, taken as fixed:
- Stock comes as month-end reports. Daily stock uploads are not possible.
- Instamart's past inventory cannot be fetched.
- Blinkit is parked until the new seller arrangement produces data.

## 1. Verdict

The structure is sound and needs no redesign: one-way layers, contract-checked loads, 28 of 28 totals reconcile to the files, no ERROR check fails. What has fallen behind is around it:

1. **The data stops on 15 Sep 2026.** The warehouse still runs on the fixed "prototype period" (1 Apr 2025 to 15 Sep 2026). Every dashboard, and all 298 open alerts, describe 15 Sep. Only retail sales were exported further (to 21 Oct); they are excluded by the period.
2. **Files were received and never loaded** (section 2).
3. **Several open issues can be closed or narrowed with data already here** (section 3).
4. **The registers are out of date**: gaps that are solved still show as open, and limits that are now accepted still read as "waiting".

## 2. Files received but not used

| File (in `exports/_originals/`) | What it holds | What it would fix |
|---|---|---|
| `return_data_2026-11-03/amazon/self fullfilled/` (9 reports) | 1,877 Amazon self-shipped return lines, 2,078 units, Rs 14.8 L refunded, 1 Apr 2025 to 14 Sep 2026, with return reason, return type and resolution | Return reasons for Amazon self-shipped orders (D-079). 439 lines are "Rejected" or "Undelivered", which is the RTO the WMS never records for Amazon (D-112) |
| `return_data_2026-11-03/amazon/FBA/486013020760.csv` | Amazon FBA returns to 31 Oct 2026: 3,632 lines (3,499 loaded, to 14 Sep) | Newer return reasons once the period moves |
| `erp_2026-11-02/DocumentWiseStockMovement_consolidated...xls` | Per product, whole period, all locations: quantity by ERP document type (scrap, increase / decrease stock, inventory transfer, subcontract) | Was used once by hand to explain 80% of Bagru's gap (D-124). Not a source, so the stock check still reports the full gap |
| `Retail Sales FY 26-27.xlsx` | Retail sales to 21 Oct 2026 | Loaded to raw; 4,999 rows excluded by the period end |

## 3. Issues that can move with the data in hand

**Instamart and partner stock (D-125, D-080).** The rebuilt balance assumes zero opening stock. The running balance per product shows that cannot be true: for 21 of 42 Instamart products the balance goes below zero. So Instamart held **at least 1,541 units on 1 Apr 2025**, and at least 4,770 on 15 Sep 2026 (the dashboard shows 3,229). The same test gives Shoppers Stop at least 503 units of opening stock and Design Estate 185; the other franchises under 100 each. This is a floor, not the true figure. To get the true figure without any history: **one** stock download from the Instamart portal on any day (and one stock count per partner), then work backwards from invoices, returns and sell-out. That needs sales loaded up to that day (point 1).

**Unclassified customers, Rs 5.89 Cr (D-019).** 355 names. Eight names with 13 or more bills hold Rs 4.15 Cr: Titan Company Rs 2.52 Cr, Culver Max Entertainment Rs 0.93 Cr, Blink Commerce Rs 0.22 Cr, Expo Digital India Rs 0.21 Cr, then Natures Basket, Madhur Mangal, The Home Story, Smart Arts. Another 211 names have one to three bills and no returns at all (Rs 0.88 Cr): one-off B2B or gifting buyers. A rule "outright B2B by evidence" (few bills, no returns, never restocked) would classify those; the owner confirms the eight big names. Blink Commerce is Blinkit and stays parked.

**Near-free lines (D-023).** 1,056 lines billed with a 99-100% discount: 822 on retail channels (1,025 units) and 231 to unclassified accounts (**22,671 units**). Their value is nil, but the units count as units sold and as demand in days of cover. The proposal in the log (flag as free / sample issue, leave out of demand) can be applied on the owner's yes.

**Bagru stock with no document (D-124).** Still 53,975 units arrived and 96,195 left without a document, mostly in May 2025 (16,911 left), Oct 2025 (13,379) and Apr 2026 (11,390). The movement report explains most of it by product for the whole period, not by month. Loading it as a whole-period source would let the stock check show "explained by scrap / adjustment / subcontract" beside each product, and leave only the real remainder.

**Product status.** Status comes from the Final Master of Sep 2026: 472 continued, 3,548 discontinued, 340 trading products not in it. In the last three months, products marked discontinued sold **Rs 98.9 L** (554 products) against Rs 258.6 L for continued ones, and they hold Rs 1.49 Cr of stock. The stock-out and low-cover alerts only look at continued products. Either the master is out of date or "discontinued" means "sell through, don't reorder"; the owner needs to say which.

**Small ones that can be closed.**
- Negative stock (D-118): 3 rows, 12 units on 15 Sep 2026. Close as "shown as reported".
- Daily stock (D-004, G-001): replace with "stock is month-end by design".
- G-027 (per-receipt GRN data) and G-021 (product cost): both solved by schema 2.14 and 2.8 but still OPEN in `meta.data_gap`. The check `po_lines_with_several_receipts` still warns about the old PO receipts although the GRN register replaced them.
- Transfers with an unknown location (D-072, D-127): 139 lines at Bagru, 1,929 units in and 1,756 out. One answer from the owner closes both.

## 4. What cannot be solved from here

| Issue | Why | Option |
|---|---|---|
| Delivery dates and RTO for Nykaa, Flipkart, FNP, Myntra, Tata Cliq (D-112, D-113) | Not in the WMS report | Seller-panel or courier exports, or accept "tracked channels only" |
| Franchise and Shoppers Stop sell-out (D-006) | No source | Partner balances stay off the stock tiles |
| Amazon's own FBA stock (D-052) | Not exported | ERP view only |
| Location columns on transfers (D-038) | The ERP report has none | Keep the prefix table |
| Blinkit (D-005, D-050, D-051, D-092) | Parked | Revisit with the new arrangement |

## 5. Recommended changes

**Warehouse**
1. **Monthly refresh in place of the fixed period.** Period end becomes the last month-end with a full set of files. One checklist per month: the eight ERP reports, the month-end stock report, the WMS dispatch report, Instamart sell-out, the two Amazon return reports. Stock dashboards and alerts say "as of <month-end>".
2. **New source: Amazon self-shipped returns**, into the existing return-reasons table, with a "not delivered" flag.
3. **Partner stock:** a minimum opening balance per product from the running balance, labelled "at least"; and a place to load one stock count per partner as an anchor.
4. **Whole-period movement source** for the Bagru explanation.
5. **Rules on the owner's yes:** outright B2B by evidence; near-free lines out of demand.
6. **Register clean-up:** close solved gaps, re-word accepted limits, retire the stale check, then re-import the issue list into the app.

**App (no warehouse change)**
7. The three dashboard fixes already listed in `context/08`: sales segment labels, Days of cover without partner balances (Rs 1.60 Cr overstated), a customer-only return rate.

Order: 6 and 2 first (no decisions needed), then 3 and 4, then 5 and 7 after the owner's answers, then 1, which needs fresh exports.
