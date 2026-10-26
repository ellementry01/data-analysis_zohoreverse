"""Builds the demo workspace through the public HTTP API (the same calls the UI makes).

    python -m app.demo                 # creates "Home Goods Co. (demo)" in the configured database
"""
from __future__ import annotations

import os
from typing import Any

SAMPLE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "sample_data")

FILES = [  # (file, dataset name, columns to exclude)
    ("products.xlsx", "Products", []),
    ("warehouses.csv", "Warehouses", []),
    ("channels.csv", "Channels", []),
    ("customers.csv", "Customers", []),
    ("orders.csv", "Orders", []),
    ("sales_register.xlsx", "Sales Register", []),
    ("returns.csv", "Returns", ["Column 10"]),
    ("inventory_movements.csv", "Inventory Movements", []),
    ("inventory_snapshots.csv", "Inventory Snapshots", []),
    ("dispatch.csv", "Dispatch", []),
    ("marketing_spend.xlsx", "Marketing Spend", []),
]


class DemoError(RuntimeError):
    pass


def _ok(r, expect=(200, 201, 204)) -> Any:
    if r.status_code not in expect:
        raise DemoError(f"{r.request.method} {r.request.url.path} -> {r.status_code}: {r.text[:500]}")
    return r.json() if r.status_code != 204 and r.content else None


def build_demo(client, sample_dir: str = SAMPLE_DIR, name: str = "Home Goods Co. (demo)", log=print) -> dict:
    ws = _ok(client.post("/api/workspaces", json={"name": name, "description": "Synthetic home & kitchen brand: sales, returns, inventory, dispatch, marketing"}))
    base = f"/api/workspaces/{ws['id']}"
    ds: dict[str, dict] = {}

    # 1-2. upload + import (header row / types auto-detected, junk columns excluded)
    for fname, dname, exclude in FILES:
        with open(os.path.join(sample_dir, fname), "rb") as f:
            prev = _ok(client.post(f"{base}/uploads", files={"file": (fname, f.read())}))
        cols = [{"source_name": c["source_name"], "name": c["name"], "display_name": c["display_name"],
                 "data_type": c["inferred_type"], "include": c["source_name"] not in exclude} for c in prev["columns"]]
        res = _ok(client.post(f"{base}/imports", json={"upload_id": prev["upload_id"], "sheet": prev["sheet"], "header_row": prev["header_row"],
                                                        "name": dname, "columns": cols, "mode": "new"}))
        d = res["dataset"]
        ds[d["slug"]] = d
        log(f"imported {dname}: {d['row_count']} rows (header row {prev['header_row']}, {len(prev['warnings'])} warnings)")

    sid = {k: v["id"] for k, v in ds.items()}

    # 3. clean
    steps = [
        ("products", "trim_whitespace", {}),
        ("products", "change_case", {"column": "category", "mode": "title"}),
        ("products", "remove_duplicates", {}),
        ("sales_register", "remove_duplicates", {}),
        ("sales_register", "standardize_values", {"column": "channel", "mapping": {
            "Amazon": ["amazon", "amazon.in"], "Shopify": ["shopify", "website"], "Flipkart": ["flipkart"]}}),
    ]
    for slug, kind, params in steps:
        r = _ok(client.post(f"{base}/datasets/{sid[slug]}/transforms", json={"kind": kind, "params": params}))
        log(f"{slug}: {kind} -> {r['message']}")
    _ok(client.post(f"{base}/datasets/{sid['sales_register']}/columns", json={
        "display_name": "Gross margin", "expression": "net_amount - qty * unit_price * 0.45", "data_type": "decimal"}))

    # 4. relationships (lookups)
    rels = [
        ("sales_register", "sku", "products", "sku"), ("sales_register", "warehouse", "warehouses", "warehouse_id"),
        ("sales_register", "channel", "channels", "channel"), ("sales_register", "customer_id", "customers", "customer_id"),
        ("returns", "sku", "products", "sku"), ("returns", "warehouse", "warehouses", "warehouse_id"),
        ("inventory_movements", "sku", "products", "sku"), ("inventory_movements", "warehouse_id", "warehouses", "warehouse_id"),
        ("inventory_snapshots", "sku", "products", "sku"), ("inventory_snapshots", "warehouse_id", "warehouses", "warehouse_id"),
        ("orders", "customer_id", "customers", "customer_id"), ("orders", "warehouse_id", "warehouses", "warehouse_id"),
        ("orders", "channel", "channels", "channel"), ("dispatch", "from_warehouse", "warehouses", "warehouse_id"),
        ("marketing_spend", "target_channel", "channels", "channel"),
    ]
    for a, ac, b, bc in rels:
        _ok(client.post(f"{base}/relationships", json={"from_dataset_id": sid[a], "from_column": ac, "to_dataset_id": sid[b], "to_column": bc}))
    log(f"{len(rels)} relationships")

    # 5. semantic layer: metrics with business rules (consumer sales exclude transfers and franchise dispatches)
    sale = [{"column": "transaction_type", "op": "eq", "value": "Sale"}]
    metrics = [
        dict(name="net_sales", label="Net sales", dataset_id=sid["sales_register"], expression="SUM(net_amount)", filters=sale,
             synonyms=["sales", "revenue", "sales revenue", "consumer sales", "turnover", "gmv"], format="currency",
             description="Consumer sales only: excludes inter-warehouse transfers and franchise stock dispatches"),
        dict(name="units_sold", label="Units sold", dataset_id=sid["sales_register"], expression="SUM(qty)", filters=sale,
             synonyms=["units", "quantity sold", "sales volume", "volume"]),
        dict(name="orders_count", label="Orders", dataset_id=sid["sales_register"], expression="COUNT(DISTINCT order_id)", filters=sale,
             synonyms=["orders", "number of orders", "order count"]),
        dict(name="franchise_dispatch_value", label="Franchise dispatch value", dataset_id=sid["sales_register"], expression="SUM(net_amount)",
             filters=[{"column": "transaction_type", "op": "eq", "value": "Franchise dispatch"}], synonyms=["franchise dispatch", "franchise stock"], format="currency"),
        dict(name="transfer_value", label="Inter-warehouse transfer value", dataset_id=sid["sales_register"], expression="SUM(net_amount)",
             filters=[{"column": "transaction_type", "op": "eq", "value": "Inter-warehouse transfer"}], synonyms=["transfers", "stock transfers"], format="currency"),
        dict(name="units_returned", label="Units returned", dataset_id=sid["returns"], expression="SUM(qty_returned)",
             synonyms=["returns", "returned units", "return quantity"], higher_is_better=False),
        dict(name="refund_amount", label="Refund amount", dataset_id=sid["returns"], expression="SUM(refund_amount)",
             synonyms=["refunds", "return value"], format="currency", higher_is_better=False),
        dict(name="stock_on_hand", label="Stock on hand", dataset_id=sid["inventory_snapshots"], expression="SUM(stock_on_hand)",
             time_column="snapshot_date", semi_additive=True, synonyms=["stock", "inventory", "inventory level", "closing stock", "stock level"]),
        dict(name="inventory_movement", label="Net inventory movement", dataset_id=sid["inventory_movements"], expression="SUM(qty)",
             synonyms=["inventory movement", "stock movement", "net movement", "movement"]),
        dict(name="marketing_spend", label="Marketing spend", dataset_id=sid["marketing_spend"], expression="SUM(spend)",
             synonyms=["marketing spend", "ad spend", "marketing cost", "spend", "advertising"], format="currency", higher_is_better=False),
    ]
    for mt in metrics:
        _ok(client.post(f"{base}/metrics", json={"kind": "simple", **mt}))
    composites = [
        dict(name="return_rate", label="Return rate", expression="{units_returned} / NULLIF({units_sold}, 0)", format="percent",
             synonyms=["return rate", "return ratio", "returns rate", "return percentage"], higher_is_better=False),
        dict(name="roas", label="ROAS", expression="{net_sales} / NULLIF({marketing_spend}, 0)", synonyms=["return on ad spend", "roas"]),
        dict(name="average_order_value", label="Average order value", expression="{net_sales} / NULLIF({orders_count}, 0)",
             synonyms=["aov", "average order value", "basket size"], format="currency"),
    ]
    for mt in composites:
        _ok(client.post(f"{base}/metrics", json={"kind": "composite", **mt}))
    log(f"{len(metrics) + len(composites)} metrics")

    glossary = [
        dict(term="website", synonyms=["own site", "d2c site", "online store"], target_type="value", dataset_id=sid["channels"], column="channel", value="Shopify"),
        dict(term="product", synonyms=["item", "sku name"], target_type="column", dataset_id=sid["products"], column="product_name"),
        dict(term="warehouse", synonyms=["location", "depot"], target_type="column", dataset_id=sid["warehouses"], column="warehouse_name"),
        dict(term="category", synonyms=["product category"], target_type="column", dataset_id=sid["products"], column="category"),
    ]
    for g in glossary:
        _ok(client.post(f"{base}/glossary", json=g))

    # 6-7. reports + dashboard
    t = {"field": "@time", "grain": "month"}
    reports = [
        ("Monthly net sales by channel", "stacked_bar", {"dimensions": [t, {"field": "channels.channel"}], "measures": [{"metric": "net_sales"}], "time_range": "last_12_months"}),
        ("Return rate by category", "bar", {"dimensions": [{"field": "products.category"}], "measures": [{"metric": "return_rate"}]}),
    ]
    rep_ids = []
    for name_, ct, spec in reports:
        rep_ids.append(_ok(client.post(f"{base}/reports", json={"name": name_, "chart_type": ct, "spec": spec}))["id"])
    dash = _ok(client.post(f"{base}/dashboards", json={"name": "Sales & inventory overview", "filters": [
        {"id": "date", "type": "date_range", "label": "Date range", "field": "@time", "value": "last_12_months"},
        {"id": "channel", "type": "values", "label": "Channel", "field": "channels.channel", "value": []}]}))
    widgets = [
        ("Net sales", "kpi", {"measures": [{"metric": "net_sales"}], "compare": "previous_period"}, {"x": 0, "y": 0, "w": 3, "h": 2}),
        ("Orders", "kpi", {"measures": [{"metric": "orders_count"}], "compare": "previous_period"}, {"x": 3, "y": 0, "w": 3, "h": 2}),
        ("Return rate", "kpi", {"measures": [{"metric": "return_rate"}]}, {"x": 6, "y": 0, "w": 3, "h": 2}),
        ("Stock on hand", "kpi", {"measures": [{"metric": "stock_on_hand"}]}, {"x": 9, "y": 0, "w": 3, "h": 2}),
        ("Net sales trend", "area", {"dimensions": [t], "measures": [{"metric": "net_sales"}]}, {"x": 0, "y": 2, "w": 8, "h": 4}),
        ("Sales by channel", "donut", {"dimensions": [{"field": "channels.channel"}], "measures": [{"metric": "net_sales"}]}, {"x": 8, "y": 2, "w": 4, "h": 4}),
        ("Top products", "hbar", {"dimensions": [{"field": "products.product_name"}], "measures": [{"metric": "net_sales"}],
                                  "sort": [{"field": "net_sales", "dir": "desc"}], "limit": 10}, {"x": 0, "y": 6, "w": 6, "h": 5}),
        ("Marketing spend vs sales", "combo", {"dimensions": [t], "measures": [{"metric": "net_sales"}, {"metric": "marketing_spend"}]}, {"x": 6, "y": 6, "w": 6, "h": 5}),
        ("Stock by warehouse & category", "heatmap", {"dimensions": [{"field": "warehouses.warehouse_name"}, {"field": "products.category"}],
                                                      "measures": [{"metric": "stock_on_hand"}]}, {"x": 0, "y": 11, "w": 6, "h": 4}),
        ("Category sales pivot", "pivot", {"dimensions": [{"field": "products.category"}, {"field": "channels.channel"}],
                                           "measures": [{"metric": "net_sales"}]}, {"x": 6, "y": 11, "w": 6, "h": 4}),
    ]
    for title, ct, spec, layout in widgets:
        _ok(client.post(f"{base}/dashboards/{dash['id']}/widgets", json={"title": title, "chart_type": ct, "spec": spec, "layout": layout}))
    _ok(client.post(f"{base}/dashboards", json={"name": "Template: Executive KPIs", "is_template": True}))
    log(f"dashboard '{dash['name']}' with {len(widgets)} widgets")
    return {"workspace_id": ws["id"], "datasets": sid, "dashboard_id": dash["id"], "report_ids": rep_ids}


if __name__ == "__main__":
    from fastapi.testclient import TestClient

    from .main import app

    with TestClient(app) as c:
        out = build_demo(c)
    print("Demo ready:", out)
