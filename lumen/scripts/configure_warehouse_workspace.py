"""
Brings the warehouse workspace's app configuration in line with ellementry_dw schema 2.4, through the public API.
Re-runnable: every step checks what is already there.

    python scripts/configure_warehouse_workspace.py [--base http://localhost:8000] [--workspace 34]

1. Syncs the connector datasets whose mart views gained columns in 2.4 (stock, transfers, POs, cover, fulfilment,
   products), so the new columns appear.
2. Imports mart.v_purchase_order_lines as dataset purchase_order_lines (every PO line, with exception flags).
3. Metrics: RTO rate is computed on channels that report RTO (is_rto_tracked), delivery time on channels that report
   deliveries (is_delivery_tracked); new stock_units_no_mrp and over_received_qty.
Run build_executive_dashboards.py afterwards.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

SYNC = ["stock_position_latest", "transfer_in_transit", "open_purchase_orders", "days_of_cover", "fulfilment", "products"]
SRC = "From ellementry_dw mart (schema 2.4)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000"); ap.add_argument("--workspace", type=int, default=34)
    a = ap.parse_args()
    base = f"{a.base}/api/workspaces/{a.workspace}"

    def call(method, path, body=None):
        req = urllib.request.Request(base + path, method=method, headers={"Content-Type": "application/json"},
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    failures = 0
    datasets = {d["slug"]: d for d in call("GET", "/datasets")[1]}
    for name in SYNC:
        s, r = call("POST", f"/datasets/{datasets[name]['id']}/sync")
        print(f"sync {name}: {'OK ' + str(r['dataset']['row_count']) + ' rows' if s == 200 else f'FAILED {r}'}")
        failures += s != 200

    if "purchase_order_lines" not in datasets:
        connector = next(c for c in call("GET", "/connectors")[1] if c["name"].startswith("ellementry_dw"))
        s, r = call("POST", f"/connectors/{connector['id']}/import",
                    {"tables": [{"schema": "mart", "table": "v_purchase_order_lines", "name": "purchase_order_lines"}],
                     "refresh_minutes": 60})
        print(f"import purchase_order_lines: {'OK' if s == 201 else f'FAILED {r}'}")
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
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
