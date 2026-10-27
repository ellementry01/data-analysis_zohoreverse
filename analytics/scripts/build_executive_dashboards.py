"""
Builds the six executive dashboards of the prototype in a workspace connected to the Ellementry warehouse, through the
public API (the same calls the UI makes). Re-runnable: dashboards with these names are replaced.

    python scripts/build_executive_dashboards.py [--base http://localhost:8000] [--workspace 34]

Needs, in that workspace: the warehouse datasets (net_sales_daily, sales_orders_daily, returns_daily, returns_to_sale,
stock_position_latest, fulfilment, open_purchase_orders, purchase_order_lines, transfer_in_transit), their calculated label
columns (sales_segment, channel, location_group, return_window, route) and the metrics named below. For warehouse schema
2.4 run configure_warehouse_workspace.py first (new columns, purchase_order_lines, tracked-channel metrics).

Periods are explicit dates, because the data ends on 15 Sep 2026 (warehouse period end): relative presets such as
"last month" are measured from today and would be empty until the app gets an "as of" date.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

FY27_YTD = {"from": "2026-04-01", "to": "2026-09-15"}         # FY 2026-27 to the latest data
ALL_DATA = {"from": "2025-04-01", "to": "2026-09-15"}         # everything loaded
RETAIL = {"field": "net_sales_daily.partner_type", "op": "eq", "value": "D2C_CHANNEL_ACCOUNT"}
TRADING = {"field": "stock_position_latest.item_type", "op": "eq", "value": "TRADING"}
OWN_STOCK = {"field": "stock_position_latest.location_group", "op": "neq", "value": "At partners (no opening balance)"}
MONTH = {"field": "@time", "grain": "month"}
RECENT_TRANSIT = {"field": "transfer_in_transit.transit_status", "op": "eq", "value": "In transit (60 days or less)"}
STALE_TRANSIT = {"field": "transfer_in_transit.transit_status", "op": "eq", "value": "Not received after 60 days"}
# Amazon receives FBA shipments itself and never posts an ERP inward entry (G-007): kept apart from own locations
TO_OWN = {"field": "transfer_in_transit.destination_group", "op": "eq", "value": "To own locations"}
TO_FBA = {"field": "transfer_in_transit.destination_group", "op": "eq", "value": "To Amazon FBA"}
# the PO export's own Document Remark; shown as a filter only, rule BR-031 is not applied in the warehouse yet
PURCHASE_PO = {"field": "open_purchase_orders.document_type", "op": "eq", "value": "PURCHASE"}
PURCHASE_LT = {"field": "supplier_lead_time.document_type", "op": "eq", "value": "PURCHASE"}


def kpi(title, metric, x, y, w=2, compare="previous_year", filters=None):
    spec = {"measures": [{"metric": metric}], "filters": filters or []}
    if compare:
        spec["compare"] = compare
    return (title, "kpi", spec, {"x": x, "y": y, "w": w, "h": 2}, {})


def chart(title, ct, spec, x, y, w, h, drill=None):
    return (title, ct, spec, {"x": x, "y": y, "w": w, "h": h}, {"drill_path": drill} if drill else {})


def top(field, metric, n, filters=None, extra=None):
    alias = metric
    return {"dimensions": [{"field": field}], "measures": [{"metric": metric, "alias": alias}] + (extra or []),
            "filters": filters or [], "sort": [{"field": alias, "dir": "desc"}], "limit": n}


DASHBOARDS = [
    ("Executive overview",
     "Company performance at a glance. Retail = website, marketplaces, own stores and quick commerce. "
     "Money excludes GST. Data 1 Apr 2025 - 15 Sep 2026; stock as of 15 Sep 2026.",
     [{"id": "period", "type": "date_range", "label": "Period", "field": "@time", "value": FY27_YTD}],
     [kpi("Net sales (all channels)", "net_sales", 0, 0),
      kpi("Retail net sales", "retail_net_sales", 2, 0),
      kpi("Retail bills", "retail_bills", 4, 0),
      kpi("Retail average bill", "retail_average_bill", 6, 0),
      kpi("Return rate (units)", "sales_return_rate", 8, 0),
      kpi("Stock value at cost (15 Sep 2026)", "stock_value_cost", 10, 0, compare=None, filters=[TRADING, OWN_STOCK]),
      chart("Net sales by month and segment", "stacked_bar",
            {"dimensions": [MONTH, {"field": "net_sales_daily.sales_segment"}], "measures": [{"metric": "net_sales"}]}, 0, 2, 8, 5),
      chart("Net sales by segment", "hbar", top("net_sales_daily.sales_segment", "net_sales", 10), 8, 2, 4, 5,
            drill=["net_sales_daily.channel", "net_sales_daily.sub_channel_name"]),
      chart("Retail net sales by channel", "hbar", top("net_sales_daily.channel", "net_sales", 12, [RETAIL]), 0, 7, 6, 5,
            drill=["net_sales_daily.sub_channel_name"]),
      chart("Top 10 products (retail)", "hbar", top("net_sales_daily.product_name", "net_sales", 10,
            [RETAIL, {"field": "net_sales_daily.item_type", "op": "eq", "value": "TRADING"}]), 6, 7, 6, 5),
      kpi("Deliveries from Bagru", "deliveries", 0, 12, w=3),
      kpi("RTO rate (website; marketplaces don't report RTO)", "rto_rate", 3, 12, w=3),
      kpi("Late shipment rate", "late_shipment_rate", 6, 12, w=3),
      kpi("Avg order-to-ship (hours)", "avg_order_to_ship_hours", 9, 12, w=3)]),

    ("Sales & channels",
     "Where sales come from. 'B2B & partners (classification pending)' = domestic invoices whose partner type is not yet "
     "confirmed (partner list awaited from the business).",
     [{"id": "period", "type": "date_range", "label": "Period", "field": "@time", "value": ALL_DATA},
      {"id": "segment", "type": "values", "label": "Sales segment", "field": "net_sales_daily.sales_segment", "value": []}],
     [kpi("Net sales", "net_sales", 0, 0, w=3, compare=None),
      kpi("Gross sales (invoices)", "gross_sales", 3, 0, w=3, compare=None),
      kpi("Units sold", "units_sold", 6, 0, w=3, compare=None),
      kpi("Return rate (units)", "sales_return_rate", 9, 0, w=3, compare=None),
      chart("Net sales by financial year and segment", "stacked_bar",
            {"dimensions": [{"field": "net_sales_daily.fiscal_year_label"}, {"field": "net_sales_daily.sales_segment"}],
             "measures": [{"metric": "net_sales"}]}, 0, 2, 5, 5),
      chart("Monthly net sales", "area", {"dimensions": [MONTH], "measures": [{"metric": "net_sales"}]}, 5, 2, 7, 5),
      chart("Retail channels and sub-channels", "pivot",
            {"dimensions": [{"field": "net_sales_daily.channel"}, {"field": "net_sales_daily.fiscal_year_label"}],
             "measures": [{"metric": "net_sales"}], "filters": [RETAIL]}, 0, 7, 6, 6),
      chart("Net sales by category", "hbar", top("net_sales_daily.category", "net_sales", 15,
            [{"field": "net_sales_daily.item_type", "op": "eq", "value": "TRADING"}]), 6, 7, 6, 6,
            drill=["net_sales_daily.product_name"]),
      chart("Top 15 products", "table", top("net_sales_daily.product_name", "net_sales", 15,
            [{"field": "net_sales_daily.item_type", "op": "eq", "value": "TRADING"}], [{"metric": "units_sold"}]), 0, 13, 6, 6),
      chart("Own stores", "bar", top("net_sales_daily.location_name", "net_sales", 12,
            [{"field": "net_sales_daily.sales_segment", "op": "eq", "value": "Own stores"}]), 6, 13, 6, 6)]),

    ("Returns",
     "Customer and partner returns, excluding GST. Return reasons are not recorded in the ERP yet (gap G-009).",
     [{"id": "period", "type": "date_range", "label": "Period", "field": "@time", "value": ALL_DATA}],
     [kpi("Returns value", "returns_value", 0, 0, w=3, compare=None),
      kpi("Units returned", "units_returned", 3, 0, w=3, compare=None),
      kpi("Return rate (units)", "sales_return_rate", 6, 0, w=3, compare=None),
      kpi("Avg days from sale to return", "avg_days_to_return", 9, 0, w=3, compare=None),
      chart("Returns value by month", "bar", {"dimensions": [MONTH], "measures": [{"metric": "returns_value"}]}, 0, 2, 7, 5),
      chart("Returns value by channel", "hbar", top("returns_daily.channel", "returns_value", 12), 7, 2, 5, 5),
      chart("Return rate by retail channel", "hbar",
            {"dimensions": [{"field": "net_sales_daily.channel"}], "measures": [{"metric": "sales_return_rate", "alias": "rr"}],
             "filters": [RETAIL], "sort": [{"field": "rr", "dir": "desc"}], "limit": 12}, 0, 7, 6, 5),
      chart("How soon goods come back", "bar",
            {"dimensions": [{"field": "returns_to_sale.return_window", "alias": "return_window"}], "measures": [{"field": "returns_to_sale.returns_value", "agg": "sum", "alias": "rv", "label": "Returns value"}],
             "sort": [{"field": "return_window", "dir": "asc"}]}, 6, 7, 6, 5),
      chart("Top 15 returned products", "table", top("returns_daily.product_name", "returns_value", 15,
            extra=[{"metric": "units_returned"}]), 0, 12, 12, 6)]),

    ("Stock",
     "Stock on 15 Sep 2026, each location from its own stock report, trading items only, valued at cost "
     "(unit cost from the ERP item master, excl. GST). Categories come from the ERP item master. "
     "History starts once the daily stock report is saved (gap G-001). Stock at partners has no opening balance yet (G-028).",
     [],
     [kpi("Stock value at cost", "stock_value_cost", 0, 0, w=3, compare=None, filters=[TRADING, OWN_STOCK]),
      kpi("Units on hand", "stock_on_hand", 3, 0, w=2, compare=None, filters=[TRADING, OWN_STOCK]),
      kpi("Sellable units", "sellable_stock", 5, 0, w=2, compare=None, filters=[TRADING, OWN_STOCK]),
      kpi("Discontinued stock at cost", "stock_value_cost", 7, 0, w=3, compare=None,
          filters=[TRADING, OWN_STOCK, {"field": "stock_position_latest.lifecycle_status", "op": "eq", "value": "DISCONTINUED"}]),
      kpi("Units with no cost", "stock_units_no_cost", 10, 0, w=2, compare=None, filters=[TRADING, OWN_STOCK]),
      chart("Stock value by location group", "hbar", top("stock_position_latest.location_group", "stock_value_cost", 10, [TRADING, OWN_STOCK]), 0, 2, 6, 5,
            drill=["stock_position_latest.location_name"]),
      chart("Continued vs discontinued (value at cost)", "donut",
            {"dimensions": [{"field": "stock_position_latest.lifecycle_status"}], "measures": [{"metric": "stock_value_cost"}],
             "filters": [TRADING, OWN_STOCK]}, 6, 2, 6, 5),
      chart("Stock value by category", "hbar", top("stock_position_latest.category_label", "stock_value_cost", 15, [TRADING, OWN_STOCK]), 0, 7, 6, 6,
            drill=["stock_position_latest.sub_category_label", "stock_position_latest.product_name"]),
      chart("Stock by location", "table", top("stock_position_latest.location_name", "stock_value_cost", 25, [TRADING, OWN_STOCK],
            [{"metric": "stock_on_hand"}]), 6, 7, 6, 6)]),

    ("Fulfilment",
     "Website and marketplace orders dispatched from Bagru (WMS export). RTO = returned to origin. Late = shipped after the "
     "marketplace's ship-by time. The WMS only knows what couriers report back: RTO is recorded for the website only "
     "(marketplace RTO is handled by the marketplace), and Nykaa, FNP and Flipkart send no delivery dates. Rates are "
     "therefore measured on the channels that report them; blank = not reported, not zero.",
     [{"id": "period", "type": "date_range", "label": "Order date", "field": "@time", "value": ALL_DATA},
      {"id": "channel", "type": "values", "label": "Channel", "field": "fulfilment.channel_name", "value": []}],
     [kpi("Deliveries", "deliveries", 0, 0, w=3, compare=None),
      kpi("RTO rate (website)", "rto_rate", 3, 0, w=2, compare=None),
      kpi("Late shipment rate", "late_shipment_rate", 5, 0, w=2, compare=None),
      kpi("Avg order-to-ship (hours)", "avg_order_to_ship_hours", 7, 0, w=2, compare=None),
      kpi("Avg delivery time, days (tracked channels)", "avg_ship_to_deliver_days", 9, 0, w=3, compare=None),
      chart("Deliveries by month and payment type", "stacked_bar",
            {"dimensions": [MONTH, {"field": "fulfilment.payment_type"}], "measures": [{"metric": "deliveries"}]}, 0, 2, 7, 5),
      chart("Shipment status", "hbar", top("fulfilment.shipment_status", "deliveries", 12), 7, 2, 5, 5),
      chart("RTO and late shipments by channel", "table",
            top("fulfilment.channel_name", "deliveries", 12, extra=[{"metric": "rto_rate"}, {"metric": "late_shipment_rate"},
                                                                     {"metric": "avg_order_to_ship_hours"}]), 0, 7, 6, 6),
      chart("Couriers", "table", top("fulfilment.courier_group", "deliveries", 12,
            extra=[{"metric": "rto_rate"}, {"metric": "avg_ship_to_deliver_days"}]), 6, 7, 6, 6)]),

    ("Purchasing & transfers",
     "Open purchase-order lines from the latest PO exports, and stock sent between locations but not yet received. "
     "Purchase vs return lines follow the PO export's own Document Remark (rule BR-031 awaiting business confirmation). "
     "The FY 25-26 PO export's date is assumed (31 Mar 2026), so its 'overdue' days are a minimum. "
     "Stock sent to Amazon FBA is received by Amazon, which never posts an ERP inward entry: it is shown apart from own "
     "locations, where 'not received after 60 days' is a real exception for the warehouse team.",
     [],
     [kpi("Open PO quantity (Purchase lines)", "open_po_qty", 0, 0, w=3, compare=None, filters=[PURCHASE_PO]),
      kpi("In transit to own sites (recent)", "units_in_transit", 3, 0, w=2, compare=None, filters=[RECENT_TRANSIT, TO_OWN]),
      kpi("Not received >60 days, own sites", "units_in_transit", 5, 0, w=2, compare=None, filters=[STALE_TRANSIT, TO_OWN]),
      kpi("To Amazon FBA >60 days (Amazon records receipt)", "units_in_transit", 7, 0, w=3, compare=None,
          filters=[STALE_TRANSIT, TO_FBA]),
      kpi("Supplier lead time, days", "avg_lead_time_days", 10, 0, w=2, compare=None, filters=[PURCHASE_LT]),
      chart("Open PO quantity by supplier (Purchase lines)", "hbar", top("open_purchase_orders.supplier", "open_po_qty", 12, [PURCHASE_PO]), 0, 2, 6, 6),
      chart("In transit by route (last 60 days)", "table", top("transfer_in_transit.route", "units_in_transit", 15, [RECENT_TRANSIT]), 6, 2, 6, 6),
      chart("Most overdue open PO lines", "table",
            {"dimensions": [{"field": "open_purchase_orders.po_number"}, {"field": "open_purchase_orders.supplier"},
                            {"field": "open_purchase_orders.document_type"}, {"field": "open_purchase_orders.due_status"}],
             "measures": [{"field": "open_purchase_orders.days_overdue", "agg": "max", "alias": "days_overdue", "label": "Days overdue"},
                          {"metric": "open_po_qty"}],
             "filters": [{"field": "open_purchase_orders.days_overdue", "op": "gt", "value": 0}],
             "sort": [{"field": "days_overdue", "dir": "desc"}], "limit": 20}, 0, 8, 12, 6),
      chart("Not received after 60 days, own locations", "table",
            top("transfer_in_transit.route", "units_in_transit", 15, [STALE_TRANSIT, TO_OWN]), 0, 14, 6, 6),
      chart("Open PO lines by due status", "hbar", top("open_purchase_orders.due_status", "open_po_qty", 6), 6, 14, 6, 3),
      chart("Over-received PO lines", "table",
            {"dimensions": [{"field": "purchase_order_lines.po_number"}, {"field": "purchase_order_lines.supplier"},
                            {"field": "purchase_order_lines.product_name"}],
             "measures": [{"metric": "over_received_qty", "alias": "over"}],
             "filters": [{"field": "purchase_order_lines.is_over_received", "op": "eq", "value": True}],
             "sort": [{"field": "over", "dir": "desc"}], "limit": 25}, 6, 17, 6, 5)]),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000"); ap.add_argument("--workspace", type=int, default=34)
    a = ap.parse_args()
    base = f"{a.base}/api/workspaces/{a.workspace}"

    def call(method, path, body=None):
        req = urllib.request.Request(base + path, method=method, headers={"Content-Type": "application/json"},
                                     data=json.dumps(body).encode() if body is not None else None)
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    existing = {d["name"]: d["id"] for d in call("GET", "/dashboards")[1]}
    failures = 0
    for name, desc, filters, widgets in DASHBOARDS:
        if name in existing:
            call("DELETE", f"/dashboards/{existing[name]}")
        s, d = call("POST", "/dashboards", {"name": name, "description": desc, "filters": filters})
        if s != 201:
            print(f"FAILED dashboard {name}: {d}"); failures += 1; continue
        for title, ct, spec, layout, options in widgets:
            s, w = call("POST", f"/dashboards/{d['id']}/widgets",
                        {"title": title, "chart_type": ct, "spec": spec, "layout": layout, "options": options})
            if s != 201:
                print(f"  FAILED widget {title}: {w}"); failures += 1; continue
            # run it the way the dashboard does (with the default filter values) to prove it returns data
            vals = [{"field": f["field"], "type": f["type"], "value": f.get("value")} for f in filters]
            s, r = call("POST", f"/dashboards/{d['id']}/widgets/{w['id']}/data", {"filters": vals})
            rows = r.get("rows") if s == 200 else None
            status = f"{len(rows)} row(s)" if rows else f"NO DATA ({r.get('detail') if isinstance(r, dict) else s})"
            if not rows:
                failures += 1
            print(f"  {name} / {title}: {status}")
        print(f"{name}: dashboard {d['id']}, {len(widgets)} widgets")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
