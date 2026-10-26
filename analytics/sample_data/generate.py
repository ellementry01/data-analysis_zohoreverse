"""Generate a synthetic, deliberately messy multi-table dataset for a home & kitchen goods brand.

Outputs (in this folder):
  products.xlsx (sheet "Product Master" with title rows + sheet "Notes"), warehouses.csv, channels.csv,
  customers.csv, orders.csv, sales_register.xlsx, returns.csv, inventory_movements.csv,
  inventory_snapshots.csv, dispatch.csv, marketing_spend.xlsx
  ground_truth.json  -- answers computed independently with pandas from the CLEAN data.

Run:  python generate.py            (deterministic, seed 42)
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta

import numpy as np
import pandas as pd

OUT = os.path.dirname(os.path.abspath(__file__))
rng = np.random.default_rng(42)
START, END = date(2024, 10, 1), date(2026, 10, 16)
TODAY = date(2026, 10, 17)
DAYS = pd.date_range(START, END, freq="D")

CATEGORIES = {
    "Kitchen": (["Steel Kadai", "Cast Iron Tawa", "Spice Box", "Chopping Board", "Knife Set", "Masala Dabba", "Tea Strainer", "Ladle Set"], (399, 2999), 0.025),
    "Dining": (["Dinner Plate Set", "Serving Bowl", "Copper Tumbler", "Brass Thali", "Cutlery Set", "Table Runner"], (499, 4999), 0.03),
    "Glassware": (["Wine Glass Pair", "Whisky Tumbler", "Glass Jug", "Highball Set", "Decanter"], (599, 3499), 0.09),
    "Decor": (["Terracotta Vase", "Wall Plate", "Brass Diya", "Candle Stand", "Planter Pot", "Photo Frame"], (299, 3999), 0.035),
    "Storage": (["Glass Jar", "Bamboo Basket", "Steel Canister", "Lunch Box"], (249, 1999), 0.02),
    "Bath": (["Soap Dispenser", "Bath Towel", "Ceramic Tray"], (299, 1499), 0.04),
}
FINISHES = ["Classic", "Royal", "Earthy", "Minimal", "Heritage"]


def seasonality(d: pd.Timestamp) -> float:
    s = {10: 1.55, 11: 1.7, 12: 1.25, 1: 0.9, 2: 0.85, 3: 1.1, 4: 0.95, 5: 0.9, 6: 0.85, 7: 0.9, 8: 1.0, 9: 1.1}[d.month]
    if d.dayofweek >= 5:
        s *= 1.2
    return s


# ----------------------------------------------------------------------------------------------- dimensions
products = []
i = 1
for cat, (names, (lo, hi), _) in CATEGORIES.items():
    for n in names:
        for fin in rng.choice(FINISHES, size=4, replace=False):
            price = int(round(rng.uniform(lo, hi) / 50) * 50 - 1)
            products.append({"sku": f"SKU{i:04d}", "product_name": f"{fin} {n}", "category": cat,
                             "unit_price": price, "unit_cost": round(price * rng.uniform(0.35, 0.55), 2),
                             "launch_date": (START - timedelta(days=int(rng.integers(30, 900)))).isoformat()})
            i += 1
products = pd.DataFrame(products)
n_prod = len(products)
pop = rng.zipf(1.6, n_prod).astype(float)
pop = np.minimum(pop, 30) + rng.uniform(0.5, 2, n_prod)
pop /= pop.sum()
# planted story: these products' sales drop by ~55% in the last 3 months while replenishment continues
declining_idx = rng.choice(np.argsort(-pop)[5:60], size=6, replace=False)
declining_skus = set(products.loc[declining_idx, "sku"])

warehouses = pd.DataFrame([
    {"warehouse_id": "WH-DEL", "warehouse_name": "Delhi Central", "city": "New Delhi", "warehouse_type": "Own"},
    {"warehouse_id": "WH-BLR", "warehouse_name": "Bengaluru South", "city": "Bengaluru", "warehouse_type": "Own"},
    {"warehouse_id": "WH-MUM", "warehouse_name": "Mumbai Bhiwandi", "city": "Mumbai", "warehouse_type": "Own"},
    {"warehouse_id": "FR-JAI", "warehouse_name": "Jaipur Franchise Store", "city": "Jaipur", "warehouse_type": "Franchise"},
    {"warehouse_id": "FR-PUN", "warehouse_name": "Pune Franchise Store", "city": "Pune", "warehouse_type": "Franchise"},
])
OWN = ["WH-DEL", "WH-BLR", "WH-MUM"]
channels = pd.DataFrame([
    {"channel": "Shopify", "channel_type": "D2C website", "commission_pct": 2.0},
    {"channel": "Amazon", "channel_type": "Marketplace", "commission_pct": 18.0},
    {"channel": "Flipkart", "channel_type": "Marketplace", "commission_pct": 16.0},
    {"channel": "Retail Store", "channel_type": "Offline", "commission_pct": 0.0},
])
CH = list(channels["channel"])

cities = ["New Delhi", "Gurugram", "Noida", "Bengaluru", "Mumbai", "Pune", "Hyderabad", "Chennai", "Kolkata", "Jaipur", "Ahmedabad", "Lucknow"]
states = {"New Delhi": "Delhi", "Gurugram": "Haryana", "Noida": "Uttar Pradesh", "Bengaluru": "Karnataka", "Mumbai": "Maharashtra",
          "Pune": "Maharashtra", "Hyderabad": "Telangana", "Chennai": "Tamil Nadu", "Kolkata": "West Bengal", "Jaipur": "Rajasthan",
          "Ahmedabad": "Gujarat", "Lucknow": "Uttar Pradesh"}
first = ["Aarav", "Diya", "Vihaan", "Ananya", "Arjun", "Isha", "Kabir", "Meera", "Rohan", "Saanvi", "Aditya", "Kavya", "Ira", "Dev", "Nisha", "Rahul", "Pooja", "Neel", "Tara", "Zoya"]
last = ["Sharma", "Verma", "Iyer", "Reddy", "Kapoor", "Mehta", "Singh", "Nair", "Gupta", "Das", "Joshi", "Khan", "Rao", "Bose", "Patel"]
N_CUST = 2500
cust_city = rng.choice(cities, N_CUST)
customers = pd.DataFrame({
    "customer_id": [f"C{j:05d}" for j in range(1, N_CUST + 1)],
    "customer_name": [f"{rng.choice(first)} {rng.choice(last)}" for _ in range(N_CUST)],
    "city": cust_city,
    "state": [states[c] for c in cust_city],
    "segment": rng.choice(["New", "Repeat", "Loyal", "Corporate"], N_CUST, p=[0.45, 0.3, 0.2, 0.05]),
    "signup_date": [(START - timedelta(days=200) + timedelta(days=int(x))).isoformat() for x in rng.integers(0, 900, N_CUST)],
})

# ----------------------------------------------------------------------------------------------- facts
orders, lines, moves, dispatch, returns = [], [], [], [], []
inv = 0
oid = 0
ch_base = {"Shopify": 11.0, "Amazon": 9.0, "Flipkart": 5.0, "Retail Store": 4.0}
months_from_start = lambda d: (d.year - START.year) * 12 + d.month - START.month  # noqa: E731
last3_start = pd.Timestamp(2026, 7, 1)
flash_day = pd.Timestamp(2026, 3, 14)  # one-day Amazon flash sale (anomaly)

for d in DAYS:
    mi = months_from_start(d)
    seas = seasonality(d)
    for ch in CH:
        trend = {"Shopify": 1 - 0.006 * mi, "Amazon": 1 + 0.03 * mi, "Flipkart": 1 + 0.005 * mi, "Retail Store": 1.0}[ch]
        lam = ch_base[ch] * seas * trend
        if ch == "Amazon" and d == flash_day:
            lam *= 6
        for _ in range(rng.poisson(lam)):
            oid += 1
            order_id = f"ORD{oid:06d}"
            cust = customers["customer_id"].iat[int(rng.integers(0, N_CUST))]
            wh = rng.choice(OWN, p=[0.45, 0.3, 0.25])
            orders.append({"order_id": order_id, "order_date": d.date(), "customer_id": cust, "channel": ch, "warehouse_id": wh,
                           "order_status": rng.choice(["Delivered", "Delivered", "Delivered", "Shipped", "Cancelled"], p=[0.5, 0.3, 0.1, 0.07, 0.03]),
                           "payment_mode": rng.choice(["UPI", "Card", "COD", "Netbanking"], p=[0.5, 0.25, 0.2, 0.05])})
            n_lines = int(rng.choice([1, 1, 1, 2, 2, 3]))
            for _ in range(n_lines):
                p = int(rng.choice(n_prod, p=pop))
                sku = products["sku"].iat[p]
                if sku in declining_skus and d >= last3_start and rng.random() < 0.55:
                    continue
                qty = int(rng.choice([1, 1, 1, 2, 2, 3, 4]))
                price = float(products["unit_price"].iat[p])
                disc = float(rng.choice([0, 0, 5, 10, 15, 20])) if ch != "Retail Store" else float(rng.choice([0, 5]))
                gross = qty * price
                net = round(gross * (1 - disc / 100), 2)
                inv += 1
                lines.append({"invoice_no": f"INV{inv:07d}", "invoice_date": d.date(), "order_id": order_id, "sku": sku,
                              "channel": ch, "warehouse_id": wh, "customer_id": cust, "qty": qty, "unit_price": price,
                              "discount_pct": disc, "gross_amount": gross, "net_amount": net, "transaction_type": "Sale"})
                moves.append({"movement_date": d.date(), "warehouse_id": wh, "sku": sku, "movement_type": "Outbound - sale", "qty": -qty})
                cat_rr = CATEGORIES[products["category"].iat[p]][2]
                if rng.random() < cat_rr and d + timedelta(days=20) <= pd.Timestamp(END):
                    rq = int(rng.integers(1, qty + 1))
                    rdate = (d + timedelta(days=int(rng.integers(3, 21)))).date()
                    returns.append({"return_id": f"RET{len(returns) + 1:06d}", "return_date": rdate, "invoice_no": f"INV{inv:07d}",
                                    "sku": sku, "channel": ch, "warehouse_id": wh, "qty_returned": rq,
                                    "return_reason": rng.choice(["Damaged in transit", "Not as described", "Changed mind", "Wrong item", "Quality issue"],
                                                                p=[0.4, 0.2, 0.2, 0.1, 0.1] if cat_rr > 0.05 else [0.15, 0.25, 0.35, 0.1, 0.15]),
                                    "refund_amount": round(net * rq / qty, 2)})
                    moves.append({"movement_date": rdate, "warehouse_id": wh, "sku": sku, "movement_type": "Return - restock", "qty": rq})
            dispatch.append({"dispatch_id": f"DSP{len(dispatch) + 1:06d}", "dispatch_date": (d + timedelta(days=int(rng.integers(0, 3)))).date(),
                             "order_id": order_id, "from_warehouse": wh, "destination": "Customer", "dispatch_type": "Customer order",
                             "courier": rng.choice(["Delhivery", "BlueDart", "Ekart", "Shadowfax", "Store pickup" if ch == "Retail Store" else "Delhivery"]),
                             "units": n_lines})
    # weekly: franchise dispatches + inter-warehouse transfers (NOT consumer sales, but appear in the sales register)
    if d.dayofweek == 1:
        for fr in ["FR-JAI", "FR-PUN"]:
            for p in rng.choice(n_prod, size=6, replace=False, p=pop):
                sku = products["sku"].iat[int(p)]
                qty = int(rng.integers(5, 25))
                price = float(products["unit_price"].iat[int(p)])
                inv += 1
                lines.append({"invoice_no": f"INV{inv:07d}", "invoice_date": d.date(), "order_id": None, "sku": sku, "channel": "Franchise",
                              "warehouse_id": "WH-DEL", "customer_id": None, "qty": qty, "unit_price": price, "discount_pct": 35.0,
                              "gross_amount": qty * price, "net_amount": round(qty * price * 0.65, 2), "transaction_type": "Franchise dispatch"})
                moves.append({"movement_date": d.date(), "warehouse_id": "WH-DEL", "sku": sku, "movement_type": "Franchise dispatch", "qty": -qty})
                dispatch.append({"dispatch_id": f"DSP{len(dispatch) + 1:06d}", "dispatch_date": d.date(), "order_id": None,
                                 "from_warehouse": "WH-DEL", "destination": fr, "dispatch_type": "Franchise stock", "courier": "Own fleet", "units": qty})
    if d.dayofweek == 3:
        for p in rng.choice(n_prod, size=5, replace=False, p=pop):
            sku = products["sku"].iat[int(p)]
            qty = int(rng.integers(10, 40))
            src, dst = rng.choice(OWN, size=2, replace=False)
            inv += 1
            lines.append({"invoice_no": f"INV{inv:07d}", "invoice_date": d.date(), "order_id": None, "sku": sku, "channel": "Internal",
                          "warehouse_id": src, "customer_id": None, "qty": qty, "unit_price": float(products["unit_cost"].iat[int(p)]),
                          "discount_pct": 0.0, "gross_amount": round(qty * products["unit_cost"].iat[int(p)], 2),
                          "net_amount": round(qty * products["unit_cost"].iat[int(p)], 2), "transaction_type": "Inter-warehouse transfer"})
            moves.append({"movement_date": d.date(), "warehouse_id": src, "sku": sku, "movement_type": "Transfer out", "qty": -qty})
            moves.append({"movement_date": d.date(), "warehouse_id": dst, "sku": sku, "movement_type": "Transfer in", "qty": qty})
            dispatch.append({"dispatch_id": f"DSP{len(dispatch) + 1:06d}", "dispatch_date": d.date(), "order_id": None,
                             "from_warehouse": src, "destination": dst, "dispatch_type": "Inter-warehouse transfer", "courier": "Own fleet", "units": qty})

sales = pd.DataFrame(lines)
moves_df = pd.DataFrame(moves)

# replenishment: weekly inbound per sku/warehouse = recent average outflow * 1.05 (declining SKUs keep OLD rate)
stock = {(w, s): int(rng.integers(40, 120)) for w in OWN for s in products["sku"]}
init_stock = dict(stock)
out_by_week = moves_df[moves_df["qty"] < 0].copy()
out_by_week["week"] = pd.to_datetime(out_by_week["movement_date"]).dt.to_period("W-SUN")
weekly_out = out_by_week.groupby(["warehouse_id", "sku", "week"])["qty"].sum().abs()
inbound = []
weeks = pd.period_range(pd.Timestamp(START), pd.Timestamp(END), freq="W-SUN")
for wk in weeks:
    monday = wk.start_time.date()
    if monday < START:
        continue
    for w in OWN:
        for s in products["sku"]:
            hist = [weekly_out.get((w, s, wk - k), 0) for k in range(1, 5)]
            base = np.mean(hist) if any(hist) else 1
            if s in declining_skus and monday >= last3_start.date():
                # buyers keep ordering at the pre-decline rate -> stock builds up
                old = [weekly_out.get((w, s, pd.Period(last3_start - pd.Timedelta(weeks=k), "W-SUN")), 0) for k in range(1, 9)]
                base = max(base, np.mean(old) * 1.6 + 2)
            q = int(round(base * 1.05 + rng.integers(0, 2)))
            if q > 0:
                inbound.append({"movement_date": monday, "warehouse_id": w, "sku": s, "movement_type": "Inbound - purchase", "qty": q})
moves_df = pd.concat([moves_df, pd.DataFrame(inbound)], ignore_index=True)
moves_df["movement_date"] = pd.to_datetime(moves_df["movement_date"])
moves_df = moves_df.sort_values(["movement_date", "warehouse_id", "sku"]).reset_index(drop=True)
moves_df.insert(0, "movement_id", [f"MV{k:07d}" for k in range(1, len(moves_df) + 1)])

# weekly stock snapshots (Sunday) for own warehouses
mv_own = moves_df[moves_df["warehouse_id"].isin(OWN)].copy()
mv_own["week_end"] = mv_own["movement_date"].dt.to_period("W-SUN").dt.end_time.dt.normalize()
net = mv_own.groupby(["warehouse_id", "sku", "week_end"])["qty"].sum()
snap_rows = []
week_ends = sorted(mv_own["week_end"].unique())
for w in OWN:
    for s in products["sku"]:
        level = init_stock[(w, s)]
        for we in week_ends:
            level += int(net.get((w, s, we), 0))
            if pd.Timestamp(we).date() <= END:
                snap_rows.append({"snapshot_date": pd.Timestamp(we).date(), "warehouse_id": w, "sku": s, "stock_on_hand": max(level, 0)})
snapshots = pd.DataFrame(snap_rows)

# marketing: daily spend per campaign
camps = [("CMP-GS", "Google Search - Brand", "Google Ads", "Shopify", 9000), ("CMP-GP", "Google Performance Max", "Google Ads", "Shopify", 7000),
         ("CMP-MT", "Meta Prospecting", "Meta Ads", "Shopify", 11000), ("CMP-MR", "Meta Retargeting", "Meta Ads", "Shopify", 4000),
         ("CMP-AZ", "Amazon Sponsored Products", "Amazon Ads", "Amazon", 8000), ("CMP-FK", "Flipkart PLA", "Flipkart Ads", "Flipkart", 3500)]
mk = []
for d in DAYS:
    mi = months_from_start(d)
    for cid, name, plat, tgt, base in camps:
        g = (1 + 0.035 * mi) if tgt == "Amazon" else (1 - 0.004 * mi) if tgt == "Shopify" else 1.0
        spend = round(base * seasonality(d) * g * rng.uniform(0.75, 1.25), 2)
        imp = int(spend * rng.uniform(55, 90))
        clicks = int(imp * rng.uniform(0.008, 0.02))
        mk.append({"date": d.date(), "campaign_id": cid, "campaign_name": name, "platform": plat, "target_channel": tgt,
                   "spend": spend, "impressions": imp, "clicks": clicks, "conversions": int(clicks * rng.uniform(0.01, 0.04))})
marketing = pd.DataFrame(mk)
orders_df = pd.DataFrame(orders)
returns_df = pd.DataFrame(returns)
dispatch_df = pd.DataFrame(dispatch)

# ----------------------------------------------------------------------------------------------- ground truth (clean data)
def month_start(d: date, k: int) -> date:
    y, m = d.year, d.month + k
    while m <= 0:
        m += 12
        y -= 1
    return date(y, m, 1)


this_m = date(TODAY.year, TODAY.month, 1)
lm_lo, lm_hi = month_start(TODAY, -1), this_m
s6_lo = month_start(TODAY, -6)
cons = sales[sales["transaction_type"] == "Sale"].copy()
cons["invoice_date"] = pd.to_datetime(cons["invoice_date"])
truth = {"today": TODAY.isoformat()}
mask_lm = (cons["invoice_date"] >= pd.Timestamp(lm_lo)) & (cons["invoice_date"] < pd.Timestamp(lm_hi))
truth["net_sales_last_month"] = round(float(cons.loc[mask_lm, "net_amount"].sum()), 2)
all_lm = sales[(pd.to_datetime(sales["invoice_date"]) >= pd.Timestamp(lm_lo)) & (pd.to_datetime(sales["invoice_date"]) < pd.Timestamp(lm_hi))]
truth["register_total_last_month_incl_transfers"] = round(float(all_lm["net_amount"].sum()), 2)
m6 = cons[(cons["invoice_date"] >= pd.Timestamp(s6_lo)) & (cons["invoice_date"] < pd.Timestamp(this_m)) & cons["channel"].isin(["Shopify", "Amazon"])]
m6g = m6.groupby([m6["invoice_date"].dt.to_period("M").astype(str), "channel"])["net_amount"].sum().round(2)
truth["shopify_amazon_monthly_last_6_months"] = {f"{k[0]}|{k[1]}": float(v) for k, v in m6g.items()}
sold = cons.groupby("sku")["qty"].sum()
ret = returns_df.groupby("sku")["qty_returned"].sum()
rr = (ret.reindex(sold.index).fillna(0) / sold).sort_values(ascending=False)
names = products.set_index("sku")["product_name"]
rr_named = rr.groupby(names.reindex(rr.index).values).apply(lambda x: x).droplevel(1) if False else None
# product_name is not unique across SKUs? (finish+name combos are unique per category) -> aggregate by name
by_name_sold = cons.assign(name=names.reindex(cons["sku"]).values).groupby("name")["qty"].sum()
by_name_ret = returns_df.assign(name=names.reindex(returns_df["sku"]).values).groupby("name")["qty_returned"].sum()
rate = (by_name_ret.reindex(by_name_sold.index).fillna(0) / by_name_sold).sort_values(ascending=False)
truth["return_rate_top10"] = [[k, round(float(v), 6)] for k, v in rate.head(10).items()]
truth["inventory_movement_by_warehouse"] = {k: int(v) for k, v in moves_df.groupby("warehouse_id")["qty"].sum().items()}
# declining sales + increasing stock: last 3 complete months vs previous 3 months
p_lo, p_mid, p_hi = month_start(TODAY, -6), month_start(TODAY, -3), this_m
cur = cons[(cons["invoice_date"] >= pd.Timestamp(p_mid)) & (cons["invoice_date"] < pd.Timestamp(p_hi))].groupby("sku")["net_amount"].sum()
prv = cons[(cons["invoice_date"] >= pd.Timestamp(p_lo)) & (cons["invoice_date"] < pd.Timestamp(p_mid))].groupby("sku")["net_amount"].sum()
snap = snapshots.copy()
snap["snapshot_date"] = pd.to_datetime(snap["snapshot_date"])


def latest_stock(lo, hi):
    w = snap[(snap["snapshot_date"] >= pd.Timestamp(lo)) & (snap["snapshot_date"] < pd.Timestamp(hi))]
    last = w["snapshot_date"].max()
    return w[w["snapshot_date"] == last].groupby("sku")["stock_on_hand"].sum()


st_cur, st_prv = latest_stock(p_mid, p_hi), latest_stock(p_lo, p_mid)
flag = [s for s in products["sku"] if cur.get(s, 0) < prv.get(s, 0) and st_cur.get(s, 0) > st_prv.get(s, 0)]
truth["declining_sales_increasing_stock_skus"] = sorted(flag)
truth["declining_sales_increasing_stock_names"] = sorted(set(names[flag]))
truth["planted_declining_skus"] = sorted(declining_skus)
mkt = marketing.copy()
mkt["date"] = pd.to_datetime(mkt["date"])
truth["marketing_spend_last_month"] = round(float(mkt[(mkt["date"] >= pd.Timestamp(lm_lo)) & (mkt["date"] < pd.Timestamp(lm_hi))]["spend"].sum()), 2)
truth["row_counts_clean"] = {"products": len(products), "sales_register": len(sales), "returns": len(returns_df), "orders": len(orders_df),
                             "inventory_movements": len(moves_df), "inventory_snapshots": len(snapshots), "marketing_spend": len(marketing),
                             "customers": len(customers), "dispatch": len(dispatch_df)}

# ----------------------------------------------------------------------------------------------- make it messy
def fmt_inr(x):
    return f"₹{x:,.2f}"


# products: title rows, blank row, inconsistent category spelling, "Rs." prices, duplicate row, sheet 2
pm = products.copy()
pm["category"] = [c if rng.random() > 0.12 else rng.choice([c.lower(), c.upper(), f" {c} ", c + " "]) for c in pm["category"]]
pm["unit_price"] = [f"Rs. {p:,}" if rng.random() < 0.3 else p for p in pm["unit_price"]]
pm = pd.concat([pm, pm.iloc[[3]]], ignore_index=True)  # duplicate product row
pm.columns = ["SKU", "Product Name", "Category ", "MRP (₹)", "Unit Cost", "Launch Date"]
with pd.ExcelWriter(os.path.join(OUT, "products.xlsx")) as xw:
    title = pd.DataFrame([["Product Master - exported from ERP"], ["Generated 2026-10-16"], [None]])
    title.to_excel(xw, sheet_name="Product Master", header=False, index=False)
    pm.to_excel(xw, sheet_name="Product Master", startrow=3, index=False)
    pd.DataFrame({"Notes": ["MRP includes GST", "Unit cost is landed cost"]}).to_excel(xw, sheet_name="Notes", index=False)

warehouses.to_csv(os.path.join(OUT, "warehouses.csv"), index=False)
channels.to_csv(os.path.join(OUT, "channels.csv"), index=False)
cm = customers.copy()
cm.loc[rng.random(len(cm)) < 0.06, "city"] = None
cm["signup_date"] = pd.to_datetime(cm["signup_date"]).dt.strftime("%d/%m/%Y")
cm.to_csv(os.path.join(OUT, "customers.csv"), index=False)
orders_df.to_csv(os.path.join(OUT, "orders.csv"), index=False)

# sales register: mixed date formats, ₹ amounts, channel spelling variants, N/A, ~0.4% duplicate rows
sm = sales.copy()
sm["invoice_date"] = [d.strftime("%d/%m/%Y") if rng.random() < 0.25 else d.isoformat() for d in sm["invoice_date"]]
variants = {"Amazon": ["amazon", "Amazon.in", "AMAZON", " Amazon"], "Shopify": ["shopify", "Shopify ", "Website"], "Flipkart": ["flipkart"]}
sm["channel"] = [rng.choice(variants[c]) if c in variants and rng.random() < 0.07 else c for c in sm["channel"]]
sm["net_amount"] = [fmt_inr(x) if rng.random() < 0.2 else x for x in sm["net_amount"]]
dups = sm.sample(frac=0.004, random_state=1)
sm = pd.concat([sm, dups], ignore_index=True).sort_values("invoice_no", kind="stable").reset_index(drop=True)
sm.columns = ["Invoice No", "Invoice Date", "Order ID", "SKU", "Channel", "Warehouse", "Customer ID", "Qty", "Unit Price",
              "Discount %", "Gross Amount", "Net Amount", "Transaction Type"]
with pd.ExcelWriter(os.path.join(OUT, "sales_register.xlsx")) as xw:
    sm.to_excel(xw, sheet_name="Sales Register", index=False)

rm = returns_df.copy()
rm["notes"] = [None if rng.random() > 0.03 else "photo received" for _ in range(len(rm))]
rm.columns = ["Return ID", "Return Date", "Invoice No", "SKU", "Channel", "Warehouse", "Qty Returned", "Return Reason", "Refund Amount", ""]
rm.to_csv(os.path.join(OUT, "returns.csv"), index=False)
mv = moves_df.copy()
mv["movement_date"] = mv["movement_date"].dt.date
mv.to_csv(os.path.join(OUT, "inventory_movements.csv"), index=False)
snapshots.to_csv(os.path.join(OUT, "inventory_snapshots.csv"), index=False)
dispatch_df.to_csv(os.path.join(OUT, "dispatch.csv"), index=False)
mm = marketing.copy()
mm["spend"] = [fmt_inr(x) if rng.random() < 0.15 else x for x in mm["spend"]]
with pd.ExcelWriter(os.path.join(OUT, "marketing_spend.xlsx")) as xw:
    mm.to_excel(xw, sheet_name="Daily Spend", index=False)

with open(os.path.join(OUT, "ground_truth.json"), "w") as f:
    json.dump(truth, f, indent=2, default=str)
print(json.dumps(truth["row_counts_clean"], indent=1))
print("declining skus planted:", sorted(declining_skus), "found:", truth["declining_sales_increasing_stock_skus"])
