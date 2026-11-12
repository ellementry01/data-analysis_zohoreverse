"""
Builds the executive dashboards of the prototype in a workspace connected to the Ellementry warehouse, through the
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
# slow stock: not sold anywhere for over 180 days (bands 4-6 of mart.v_slow_stock.sales_age_band)
SLOW = {"field": "slow_stock.sales_age_band", "op": "in",
        "value": ["4. Last sale 181-365 days ago", "5. Last sale over a year ago", "6. No sale since Apr 2025"]}
SLOW_COVER = {"field": "days_of_cover.cover_band", "op": "in", "value": ["5. Over a year", "6. Nothing sold or sent in 30 days"]}
# Fulfilment table columns: "deliveries" counts every WMS order (cancelled and in transit too), so it is shown as Orders
ORDERS = {"metric": "deliveries", "alias": "orders", "label": "Orders"}
RTO = {"metric": "rto_rate", "label": "RTO rate (website)"}
LATE = {"metric": "late_shipment_rate", "label": "Shipped late"}
DELIVERY_DAYS = {"metric": "avg_ship_to_deliver_days", "label": "Delivery time (days)"}
IM_SELLOUT = {"field": "quick_commerce_sell_out_daily.platform", "op": "eq", "value": "Instamart"}
IM_STOCK = {"field": "partner_stock_monthly.partner", "op": "eq", "value": "INSTAMART"}
# Amazon's FBA report states the condition on return; the self-shipped report (warehouse 2.17) does not
FBA_ONLY = {"field": "return_reasons.sub_channel_name", "op": "eq", "value": "FBA"}
# Widgets renamed in place: (dashboard, new title) -> the title it had before. update_dashboard_widgets.py finds the
# live widget by its old title and renames it, so the dashboard and widget ids stay the same.
RENAMED_FROM = {
    ("Returns", "Amazon returns by reason (units)"): "Amazon FBA returns by reason (units)",
    ("Instamart", "Stock with Instamart (at least)"): "Stock with Instamart (since Apr 2025)",
    ("Instamart", "Stock with Instamart over time (at least)"): "Stock with Instamart over time",
}
# BR-031 confirmed (warehouse 2.10): the warehouse already leaves return-inward lines out; the filter is a safety net
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


# Stable key and domain of each dashboard. The key never changes (assistant threads and memories hang off it), even
# when the dashboard is renamed or rebuilt; the domain groups dashboards for the domain assistants.
DASHBOARD_META = {
    "Executive overview": ("executive-overview", "executive"),
    "Sales & channels": ("sales-channels", "sales"),
    "Returns": ("returns", "operations"),
    "Stock": ("stock", "stock"),
    "Fulfilment": ("fulfilment", "operations"),
    "Purchasing & transfers": ("purchasing-transfers", "operations"),
    "Discontinued & slow stock": ("discontinued-slow-stock", "stock"),
    "Days of cover": ("days-of-cover", "stock"),
    "Instamart": ("instamart", "sales"),
    "Data health": ("data-health", "data"),
}

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
     "Customer and partner returns, excluding GST. The ERP records no return reasons (gap G-009); the reasons below come from "
     "Amazon's own reports, in units: FBA orders and Amazon orders we ship ourselves. 'Not delivered' is parcels refused or "
     "undelivered. The condition on return is known for FBA only.",
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
            extra=[{"metric": "units_returned"}]), 0, 12, 12, 6),
      chart("Amazon returns by reason (units)", "hbar", top("return_reasons.reason_group", "amazon_units_returned", 10), 0, 18, 6, 5,
            drill=["return_reasons.sub_channel_name", "return_reasons.reason"]),
      chart("Condition when returned (Amazon FBA)", "donut",
            {"dimensions": [{"field": "return_reasons.condition_on_return"}], "measures": [{"metric": "amazon_units_returned"}],
             "filters": [FBA_ONLY]}, 6, 18, 6, 5),
      chart("Amazon return reasons in detail", "table",
            top("return_reasons.reason", "amazon_units_returned", 20, extra=[]), 0, 23, 6, 6),
      chart("Products returned most on Amazon (units)", "table",
            top("return_reasons.product_name", "amazon_units_returned", 15), 6, 23, 6, 6)]),

    ("Stock",
     "Stock on 15 Sep 2026, the latest stock report, at every company location: Bagru warehouse, own stores, Amazon FBA and "
     "other company locations. Trading items only, valued at cost (unit cost from the ERP item master, excluding GST); "
     "every unit in stock has a cost. Stock held by franchise, Shoppers Stop and quick-commerce partners is not included: "
     "we only know what was sent and returned, not what they sold, so it is not a stock count. Closed stores are marked "
     "'(closed)' and still show the stock they hold. 'Essential - DFAL' is a company location still being confirmed (D-073). "
     "Month-end trend: from the ERP's month-end stock reports since 31 Mar 2025, valued at today's unit cost. Bagru fell by "
     "about 16,700 units (about ₹1 Cr) in May 2025 with no sale, transfer or receipt recorded for it; the ERP documents "
     "behind it (scrap, adjustments) are still being loaded. Use the Location and Category filters to focus; click a bar to "
     "drill down.",
     [{"id": "location", "type": "values", "label": "Location", "field": "locations.location_name", "value": []},
      {"id": "category", "type": "values", "label": "Category", "field": "products.category", "value": []}],
     [kpi("Stock value at cost", "stock_value_cost", 0, 0, compare=None, filters=[TRADING, OWN_STOCK]),
      kpi("Units on hand", "stock_on_hand", 2, 0, compare=None, filters=[TRADING, OWN_STOCK]),
      ("Products in stock", "kpi",
       {"measures": [{"field": "stock_position_latest.sku_code", "agg": "count_distinct", "alias": "n", "label": "Products in stock"}],
        "filters": [TRADING, OWN_STOCK, {"field": "stock_position_latest.on_hand_qty", "op": "gt", "value": 0}]},
       {"x": 4, "y": 0, "w": 2, "h": 2}, {}),
      kpi("Continued stock at cost", "stock_value_cost", 6, 0, compare=None,
          filters=[TRADING, OWN_STOCK, {"field": "stock_position_latest.lifecycle_status", "op": "eq", "value": "CONTINUED"}]),
      kpi("Discontinued stock at cost", "stock_value_cost", 8, 0, compare=None,
          filters=[TRADING, OWN_STOCK, {"field": "stock_position_latest.lifecycle_status", "op": "eq", "value": "DISCONTINUED"}]),
      kpi("Units with no cost", "stock_units_no_cost", 10, 0, compare=None, filters=[TRADING, OWN_STOCK]),
      chart("Stock value by location group", "hbar", top("stock_position_latest.location_group", "stock_value_cost", 10, [TRADING, OWN_STOCK]), 0, 2, 6, 5,
            drill=["stock_position_latest.location"]),
      chart("Continued vs discontinued (value at cost)", "donut",
            {"dimensions": [{"field": "stock_position_latest.lifecycle_status"}], "measures": [{"metric": "stock_value_cost"}],
             "filters": [TRADING, OWN_STOCK]}, 6, 2, 6, 5),
      chart("Stock value by category", "hbar", top("stock_position_latest.category_label", "stock_value_cost", 15, [TRADING, OWN_STOCK]), 0, 7, 6, 6,
            drill=["stock_position_latest.sub_category_label", "stock_position_latest.product_name"]),
      chart("Stock by location", "table",
            {"dimensions": [{"field": "stock_position_latest.location", "label": "Location"}],
             "measures": [{"metric": "stock_value_cost", "alias": "v", "label": "Value at cost"},
                          {"metric": "stock_on_hand", "label": "Units"}],
             "filters": [TRADING, OWN_STOCK], "sort": [{"field": "v", "dir": "desc"}], "limit": 25}, 6, 7, 6, 6),
      chart("Top 20 products by stock value", "table",
            {"dimensions": [{"field": "stock_position_latest.sku_code", "label": "SKU"},
                            {"field": "stock_position_latest.product_name", "label": "Product"},
                            {"field": "stock_position_latest.category_label", "label": "Category"},
                            {"field": "stock_position_latest.lifecycle_status", "label": "Status"}],
             "measures": [{"metric": "stock_value_cost", "alias": "v", "label": "Value at cost"},
                          {"metric": "stock_on_hand", "label": "Units"}],
             "filters": [TRADING, OWN_STOCK], "sort": [{"field": "v", "dir": "desc"}], "limit": 20}, 0, 13, 12, 7),
      chart("Stock value at cost, month-end (at today's unit cost)", "line",
            {"dimensions": [MONTH], "measures": [{"metric": "stock_value_cost_history"}],
             "filters": [{"field": "stock_position_daily.item_type", "op": "eq", "value": "TRADING"}]}, 0, 20, 12, 5)]),

    ("Fulfilment",
     "Website and marketplace orders handled by the Bagru warehouse (WMS order report), by order date, 1 Apr 2025 - 15 Sep 2026. "
     "Orders = every order in the WMS, including cancelled ones and ones still on the way. RTO (returned to origin) is "
     "recorded for the website only: marketplaces handle their own RTO and never report it back. Late = shipped after the "
     "ship-by time. Delivery time is measured where couriers report delivery dates (Nykaa, FNP and Flipkart don't). "
     "A blank rate means 'not reported', not zero. 'Shipped, no delivery update' are mostly orders on channels that send no "
     "delivery dates. Use the Order date and Channel filters; Compare shows the same period last year.",
     [{"id": "period", "type": "date_range", "label": "Order date", "field": "@time", "value": ALL_DATA},
      {"id": "channel", "type": "values", "label": "Channel", "field": "fulfilment.channel_name", "value": []}],
     [kpi("Orders", "deliveries", 0, 0, compare=None),
      kpi("Delivered", "deliveries", 2, 0, compare=None, filters=[{"field": "fulfilment.order_status", "op": "eq", "value": "Delivered"}]),
      kpi("RTO rate (website)", "rto_rate", 4, 0, compare=None),
      kpi("Shipped late", "late_shipment_rate", 6, 0, compare=None),
      kpi("Order to ship (hours)", "avg_order_to_ship_hours", 8, 0, compare=None),
      kpi("Delivery time (days)", "avg_ship_to_deliver_days", 10, 0, compare=None),
      chart("Orders by month and payment type", "stacked_bar",
            {"dimensions": [MONTH, {"field": "fulfilment.payment_type"}], "measures": [ORDERS]}, 0, 2, 7, 5),
      chart("Order status", "hbar",
            {"dimensions": [{"field": "fulfilment.order_status"}], "measures": [ORDERS],
             "sort": [{"field": "orders", "dir": "desc"}], "limit": 12}, 7, 2, 5, 5),
      chart("RTO rate (website) and late shipments, by month", "line",
            {"dimensions": [MONTH], "measures": [{"metric": "rto_rate"}, {"metric": "late_shipment_rate"}]}, 0, 7, 7, 5),
      chart("Website RTO rate: cash on delivery vs prepaid", "bar",
            {"dimensions": [{"field": "fulfilment.payment_type"}], "measures": [{"metric": "rto_rate"}]}, 7, 7, 5, 5),
      chart("Orders, RTO and late shipments by channel", "table",
            {"dimensions": [{"field": "fulfilment.channel_name", "label": "Channel"}],
             "measures": [ORDERS, RTO, LATE, {"metric": "avg_order_to_ship_hours", "label": "Order to ship (hours)"}, DELIVERY_DAYS],
             "sort": [{"field": "orders", "dir": "desc"}], "limit": 12}, 0, 12, 7, 6),
      chart("Couriers", "table",
            {"dimensions": [{"field": "fulfilment.courier_group", "label": "Courier"}], "measures": [ORDERS, RTO, DELIVERY_DAYS],
             "sort": [{"field": "orders", "dir": "desc"}], "limit": 12}, 7, 12, 5, 6)]),

    ("Purchasing & transfers",
     "Open purchase-order lines from the latest PO exports, and stock sent between locations but not yet received. "
     "Purchases only: return-inward lines (PO Document Remark 'Return', rule BR-031, confirmed) are left out. "
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

    ("Discontinued & slow stock",
     "Trading stock on 15 Sep 2026 at cost, by how long since the product last sold anywhere (all channels, invoices). "
     "'No sale since Apr 2025' = no invoice in the loaded period. Stock at partners is not included.",
     [],
     [kpi("Trading stock at cost", "slow_stock_value_cost", 0, 0, w=3, compare=None),
      kpi("Not sold in over 180 days", "slow_stock_value_cost", 3, 0, w=3, compare=None, filters=[SLOW]),
      kpi("No sale since Apr 2025", "slow_stock_value_cost", 6, 0, w=3, compare=None,
          filters=[{"field": "slow_stock.sales_age_band", "op": "eq", "value": "6. No sale since Apr 2025"}]),
      kpi("Discontinued stock at cost", "slow_stock_value_cost", 9, 0, w=3, compare=None,
          filters=[{"field": "slow_stock.lifecycle_status", "op": "eq", "value": "DISCONTINUED"}]),
      chart("Stock by time since last sale (at cost)", "bar",
            {"dimensions": [{"field": "slow_stock.sales_age_band", "alias": "band"}], "measures": [{"metric": "slow_stock_value_cost"}],
             "sort": [{"field": "band", "dir": "asc"}]}, 0, 2, 6, 5),
      chart("Continued vs discontinued, by time since last sale", "stacked_bar",
            {"dimensions": [{"field": "slow_stock.sales_age_band", "alias": "band"}, {"field": "slow_stock.lifecycle_status"}],
             "measures": [{"metric": "slow_stock_value_cost"}], "sort": [{"field": "band", "dir": "asc"}]}, 6, 2, 6, 5),
      chart("Slow stock (over 180 days) by category", "hbar", top("slow_stock.category_label", "slow_stock_value_cost", 12, [SLOW]), 0, 7, 6, 6,
            drill=["slow_stock.sub_category_label"]),
      chart("Slow stock (over 180 days) by location", "hbar", top("slow_stock.location_name", "slow_stock_value_cost", 12, [SLOW]), 6, 7, 6, 6),
      chart("Slowest stock: top 25 products by value", "table",
            {"dimensions": [{"field": "slow_stock.sku_code"}, {"field": "slow_stock.product_name"}, {"field": "slow_stock.lifecycle_status"},
                            {"field": "slow_stock.sales_age_band"}, {"field": "slow_stock.last_sale_date"}],
             "measures": [{"metric": "slow_stock_value_cost", "alias": "v"},
                          {"field": "slow_stock.on_hand_qty", "agg": "sum", "alias": "units", "label": "Units on hand"}],
             "filters": [SLOW], "sort": [{"field": "v", "dir": "desc"}], "limit": 25}, 0, 13, 12, 7)]),

    ("Days of cover",
     "How long sellable stock lasts at each location at the last 30 days' pace (units sold plus units sent out by transfer), "
     "on 15 Sep 2026, valued at cost. Under 30 days = may run out; over a year = overstock.",
     [],
     [kpi("Sellable stock at cost", "cover_stock_value_cost", 0, 0, w=4, compare=None),
      kpi("Under 30 days of cover", "cover_stock_value_cost", 4, 0, w=4, compare=None,
          filters=[{"field": "days_of_cover.cover_band", "op": "eq", "value": "1. Under 30 days"}]),
      kpi("Over a year, or nothing sold in 30 days", "cover_stock_value_cost", 8, 0, w=4, compare=None, filters=[SLOW_COVER]),
      chart("Stock by days of cover (at cost)", "bar",
            {"dimensions": [{"field": "days_of_cover.cover_band", "alias": "band"}], "measures": [{"metric": "cover_stock_value_cost"}],
             "sort": [{"field": "band", "dir": "asc"}]}, 0, 2, 6, 5),
      chart("Cover by location (at cost)", "stacked_bar",
            {"dimensions": [{"field": "days_of_cover.location_name"}, {"field": "days_of_cover.cover_band"}],
             "measures": [{"metric": "cover_stock_value_cost"}]}, 6, 2, 6, 5),
      chart("May run out: under 30 days of cover", "table",
            {"dimensions": [{"field": "days_of_cover.location_name"}, {"field": "days_of_cover.sku_code"}, {"field": "days_of_cover.product_name"}],
             "measures": [{"field": "days_of_cover.days_of_cover", "agg": "min", "alias": "cover", "label": "Days of cover"},
                          {"field": "days_of_cover.sellable_qty", "agg": "sum", "alias": "qty", "label": "Sellable units"},
                          {"field": "days_of_cover.avg_daily_units_30d", "agg": "sum", "alias": "pace", "label": "Sold per day (30 days)"}],
             "filters": [{"field": "days_of_cover.cover_band", "op": "eq", "value": "1. Under 30 days"}],
             "sort": [{"field": "pace", "dir": "desc"}], "limit": 25}, 0, 7, 12, 7),
      chart("Overstock: over a year of cover, by value", "table",
            {"dimensions": [{"field": "days_of_cover.location_name"}, {"field": "days_of_cover.sku_code"}, {"field": "days_of_cover.product_name"}],
             "measures": [{"metric": "cover_stock_value_cost", "alias": "v"},
                          {"field": "days_of_cover.days_of_cover", "agg": "min", "alias": "cover", "label": "Days of cover"}],
             "filters": [{"field": "days_of_cover.cover_band", "op": "eq", "value": "5. Over a year"}],
             "sort": [{"field": "v", "dir": "desc"}], "limit": 25}, 0, 14, 12, 7)]),

    ("Instamart",
     "Instamart, sale-or-return. Sent / returned = our invoices and credit notes to Instamart's six buying accounts (rule BR-034); "
     "sold = Instamart's consumer sell-out (demand, never our revenue: BR-024). Stock with Instamart = sent minus returned minus "
     "sold since 1 Apr 2025, plus the least stock Instamart must have held on 1 Apr 2025 (without it some products would show "
     "below zero). Instamart's past stock cannot be fetched, so this is a floor, not a stock count.",
     [{"id": "period", "type": "date_range", "label": "Period", "field": "@time", "value": ALL_DATA}],
     [kpi("Units sold by Instamart", "qc_units_sold", 0, 0, compare=None, filters=[IM_SELLOUT]),
      kpi("Sell-out value (GMV)", "qc_sell_out_value", 2, 0, compare=None, filters=[IM_SELLOUT]),
      kpi("Invoiced to Instamart (net, excl. GST)", "net_sales", 4, 0, compare=None,
          filters=[{"field": "net_sales_daily.channel_name", "op": "eq", "value": "Instamart"}]),
      kpi("Units sent to Instamart", "partner_units_sent", 6, 0, compare=None, filters=[IM_STOCK]),
      kpi("Units returned by Instamart", "partner_units_returned", 8, 0, compare=None, filters=[IM_STOCK]),
      kpi("Stock with Instamart (at least)", "partner_stock_at_least", 10, 0, compare=None, filters=[IM_STOCK]),
      chart("Units sent vs sold, by month", "bar",
            {"dimensions": [MONTH], "measures": [{"metric": "partner_units_sent"}, {"metric": "partner_units_sold"},
                                                 {"metric": "partner_units_returned"}], "filters": [IM_STOCK]}, 0, 2, 8, 5),
      chart("Stock with Instamart over time (at least)", "line",
            {"dimensions": [MONTH], "measures": [{"metric": "partner_stock_at_least"}], "filters": [IM_STOCK]}, 8, 2, 4, 5),
      chart("Top 15 products sold on Instamart", "table",
            top("quick_commerce_sell_out_daily.product_name", "qc_units_sold", 15, [IM_SELLOUT], [{"metric": "qc_sell_out_value"}]), 0, 7, 6, 6),
      chart("Instamart sales by city", "hbar", top("quick_commerce_sell_out_daily.city", "qc_units_sold", 15, [IM_SELLOUT]), 6, 7, 6, 6)]),

    ("Data health",
     "How complete and trustworthy the data behind the dashboards is: the quality checks of the latest warehouse build, the "
     "data still missing (gaps), and the source files loaded. A blocking error stops a build, so a published build always shows 0.",
     [],
     [kpi("Blocking data errors", "dq_blocking_errors", 0, 0, w=3, compare=None),
      kpi("Checks flagging rows (warnings)", "dq_failed_checks", 3, 0, w=3, compare=None),
      kpi("Open data gaps", "open_data_gaps", 6, 0, w=3, compare=None),
      kpi("Source files loaded", "files_loaded", 9, 0, w=3, compare=None),
      chart("Quality checks that flag rows (latest build)", "table",
            {"dimensions": [{"field": "data_quality_latest.check_name"}, {"field": "data_quality_latest.target_table"},
                            {"field": "data_quality_latest.severity"}, {"field": "data_quality_latest.details"}],
             "measures": [{"field": "data_quality_latest.failed_row_count", "agg": "sum", "alias": "rows", "label": "Rows flagged"}],
             "filters": [{"field": "data_quality_latest.outcome", "op": "eq", "value": "FAIL"}],
             "sort": [{"field": "rows", "dir": "desc"}], "limit": 60}, 0, 2, 12, 8),
      chart("Open data gaps", "table",
            {"dimensions": [{"field": "data_gaps.gap_id", "alias": "gap"}, {"field": "data_gaps.title"}, {"field": "data_gaps.owner"},
                            {"field": "data_gaps.priority"}],
             "measures": [{"metric": "open_data_gaps", "alias": "n"}],
             "filters": [{"field": "data_gaps.status", "op": "neq", "value": "CLOSED"}],
             "sort": [{"field": "gap", "dir": "asc"}], "limit": 40}, 0, 10, 7, 8),
      chart("Files loaded, by source", "table",
            {"dimensions": [{"field": "load_batches.source_name"}],
             "measures": [{"metric": "files_loaded", "alias": "files"},
                          {"field": "load_batches.rows_loaded", "agg": "sum", "alias": "rows", "label": "Rows loaded"},
                          {"field": "load_batches.as_of_date", "agg": "max", "alias": "latest", "label": "Latest as-of date"}],
             "filters": [{"field": "load_batches.status", "op": "eq", "value": "LOADED"}],
             "sort": [{"field": "files", "dir": "desc"}], "limit": 30}, 7, 10, 5, 8)]),
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
            with urllib.request.urlopen(req, timeout=300) as r:
                return r.status, json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"null")

    live = call("GET", "/dashboards")[1]
    by_key = {d.get("key"): d["id"] for d in live}
    by_name = {d["name"]: d["id"] for d in live}
    failures = 0
    for name, desc, filters, widgets in DASHBOARDS:
        key, domain = DASHBOARD_META[name]
        old = by_key.get(key) or by_name.get(name)
        if old:
            call("DELETE", f"/dashboards/{old}")
        s, d = call("POST", "/dashboards", {"name": name, "description": desc, "filters": filters, "key": key, "domain": domain})
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
