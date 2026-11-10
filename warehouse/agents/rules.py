"""
The rules the agent runner evaluates (PRD-001 sections 4.4 and 5.3). Each rule is one SQL query that returns the
conditions that hold now, one row per condition:

    identity_key, product_key, location_key, document_ref, severity, metric_value, threshold_value, message, details

Queries read mart views and core dimensions only (never raw). %(name)s parameters come from the run context:
as_of (the build's period end) and the settings the rule names. Messages are complete sentences with every number
the alert relies on, so the app and the assistants can quote them as they are.
"""
from __future__ import annotations

# Demand at a location in the 30 days to the build's period end: units sold (external customers) plus units sent out by
# transfer, the same definition as mart.v_days_of_cover.
_DEMAND = """
WITH sold AS (
    SELECT s.location_key, s.product_key, sum(s.quantity) AS units
    FROM core.fact_sales_line s
    JOIN core.dim_date d ON d.date_key = s.bill_date_key
    JOIN core.dim_partner pt ON pt.partner_key = s.partner_key
    WHERE NOT pt.is_internal AND d.calendar_date > %(as_of)s::DATE - 30 AND d.calendar_date <= %(as_of)s::DATE
    GROUP BY 1, 2),
sent AS (
    SELECT t.from_location_key AS location_key, t.product_key, sum(t.quantity) AS units
    FROM core.fact_stock_transfer_line t
    JOIN core.dim_date d ON d.date_key = t.document_date_key
    WHERE t.movement_direction = 'OUT' AND d.calendar_date > %(as_of)s::DATE - 30 AND d.calendar_date <= %(as_of)s::DATE
    GROUP BY 1, 2),
demand AS (
    SELECT coalesce(so.location_key, se.location_key) AS location_key, coalesce(so.product_key, se.product_key) AS product_key,
           coalesce(so.units, 0) AS sold, coalesce(se.units, 0) AS sent
    FROM sold so FULL JOIN sent se ON se.location_key = so.location_key AND se.product_key = so.product_key)
"""

STOCKOUT = _DEMAND + """
SELECT 'STK-A01|' || p.sku_code || '|' || l.location_code AS identity_key, p.product_key, l.location_key,
       NULL::TEXT AS document_ref, 'CRITICAL' AS severity,
       coalesce(sp.sellable_qty, 0) AS metric_value, 0 AS threshold_value,
       p.product_name || ' (' || p.sku_code || ') has no sellable stock at ' || l.location_name || '; in the 30 days to '
         || to_char(%(as_of)s::DATE, 'DD Mon YYYY') || ' it '
         || CASE WHEN dm.sold > 0 AND dm.sent > 0 THEN 'sold ' || trim(to_char(dm.sold, 'FM999G999G990')) || ' and sent out '
                                                         || trim(to_char(dm.sent, 'FM999G999G990')) || ' units'
                 WHEN dm.sold > 0 THEN 'sold ' || trim(to_char(dm.sold, 'FM999G999G990')) || ' units'
                 ELSE 'sent out ' || trim(to_char(dm.sent, 'FM999G999G990')) || ' units' END || ' there.' AS message,
       json_build_object('units_sold_30d', dm.sold, 'units_sent_30d', dm.sent,
                         'sellable_qty', coalesce(sp.sellable_qty, 0), 'location_type', l.location_type)::TEXT AS details
FROM demand dm
JOIN core.dim_location l ON l.location_key = dm.location_key
JOIN core.dim_product p ON p.product_key = dm.product_key
LEFT JOIN mart.v_stock_position_latest sp ON sp.location_code = l.location_code AND sp.sku_code = p.sku_code
WHERE dm.sold + dm.sent > 0 AND coalesce(sp.sellable_qty, 0) <= 0
  AND l.is_sellable_stock AND l.location_type <> 'PARTNER_CONSIGNMENT' AND l.location_key > 0
  AND p.item_type = 'TRADING' AND p.lifecycle_status = 'CONTINUED' AND p.product_key > 0
"""

LOW_COVER = """
SELECT 'STK-A02|' || c.sku_code || '|' || c.location_code AS identity_key, p.product_key, l.location_key,
       NULL::TEXT AS document_ref, 'WARNING' AS severity,
       c.days_of_cover AS metric_value, %(stock.low_cover_days)s::NUMERIC AS threshold_value,
       c.product_name || ' (' || c.sku_code || ') at ' || c.location_name || ': '
         || trim(to_char(c.sellable_qty, 'FM999G999G990')) || ' sellable units last '
         || trim(to_char(c.days_of_cover, 'FM999G990D0')) || ' days at '
         || trim(to_char(c.avg_daily_units_30d + c.avg_daily_transfer_out_30d, 'FM999G990D00'))
         || ' units a day (30-day average of units sold and sent out), below the '
         || %(stock.low_cover_days)s || '-day threshold.' AS message,
       json_build_object('sellable_qty', c.sellable_qty, 'avg_daily_sold_30d', c.avg_daily_units_30d,
                         'avg_daily_sent_30d', c.avg_daily_transfer_out_30d, 'days_of_cover', c.days_of_cover,
                         'location_type', c.location_type)::TEXT AS details
FROM mart.v_days_of_cover c
JOIN core.dim_location l ON l.location_code = c.location_code
JOIN core.dim_product p ON p.sku_code = c.sku_code
WHERE c.lifecycle_status = 'CONTINUED' AND c.location_type <> 'PARTNER_CONSIGNMENT'
  AND c.sellable_qty > 0 AND c.days_of_cover IS NOT NULL AND c.days_of_cover < %(stock.low_cover_days)s::NUMERIC
"""

# One alert per purchase order (not per line): pending units and the worst lateness across its overdue lines.
PO_OVERDUE = """
WITH po AS (
    SELECT po_number, min(supplier) AS supplier, min(po_date) AS po_date, min(due_date) AS due_date,
           max(days_overdue) AS days_overdue, sum(pending_qty) AS pending_units, count(*) AS lines
    FROM mart.v_open_purchase_orders
    WHERE document_type = 'PURCHASE' AND has_due_date AND days_overdue > 0 AND pending_qty > 0
    GROUP BY po_number)
SELECT 'OPS-A02|' || po_number AS identity_key, NULL::INTEGER AS product_key, NULL::SMALLINT AS location_key,
       po_number AS document_ref,
       CASE WHEN days_overdue > %(ops.po_overdue_critical_days)s::INTEGER THEN 'CRITICAL' ELSE 'WARNING' END AS severity,
       days_overdue AS metric_value, %(ops.po_overdue_critical_days)s::NUMERIC AS threshold_value,
       'Purchase order ' || po_number || ' from ' || coalesce(supplier, 'an unnamed supplier') || ': '
         || trim(to_char(pending_units, 'FM999G999G990')) || ' units on ' || lines || CASE WHEN lines = 1 THEN ' line' ELSE ' lines' END
         || ' still pending, ' || days_overdue || CASE WHEN days_overdue = 1 THEN ' day' ELSE ' days' END
         || ' past the due date of ' || to_char(due_date, 'DD Mon YYYY') || '.' AS message,
       json_build_object('supplier', supplier, 'po_date', po_date, 'due_date', due_date, 'pending_units', pending_units,
                         'overdue_lines', lines, 'days_overdue', days_overdue)::TEXT AS details
FROM po
"""

RULES = {
    "STK-A01": STOCKOUT,
    "STK-A02": LOW_COVER,
    "OPS-A02": PO_OVERDUE,
}
AGENTS = {"STOCK": "stock", "OPERATIONS": "operations"}
