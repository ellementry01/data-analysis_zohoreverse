"""
Brings the warehouse workspace's app configuration in line with ellementry_dw schema 2.13, through the public API.
Re-runnable: every step checks what is already there.

    python scripts/configure_warehouse_workspace.py [--base http://localhost:8000] [--workspace 34]

1. Syncs every warehouse (connector) dataset, so new columns and re-classified rows appear (2.8 changed categories,
   MRPs and channels across all views).
2. Imports mart.v_purchase_order_lines as dataset purchase_order_lines (every PO line, with exception flags).
3. Metrics: RTO rate is computed on channels that report RTO (is_rto_tracked), delivery time on channels that report
   deliveries (is_delivery_tracked); stock_units_no_mrp, over_received_qty; 2.8: stock_value_cost (stock is valued at
   cost) and stock_units_no_cost.
4. Calculated column sales_segment: Ellementry International (channel EXPORT_B2C) is its own segment, "B2C export".
5. Label columns: fulfilment.order_status (readable WMS status) and stock_position_latest.location (closed stores marked).
Run build_executive_dashboards.py afterwards.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

SRC = "From ellementry_dw mart (schema 2.13)"
IMPORTS = [("v_purchase_order_lines", "purchase_order_lines"),     # 2.4: every PO line with exception flags
           ("v_stock_movement_check", "stock_movement_check"),     # 2.11: opening + movements vs closing, per stock period
           ("v_slow_stock", "slow_stock"),                         # 2.13: stock with days since the SKU last sold
           ("v_partner_stock_monthly", "partner_stock_monthly"),   # 2.13: sent / returned / sold at sale-or-return partners
           ("v_return_reasons", "return_reasons"),                 # 2.13: Amazon FBA return reasons
           ("v_agent_alerts", "agent_alerts"),                     # 2.16: alerts from the agent runner (Phase 7)
           ("v_agent_rules", "agent_rules"),                       # 2.16: the alert rules and their current thresholds
           ("v_agent_runs", "agent_runs"),                         # 2.16: agent runs (succeeded / failed)
           # 2.17: per product, stock that moved with no document vs the ERP documents no export carries
           ("v_unexplained_stock_by_document", "unexplained_stock_by_document")]
B2C_EXPORT = "WHEN channel_code = 'EXPORT_B2C' THEN 'B2C export' "
LABEL_COLUMNS = [
    ("fulfilment", "Order status",
     "CASE shipment_status WHEN 'DELIVERED' THEN 'Delivered' WHEN 'SHIPPED' THEN 'Shipped, no delivery update' "
     "WHEN 'IN_TRANSIT' THEN 'In transit' WHEN 'OUT_FOR_DELIVERY' THEN 'Out for delivery' "
     "WHEN 'DELIVERY_ATTEMPTED' THEN 'Delivery attempted' WHEN 'RTO_INITIATED' THEN 'Returning to origin (RTO)' "
     "WHEN 'RTO_DELIVERED' THEN 'Returned to origin (RTO)' WHEN 'CANCELLED' THEN 'Cancelled' WHEN 'LOST' THEN 'Lost' "
     "WHEN 'OPEN' THEN 'Not yet shipped' WHEN 'PICKED' THEN 'Not yet shipped' WHEN 'PACKING' THEN 'Not yet shipped' "
     "ELSE 'Status not recorded' END"),
    # closed stores keep showing the stock they still hold, marked so (store status sheet, BR-035)
    ("stock_position_latest", "Location",
     "CASE WHEN is_active = false THEN location_name || ' (closed)' ELSE location_name END"),
]



def _headers() -> dict:
    """With company sign-in on, scripts authenticate with an API token from ELLEMENTRY_API_TOKEN (Administration ->
    API tokens). It is read from the environment only, never printed."""
    import os

    h = {"Content-Type": "application/json"}
    token = os.environ.get("ELLEMENTRY_API_TOKEN", "").strip()
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000"); ap.add_argument("--workspace", type=int, default=34)
    a = ap.parse_args()
    base = f"{a.base}/api/workspaces/{a.workspace}"

    def call(method, path, body=None):
        req = urllib.request.Request(base + path, method=method, headers=_headers(),
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    failures = 0
    datasets = {d["slug"]: d for d in call("GET", "/datasets")[1]}
    for name in sorted(n for n, d in datasets.items() if d["kind"] == "connector"):
        s, r = call("POST", f"/datasets/{datasets[name]['id']}/sync")
        print(f"sync {name}: {'OK ' + str(r['dataset']['row_count']) + ' rows' if s == 200 else f'FAILED {r}'}")
        failures += s != 200

    connector = next(c for c in call("GET", "/connectors")[1] if c["name"].startswith("ellementry_dw"))
    for view, name in IMPORTS:
        if name in datasets:
            continue
        s, r = call("POST", f"/connectors/{connector['id']}/import",
                    {"tables": [{"schema": "mart", "table": view, "name": name}], "refresh_minutes": 60})
        print(f"import {name}: {'OK' if s == 201 else f'FAILED {r}'}")
        failures += s != 201
    datasets = {d["slug"]: d for d in call("GET", "/datasets")[1]}

    def ds(name):
        return datasets[name]["id"]

    wanted = [
        {"name": "rto_rate", "label": "RTO rate (channels that report RTO)", "dataset_id": ds("fulfilment"),
         "expression": "AVG(CASE WHEN is_rto THEN 1.0 ELSE 0 END)",
         "filters": [{"column": "is_rto_tracked", "op": "eq", "value": True}],
         "description": SRC + ". Only channels that record returns-to-origin in the WMS (today the website); "
                              "marketplace RTO never reaches the WMS and would read as zero.",
         "synonyms": ["rto rate", "return to origin rate", "rto"], "format": "percent", "higher_is_better": False},
        {"name": "avg_ship_to_deliver_days", "label": "Average delivery time (days, tracked channels)", "dataset_id": ds("fulfilment"),
         "expression": "AVG(ship_to_deliver_days)",
         "filters": [{"column": "is_delivery_tracked", "op": "eq", "value": True}],
         "description": SRC + ". Channels whose couriers report delivery dates (not Nykaa, FNP, Flipkart).",
         "synonyms": ["delivery time", "transit time", "ship to deliver"], "format": "number", "higher_is_better": False},
        {"name": "stock_units_no_mrp", "label": "Units with no MRP (left out of stock value)", "dataset_id": ds("stock_position_latest"),
         "expression": "SUM(CASE WHEN mrp_status = 'MRP missing' THEN on_hand_qty ELSE 0 END)", "filters": [],
         "time_column": "as_of_date", "semi_additive": True,
         "description": SRC + ". Stock whose item has no MRP in the stock report, invoices or ERP item master.",
         "synonyms": ["missing mrp", "no mrp", "unvalued stock"], "format": "number", "higher_is_better": False},
        {"name": "over_received_qty", "label": "Over-received quantity", "dataset_id": ds("purchase_order_lines"),
         "expression": "SUM(over_received_qty)", "filters": [],
         "description": SRC + ". PO lines where more was received than ordered (pending quantity below zero).",
         "synonyms": ["over received", "excess receipt"], "format": "number", "higher_is_better": False},
        {"name": "stock_value_cost", "label": "Stock value at cost", "dataset_id": ds("stock_position_latest"),
         "expression": "SUM(stock_value_cost)", "filters": [], "time_column": "as_of_date", "semi_additive": True,
         "description": SRC + ". Units on hand x unit cost from the ERP item master (excl. GST). The company values stock at cost.",
         "synonyms": ["stock value", "inventory value", "stock at cost", "inventory at cost"], "format": "currency",
         "higher_is_better": True},
        {"name": "stock_value_cost_history", "label": "Stock value at cost (saved stock days)", "dataset_id": ds("stock_position_daily"),
         "expression": "SUM(stock_value_cost)", "filters": [], "time_column": "snapshot_date", "semi_additive": True,
         "description": SRC + ". Stock at cost on each saved stock day (month-ends from 31 Mar 2025, then 15 Sep 2026); "
                              "by month it takes the last saved day of the month.",
         "synonyms": ["stock trend", "stock history", "inventory trend"], "format": "currency", "higher_is_better": True},
        {"name": "unexplained_stock_qty", "label": "Stock movement without a document (units)", "dataset_id": ds("stock_movement_check"),
         "expression": "SUM(unexplained_qty)", "filters": [], "time_column": "period_to",
         "description": SRC + ". Closing stock minus (opening + recorded movements) between two saved stock days. "
                              "Negative = left without a document; positive = arrived without one.",
         "synonyms": ["stock gap", "unexplained stock", "stock difference"], "format": "number", "higher_is_better": True},
        {"name": "slow_stock_value_cost", "label": "Stock value at cost (by last sale)", "dataset_id": ds("slow_stock"),
         "expression": "SUM(stock_value_cost)", "filters": [],
         "description": SRC + ". Trading stock at ERP-reported locations on the latest stock day, valued at cost; "
                              "slice by sales_age_band (how long since the SKU last sold anywhere).",
         "synonyms": ["slow stock", "dead stock", "ageing stock"], "format": "currency", "higher_is_better": False},
        {"name": "cover_stock_value_cost", "label": "Sellable stock value at cost (cover view)", "dataset_id": ds("days_of_cover"),
         "expression": "SUM(stock_value_cost)", "filters": [],
         "description": SRC + ". Sellable trading stock by location at cost; slice by cover_band.",
         "synonyms": ["cover value", "overstock value"], "format": "currency", "higher_is_better": True},
        {"name": "partner_units_sent", "label": "Units sent to partner (sale-or-return)", "dataset_id": ds("partner_stock_monthly"),
         "expression": "SUM(sent_qty)", "filters": [], "time_column": "month_start_date",
         "description": SRC + ". Units invoiced to sale-or-return partners (Instamart, Blinkit).",
         "synonyms": ["sent to instamart", "supplied to instamart"], "format": "number", "higher_is_better": True},
        {"name": "partner_units_returned", "label": "Units returned by partner", "dataset_id": ds("partner_stock_monthly"),
         "expression": "SUM(returned_qty)", "filters": [], "time_column": "month_start_date",
         "description": SRC + ". Units the partner sent back (credit notes).",
         "synonyms": ["returned by instamart"], "format": "number", "higher_is_better": False},
        {"name": "partner_units_sold", "label": "Units sold through by partner", "dataset_id": ds("partner_stock_monthly"),
         "expression": "SUM(sold_qty)", "filters": [], "time_column": "month_start_date",
         "description": SRC + ". Units the partner sold to consumers (sell-out).",
         "synonyms": ["sold by instamart", "sell through"], "format": "number", "higher_is_better": True},
        {"name": "partner_stock_balance", "label": "Stock with partner (since Apr 2025, no opening)", "dataset_id": ds("partner_stock_monthly"),
         "expression": "SUM(closing_qty)", "filters": [], "time_column": "month_start_date", "semi_additive": True,
         "description": SRC + ". Sent minus returned minus sold since 1 Apr 2025. The partner's opening stock is unknown (G-028), "
                              "so this is not a stock count.",
         "synonyms": ["stock at instamart", "instamart stock"], "format": "number", "higher_is_better": True},
        {"name": "qc_sell_out_value", "label": "Quick-commerce sell-out value (consumer prices)", "dataset_id": ds("quick_commerce_sell_out_daily"),
         "expression": "SUM(selling_value)", "filters": [],
         "description": SRC + ". What consumers paid on the platform (Instamart reports GMV at MRP). Demand, never our revenue (BR-024).",
         "synonyms": ["instamart gmv", "sell out value"], "format": "currency", "higher_is_better": True},
        {"name": "amazon_units_returned", "label": "Amazon units returned (with reason)", "dataset_id": ds("return_reasons"),
         "expression": "SUM(units_returned)", "filters": [], "time_column": "return_date",
         "description": SRC + ". Amazon returns with Amazon's reason: FBA orders (with the condition on return) and, since "
                              "warehouse 2.17, self-shipped orders (sub_channel_name 'Self-ship / Easyship'; reason group 'Not "
                              "delivered' = rejected or undelivered parcels). Units only.",
         "synonyms": ["return reasons", "amazon returns", "amazon rto", "amazon not delivered"], "format": "number",
         "higher_is_better": False},
        {"name": "partner_stock_at_least", "label": "Stock with partner, at least", "dataset_id": ds("partner_stock_monthly"),
         "expression": "SUM(closing_qty_at_least)", "filters": [], "time_column": "month_start_date", "semi_additive": True,
         "description": SRC + " (2.17). Sent minus returned minus sold since 1 Apr 2025, plus the least opening stock the partner "
                              "must have held (how far each product's running balance falls below zero). A floor, not a stock count.",
         "synonyms": ["instamart stock at least", "minimum stock at instamart"], "format": "number", "higher_is_better": True},
        {"name": "stock_gap_units", "label": "Stock moved without a document, net per product (units)",
         "dataset_id": ds("unexplained_stock_by_document"), "expression": "SUM(ABS(unexplained_qty))", "filters": [],
         "description": SRC + " (2.17). Per product over the whole stock-check period, all ERP locations together: the net units "
                              "that arrived or left with no document in the exports.",
         "synonyms": ["stock gap", "unexplained stock per product"], "format": "number", "higher_is_better": False},
        {"name": "stock_gap_explained_units", "label": "Stock gap explained by ERP documents (units)",
         "dataset_id": ds("unexplained_stock_by_document"), "expression": "SUM(ABS(explained_qty))", "filters": [],
         "description": SRC + " (2.17). The part of the stock gap accounted for by ERP documents no export carries: scrap notes, "
                              "stock increase / decrease, inventory transfer, sub-contractor issue and receipt, return to supplier.",
         "synonyms": ["explained stock gap", "scrap and adjustments"], "format": "number", "higher_is_better": True},
        {"name": "stock_gap_remaining_units", "label": "Stock gap still unexplained (units)",
         "dataset_id": ds("unexplained_stock_by_document"), "expression": "SUM(ABS(still_unexplained_qty))", "filters": [],
         "description": SRC + " (2.17). The stock gap left after the ERP's scrap, adjustment, sub-contractor and supplier-return "
                              "documents.",
         "synonyms": ["remaining stock gap", "still unexplained stock"], "format": "number", "higher_is_better": False},
        {"name": "dq_failed_checks", "label": "Quality checks flagging rows", "dataset_id": ds("data_quality_latest"),
         "expression": "SUM(CASE WHEN outcome = 'FAIL' THEN 1 ELSE 0 END)", "filters": [],
         "description": SRC + ". Checks of the latest build that flag at least one row (warnings: known gaps).",
         "synonyms": ["data quality", "failed checks"], "format": "number", "higher_is_better": False},
        {"name": "dq_blocking_errors", "label": "Blocking data errors", "dataset_id": ds("data_quality_latest"),
         "expression": "SUM(CASE WHEN outcome = 'FAIL' THEN CASE WHEN severity = 'ERROR' THEN 1 ELSE 0 END ELSE 0 END)", "filters": [],
         "description": SRC + ". ERROR checks that failed. Always 0 on a published build: a failed ERROR check stops the build.",
         "synonyms": ["data errors"], "format": "number", "higher_is_better": False},
        {"name": "open_data_gaps", "label": "Open data gaps", "dataset_id": ds("data_gaps"),
         "expression": "SUM(CASE WHEN status <> 'CLOSED' THEN 1 ELSE 0 END)", "filters": [],
         "description": SRC + ". Data the warehouse still needs from the business or the ERP team.",
         "synonyms": ["data gaps", "missing data"], "format": "number", "higher_is_better": False},
        {"name": "files_loaded", "label": "Source files loaded", "dataset_id": ds("load_batches"),
         "expression": "SUM(CASE WHEN status = 'LOADED' THEN 1 ELSE 0 END)", "filters": [],
         "description": SRC + ". Export files loaded into the warehouse.", "synonyms": ["files", "loads"], "format": "number",
         "higher_is_better": True},
        {"name": "stock_units_no_cost", "label": "Units with no cost (left out of stock value)", "dataset_id": ds("stock_position_latest"),
         "expression": "SUM(CASE WHEN cost_status = 'Cost missing' THEN on_hand_qty ELSE 0 END)", "filters": [],
         "time_column": "as_of_date", "semi_additive": True,
         "description": SRC + ". Stock whose item has no cost in the ERP item master.",
         "synonyms": ["missing cost", "no cost"], "format": "number", "higher_is_better": False},
    ]
    metrics = {x["name"]: x for x in call("GET", "/metrics")[1]}
    for w in wanted:
        body = {"kind": "simple", "time_column": None, "semi_additive": False} | w
        if w["name"] in metrics:
            s, r = call("PUT", f"/metrics/{metrics[w['name']]['id']}", body)
            ok = s == 200
        else:
            s, r = call("POST", "/metrics", body)
            ok = s == 201
        print(f"metric {w['name']}: {'OK' if ok else f'FAILED {r}'}")
        failures += not ok

    for name in ("net_sales_daily", "sales_orders_daily"):
        full = call("GET", f"/datasets/{ds(name)}")[1]
        col = next(c for c in full["columns"] if c["name"] == "sales_segment")
        expr = col["expression"]
        if expr.startswith("CAST((") and expr.endswith(") AS TEXT)"):   # stored with the type cast the app adds
            expr = expr[len("CAST(("):-len(") AS TEXT)")]
        if "EXPORT_B2C" not in expr:
            assert expr.startswith("CASE WHEN "), expr[:40]
            expr = "CASE " + B2C_EXPORT + expr[len("CASE "):]
            s, r = call("PATCH", f"/datasets/{ds(name)}/columns/sales_segment", {"expression": expr, "data_type": "text"})
            print(f"{name}.sales_segment B2C export: {'OK' if s == 200 else f'FAILED {r}'}")
            failures += s != 200

    # 5. Readable label columns used by the Fulfilment and Stock dashboards (added or updated in place)
    for name, display, expr in LABEL_COLUMNS:
        full = call("GET", f"/datasets/{ds(name)}")[1]
        col = next((c for c in full["columns"] if c["display_name"] == display), None)
        if col is None:
            s, r = call("POST", f"/datasets/{ds(name)}/columns", {"display_name": display, "expression": expr, "data_type": "text"})
            ok = s == 201
        elif expr not in (col.get("expression") or ""):
            s, r = call("PATCH", f"/datasets/{ds(name)}/columns/{col['name']}", {"expression": expr, "data_type": "text"})
            ok = s == 200
        else:
            ok, r = True, None
        print(f"{name}.{display}: {'OK' if ok else f'FAILED {r}'}")
        failures += not ok
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
