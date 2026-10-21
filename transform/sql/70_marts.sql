-- =============================================================================
-- 70  Mart views: the only layer dashboards and agents read.
-- Business definitions live here, once. All money excludes GST (BR-001).
-- =============================================================================

-- Net sales by day: invoices minus returns (BR-004). Employee exhibition stock is not a sale (BR-011);
-- related-party (Dileep group exports, BR-007) and unclassified lines are kept and labelled, never hidden.
CREATE OR REPLACE VIEW mart.v_net_sales_daily AS
WITH lines AS (
    SELECT bill_date_key AS date_key, channel_key, location_key, product_key, partner_key,
           quantity AS units_sold, 0::NUMERIC AS units_returned, coalesce(net_sales_amount, 0) AS sales_amount, 0::NUMERIC AS returns_amount,
           (net_amount_method = 'MISSING') AS has_missing_amount
    FROM core.fact_sales_line
    UNION ALL
    SELECT return_date_key, channel_key, receiving_location_key, product_key, partner_key,
           0, quantity, 0, coalesce(net_return_amount, 0), (net_amount_method = 'MISSING')
    FROM core.fact_return_line)
SELECT d.calendar_date, d.fiscal_year_label, d.fiscal_month, d.month_start_date,
       c.channel_code, c.channel_name, c.sub_channel_name, c.channel_group,
       l.location_code, l.location_name, p.sku_code, p.product_name, p.item_type, p.lifecycle_status, p.category,
       pt.partner_type, pt.is_related_party, pt.is_sale_or_return,
       sum(units_sold) AS units_sold, sum(units_returned) AS units_returned,
       sum(sales_amount) AS gross_sales, sum(returns_amount) AS returns, sum(sales_amount) - sum(returns_amount) AS net_sales,
       bool_or(has_missing_amount) AS has_missing_amount
FROM lines x
JOIN core.dim_date d ON d.date_key = x.date_key
JOIN core.dim_channel c ON c.channel_key = x.channel_key
JOIN core.dim_location l ON l.location_key = x.location_key
JOIN core.dim_product p ON p.product_key = x.product_key
JOIN core.dim_partner pt ON pt.partner_key = x.partner_key
WHERE NOT pt.is_internal
GROUP BY d.calendar_date, d.fiscal_year_label, d.fiscal_month, d.month_start_date, c.channel_code, c.channel_name, c.sub_channel_name,
         c.channel_group, l.location_code, l.location_name, p.sku_code, p.product_name, p.item_type, p.lifecycle_status, p.category,
         pt.partner_type, pt.is_related_party, pt.is_sale_or_return;

-- Current stock per location and SKU, each location counted ONCE from its system of record (BR-025).
-- Locations with no report of their own (partner consignment, employees) come from the ledger (BR-022, BR-029):
-- movements since the period start only, so those balances lack an opening figure (basis says so).
CREATE OR REPLACE VIEW mart.v_stock_position_latest AS
WITH sor AS (
    SELECT l.location_key, CASE l.inventory_system_of_record WHEN 'ERP' THEN 'ERP_INVENTORY_SNAPSHOT'
           WHEN 'BLINKIT' THEN 'BLINKIT_INVENTORY' WHEN 'INSTAMART' THEN 'INSTAMART_INVENTORY' END AS source_name
    FROM core.dim_location l WHERE l.is_stock_holding AND NOT l.is_unknown_member),
latest AS (SELECT source_name, max(snapshot_date_key) AS snapshot_date_key FROM core.fact_inventory_snapshot GROUP BY source_name),
snap AS (
    SELECT s.location_key, s.product_key, sum(s.on_hand_qty) AS on_hand_qty, sum(coalesce(s.sellable_qty, s.on_hand_qty)) AS sellable_qty,
           sum(s.in_transit_qty) AS in_transit_qty, s.snapshot_date_key AS as_of_date_key, 'SNAPSHOT: ' || s.source_name AS basis
    FROM core.fact_inventory_snapshot s
    JOIN sor ON sor.location_key = s.location_key AND sor.source_name = s.source_name
    JOIN latest lt ON lt.source_name = s.source_name AND lt.snapshot_date_key = s.snapshot_date_key
    GROUP BY s.location_key, s.product_key, s.snapshot_date_key, s.source_name),
ledger AS (
    SELECT m.location_key, m.product_key, sum(m.quantity) AS on_hand_qty, sum(m.quantity) AS sellable_qty, NULL::NUMERIC AS in_transit_qty,
           max(m.movement_date_key) AS as_of_date_key, 'LEDGER: movements in period, no opening balance' AS basis
    FROM core.fact_stock_movement m JOIN core.dim_location l ON l.location_key = m.location_key
    WHERE l.inventory_system_of_record = 'NONE' AND l.is_stock_holding
    GROUP BY m.location_key, m.product_key HAVING sum(m.quantity) <> 0)
SELECT l.location_code, l.location_name, l.location_type, l.operated_by, l.is_sellable_stock, l.is_active,
       p.sku_code, p.product_name, p.item_type, p.lifecycle_status, p.category, p.current_mrp,
       x.on_hand_qty, x.sellable_qty, x.in_transit_qty, d.calendar_date AS as_of_date, x.basis
FROM (SELECT * FROM snap UNION ALL SELECT * FROM ledger) x
JOIN core.dim_location l ON l.location_key = x.location_key
JOIN core.dim_product p ON p.product_key = x.product_key
JOIN core.dim_date d ON d.date_key = x.as_of_date_key;

-- Transfers sent but not yet received (OUT line with no IN line for the same document and SKU)
CREATE OR REPLACE VIEW mart.v_transfer_in_transit AS
SELECT o.document_number, d.calendar_date AS sent_date,
       (SELECT period_end FROM meta.transform_run WHERE status = 'SUCCEEDED' ORDER BY transform_run_id DESC LIMIT 1) - d.calendar_date AS days_in_transit,
       fl.location_name AS from_location, tl.location_name AS to_location, tl.location_type AS to_location_type,
       p.sku_code, p.product_name, o.quantity AS units, o.transfer_value
FROM core.fact_stock_transfer_line o
JOIN core.dim_date d ON d.date_key = o.document_date_key
JOIN core.dim_location fl ON fl.location_key = o.from_location_key
JOIN core.dim_location tl ON tl.location_key = o.to_location_key
JOIN core.dim_product p ON p.product_key = o.product_key
WHERE o.movement_direction = 'OUT'
  AND NOT EXISTS (SELECT 1 FROM core.fact_stock_transfer_line i WHERE i.movement_direction = 'IN'
                  AND i.linked_outward_document = o.document_number AND i.product_key = o.product_key);

-- Open purchase orders, as of the PO export. document_type = the export's Document Remark; once BR-031 is
-- confirmed (po_document_remark_confirmed) return-inward documents are not purchases and are left out (BR-013).
CREATE OR REPLACE VIEW mart.v_open_purchase_orders AS
SELECT po.po_number, d.calendar_date AS po_date, dd.calendar_date AS due_date, po.as_of_date,
       po.as_of_date - d.calendar_date AS days_open,
       CASE WHEN dd.calendar_date < po.as_of_date THEN po.as_of_date - dd.calendar_date END AS days_overdue,
       pt.partner_name AS supplier, pt.partner_type AS supplier_type, p.sku_code, p.product_name, p.lifecycle_status,
       po.order_qty, po.received_qty, po.pending_qty, po.purchase_price, po.po_status, po.document_type
FROM core.fact_purchase_order_line po
JOIN core.dim_date d ON d.date_key = po.po_date_key
LEFT JOIN core.dim_date dd ON dd.date_key = po.due_date_key
JOIN core.dim_partner pt ON pt.partner_key = po.partner_key
JOIN core.dim_product p ON p.product_key = po.product_key
WHERE po.po_status IN ('OPEN','IN_PROGRESS','OVERDUE') AND coalesce(po.pending_qty, 0) > 0
  AND NOT (po.document_type = 'RETURN' AND EXISTS (SELECT 1 FROM meta.pipeline_setting
           WHERE setting_key = 'po_document_remark_confirmed' AND setting_value = 'true'));

-- Supplier lead time: PO date to the receipt date the report gives. Part-delivered lines are flagged approximate (G-027).
-- Return-inward documents have no supplier lead time: left out once BR-031 is confirmed, as above.
CREATE OR REPLACE VIEW mart.v_supplier_lead_time AS
SELECT pt.partner_name AS supplier, pt.partner_type AS supplier_type, po.po_number, p.sku_code, p.product_name,
       d.calendar_date AS po_date, g2.calendar_date AS receipt_date, g2.calendar_date - d.calendar_date AS lead_time_days,
       g.receipt_count, (g.receipt_count > 1) AS is_approximate, g.received_qty, po.order_qty, po.document_type
FROM core.fact_goods_receipt_line g
JOIN core.fact_purchase_order_line po ON po.po_line_id = g.po_line_id
JOIN core.dim_date d ON d.date_key = po.po_date_key
JOIN core.dim_date g2 ON g2.date_key = g.grn_date_key
JOIN core.dim_partner pt ON pt.partner_key = g.partner_key
JOIN core.dim_product p ON p.product_key = g.product_key
WHERE NOT (po.document_type = 'RETURN' AND EXISTS (SELECT 1 FROM meta.pipeline_setting
           WHERE setting_key = 'po_document_remark_confirmed' AND setting_value = 'true'));

-- Days of cover: sellable stock now / average units sold from that location per day over the last 30 days of the period
CREATE OR REPLACE VIEW mart.v_days_of_cover AS
WITH period AS (SELECT period_end FROM meta.transform_run WHERE status = 'SUCCEEDED' ORDER BY transform_run_id DESC LIMIT 1),
sold AS (
    SELECT l.location_code, p.sku_code, sum(s.quantity) / 30.0 AS avg_daily_units
    FROM core.fact_sales_line s
    JOIN core.dim_date d ON d.date_key = s.bill_date_key
    JOIN core.dim_location l ON l.location_key = s.location_key
    JOIN core.dim_product p ON p.product_key = s.product_key
    JOIN core.dim_partner pt ON pt.partner_key = s.partner_key
    WHERE NOT pt.is_internal AND d.calendar_date > (SELECT period_end FROM period) - 30
    GROUP BY l.location_code, p.sku_code)
SELECT sp.location_code, sp.location_name, sp.location_type, sp.sku_code, sp.product_name, sp.lifecycle_status,
       sp.sellable_qty, round(coalesce(so.avg_daily_units, 0), 3) AS avg_daily_units_30d,
       CASE WHEN so.avg_daily_units > 0 THEN round(sp.sellable_qty / so.avg_daily_units, 1) END AS days_of_cover,
       sp.as_of_date, sp.basis
FROM mart.v_stock_position_latest sp
LEFT JOIN sold so ON so.location_code = sp.location_code AND so.sku_code = sp.sku_code
WHERE sp.is_sellable_stock AND sp.item_type = 'TRADING';

-- Returns by day, channel and reason
CREATE OR REPLACE VIEW mart.v_returns_daily AS
SELECT d.calendar_date, d.month_start_date, r.source_name, c.channel_name, c.sub_channel_name, pt.partner_type,
       rr.reason_name, l.location_name AS received_at, p.sku_code, p.product_name,
       sum(r.quantity) AS units_returned, sum(coalesce(r.net_return_amount, 0)) AS returns_value
FROM core.fact_return_line r
JOIN core.dim_date d ON d.date_key = r.return_date_key
JOIN core.dim_channel c ON c.channel_key = r.channel_key
JOIN core.dim_partner pt ON pt.partner_key = r.partner_key
JOIN core.dim_return_reason rr ON rr.return_reason_key = r.return_reason_key
JOIN core.dim_location l ON l.location_key = r.receiving_location_key
JOIN core.dim_product p ON p.product_key = r.product_key
WHERE NOT pt.is_internal
GROUP BY d.calendar_date, d.month_start_date, r.source_name, c.channel_name, c.sub_channel_name, pt.partner_type, rr.reason_name,
         l.location_name, p.sku_code, p.product_name;

-- Partners needing a decision: who is unclassified or classified by elimination, and how much business they carry
CREATE OR REPLACE VIEW mart.v_partner_review AS
SELECT pt.partner_name, pt.partner_role, pt.partner_type, pt.classification_method, pt.classification_rule_id, pt.is_confirmed,
       count(s.sales_line_id) AS invoice_lines, coalesce(sum(s.net_sales_amount), 0) AS net_sales,
       min(d.calendar_date) AS first_invoice, max(d.calendar_date) AS last_invoice
FROM core.dim_partner pt
LEFT JOIN core.fact_sales_line s ON s.partner_key = pt.partner_key
LEFT JOIN core.dim_date d ON d.date_key = s.bill_date_key
WHERE NOT pt.is_unknown_member AND (pt.partner_type = 'UNCLASSIFIED' OR NOT pt.is_confirmed OR pt.classification_method = 'DEFAULT_RULE' AND pt.partner_type <> 'D2C_CHANNEL_ACCOUNT')
GROUP BY pt.partner_name, pt.partner_role, pt.partner_type, pt.classification_method, pt.classification_rule_id, pt.is_confirmed;

-- What data exists for which month (so "no data" is never shown as zero)
CREATE OR REPLACE VIEW mart.v_data_coverage AS
SELECT bp.process_name, bp.build_phase, pc.period_month, pc.coverage, pc.sources, pc.notes
FROM meta.process_coverage pc JOIN meta.business_process bp USING (process_code);

-- Data-quality results of the latest successful build
CREATE OR REPLACE VIEW mart.v_data_quality_latest AS
SELECT q.check_name, q.target_table, q.severity, q.outcome, q.failed_row_count, q.details, r.finished_at
FROM meta.dq_check_result q JOIN meta.transform_run r ON r.transform_run_id = q.transform_run_id
WHERE r.transform_run_id = (SELECT max(transform_run_id) FROM meta.transform_run WHERE status = 'SUCCEEDED');
