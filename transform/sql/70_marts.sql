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

-- 2.4: category_label is never blank ('Uncategorised'); stock_value_mrp is NULL, not 0, when no source holds an MRP
-- (mrp_status = 'MRP missing'), so a value total can say how many units it leaves out.
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
       x.on_hand_qty, x.sellable_qty, x.in_transit_qty, d.calendar_date AS as_of_date, x.basis,
       coalesce(p.category, 'Uncategorised')::VARCHAR(100) AS category_label,
       CASE WHEN p.current_mrp > 0 THEN 'MRP known' ELSE 'MRP missing' END AS mrp_status,
       CASE WHEN p.current_mrp > 0 THEN x.on_hand_qty * p.current_mrp END AS stock_value_mrp
FROM (SELECT * FROM snap UNION ALL SELECT * FROM ledger) x
JOIN core.dim_location l ON l.location_key = x.location_key
JOIN core.dim_product p ON p.product_key = x.product_key
JOIN core.dim_date d ON d.date_key = x.as_of_date_key;

-- Transfers sent but not yet received (OUT line with no IN line for the same document and SKU).
-- 2.4: shipments to Amazon FBA are received by Amazon, which never posts an ERP inward entry (G-007). They are split
-- out (destination_group) so "not received" at own locations stands out as the real exception.
CREATE OR REPLACE VIEW mart.v_transfer_in_transit AS
SELECT o.document_number, d.calendar_date AS sent_date,
       (SELECT period_end FROM meta.transform_run WHERE status = 'SUCCEEDED' ORDER BY transform_run_id DESC LIMIT 1) - d.calendar_date AS days_in_transit,
       fl.location_name AS from_location, tl.location_name AS to_location, tl.location_type AS to_location_type,
       p.sku_code, p.product_name, o.quantity AS units, o.transfer_value,
       CASE WHEN tl.location_type = 'AMAZON_FBA' THEN 'To Amazon FBA' ELSE 'To own locations' END AS destination_group,
       CASE WHEN (SELECT period_end FROM meta.transform_run WHERE status = 'SUCCEEDED' ORDER BY transform_run_id DESC LIMIT 1)
                 - d.calendar_date <= 60 THEN 'In transit (60 days or less)' ELSE 'Not received after 60 days' END AS transit_status,
       CASE WHEN tl.location_type = 'AMAZON_FBA' THEN 'Amazon records the receipt, not the ERP (G-007): likely received, unconfirmed'
            ELSE 'No inward entry in the ERP' END AS receipt_note
FROM core.fact_stock_transfer_line o
JOIN core.dim_date d ON d.date_key = o.document_date_key
JOIN core.dim_location fl ON fl.location_key = o.from_location_key
JOIN core.dim_location tl ON tl.location_key = o.to_location_key
JOIN core.dim_product p ON p.product_key = o.product_key
WHERE o.movement_direction = 'OUT'
  AND NOT EXISTS (SELECT 1 FROM core.fact_stock_transfer_line i WHERE i.movement_direction = 'IN'
                  AND i.linked_outward_document = o.document_number AND i.product_key = o.product_key);

-- 2.4: due_status says when "overdue" is measured against an assumed export date (D-094) or cannot be judged.
-- Open purchase orders, as of the PO export. document_type = the export's Document Remark; once BR-031 is
-- confirmed (po_document_remark_confirmed) return-inward documents are not purchases and are left out (BR-013).
CREATE OR REPLACE VIEW mart.v_open_purchase_orders AS
SELECT po.po_number, d.calendar_date AS po_date, dd.calendar_date AS due_date, po.as_of_date,
       po.as_of_date - d.calendar_date AS days_open,
       CASE WHEN dd.calendar_date < po.as_of_date THEN po.as_of_date - dd.calendar_date END AS days_overdue,
       pt.partner_name AS supplier, pt.partner_type AS supplier_type, p.sku_code, p.product_name, p.lifecycle_status,
       po.order_qty, po.received_qty, po.pending_qty, po.purchase_price, po.po_status, po.document_type,
       b.as_of_is_assumed, (dd.calendar_date IS NOT NULL) AS has_due_date,
       CASE WHEN dd.calendar_date IS NULL THEN 'No due date'
            WHEN dd.calendar_date >= po.as_of_date THEN 'Not yet due'
            WHEN b.as_of_is_assumed THEN 'Overdue (export date assumed)'
            ELSE 'Overdue' END AS due_status
FROM core.fact_purchase_order_line po
JOIN meta.load_batch b ON b.batch_id = po.batch_id
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

-- Days of cover: sellable stock now / average units leaving that location per day over the last 30 days of the period
-- (sold, plus transferred out since 2.4: without transfers the central warehouse looked like years of cover)
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
    GROUP BY l.location_code, p.sku_code),
sent AS (      -- 2.4: stock also leaves a location by transfer (Bagru feeds the stores and FBA)
    SELECT l.location_code, p.sku_code, sum(t.quantity) / 30.0 AS avg_daily_units
    FROM core.fact_stock_transfer_line t
    JOIN core.dim_date d ON d.date_key = t.document_date_key
    JOIN core.dim_location l ON l.location_key = t.from_location_key
    JOIN core.dim_product p ON p.product_key = t.product_key
    WHERE t.movement_direction = 'OUT' AND d.calendar_date > (SELECT period_end FROM period) - 30
    GROUP BY l.location_code, p.sku_code)
SELECT sp.location_code, sp.location_name, sp.location_type, sp.sku_code, sp.product_name, sp.lifecycle_status,
       sp.sellable_qty, round(coalesce(so.avg_daily_units, 0), 3) AS avg_daily_units_30d,
       CASE WHEN coalesce(so.avg_daily_units, 0) + coalesce(se.avg_daily_units, 0) > 0
            THEN round(sp.sellable_qty / (coalesce(so.avg_daily_units, 0) + coalesce(se.avg_daily_units, 0)), 1) END AS days_of_cover,
       sp.as_of_date, sp.basis,
       round(coalesce(se.avg_daily_units, 0), 3) AS avg_daily_transfer_out_30d
FROM mart.v_stock_position_latest sp
LEFT JOIN sold so ON so.location_code = sp.location_code AND so.sku_code = sp.sku_code
LEFT JOIN sent se ON se.location_code = sp.location_code AND se.sku_code = sp.sku_code
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

-- =============================================================================
-- 2.3 views for executive dashboards and reports
-- =============================================================================

-- Bills and orders per day: the "how many / average bill" side of sales (invoice values excl. GST, BR-001).
-- Same scope as v_net_sales_daily (internal employee stock excluded); bills = distinct invoice numbers.
CREATE OR REPLACE VIEW mart.v_sales_orders_daily AS
SELECT d.calendar_date, d.fiscal_year_label, d.fiscal_month, d.month_start_date, d.week_start_date,
       c.channel_code, c.channel_name, c.sub_channel_name, c.channel_group, l.location_code, l.location_name,
       pt.partner_type, pt.is_related_party, pt.is_sale_or_return,
       count(DISTINCT s.bill_number) AS bills,
       count(DISTINCT s.order_key) FILTER (WHERE s.order_key <> -1) AS orders,
       sum(s.quantity) FILTER (WHERE p.item_type = 'TRADING') AS units_sold,
       sum(coalesce(s.net_sales_amount, 0)) AS invoiced_sales
FROM core.fact_sales_line s
JOIN core.dim_date d ON d.date_key = s.bill_date_key
JOIN core.dim_channel c ON c.channel_key = s.channel_key
JOIN core.dim_location l ON l.location_key = s.location_key
JOIN core.dim_partner pt ON pt.partner_key = s.partner_key
JOIN core.dim_product p ON p.product_key = s.product_key
WHERE NOT pt.is_internal
GROUP BY d.calendar_date, d.fiscal_year_label, d.fiscal_month, d.month_start_date, d.week_start_date, c.channel_code, c.channel_name,
         c.sub_channel_name, c.channel_group, l.location_code, l.location_name, pt.partner_type, pt.is_related_party, pt.is_sale_or_return;

-- Quick-commerce consumer sell-out (Blinkit, Instamart): demand, never revenue and never added to invoices (BR-024).
CREATE OR REPLACE VIEW mart.v_partner_sellout_daily AS
SELECT d.calendar_date, d.month_start_date, so.source_name, c.channel_name AS platform, so.city, l.location_name AS platform_location,
       p.sku_code, p.product_name, p.category, p.lifecycle_status,
       sum(so.units_sold) AS units_sold, sum(so.order_count) AS orders, sum(so.mrp_value) AS mrp_value, sum(so.selling_value) AS selling_value
FROM core.fact_partner_sellout so
JOIN core.dim_date d ON d.date_key = so.order_date_key
JOIN core.dim_channel c ON c.channel_key = so.channel_key
JOIN core.dim_location l ON l.location_key = so.location_key
JOIN core.dim_product p ON p.product_key = so.product_key
GROUP BY d.calendar_date, d.month_start_date, so.source_name, c.channel_name, so.city, l.location_name, p.sku_code, p.product_name,
         p.category, p.lifecycle_status;

-- Order fulfilment from Bagru (WMS dispatch, BR-017): one row per outbound delivery. Durations in hours / days;
-- shipped_late = shipped after the marketplace's ship-by time (or not shipped and past it at the period end).
-- 2.4 tracking scope per channel, from the data itself: the WMS only knows what the courier reports back.
--   is_delivery_tracked: at least half the channel's shipped deliveries carry a delivery date.
--   is_rto_tracked: the channel records RTO on at least 1% of its deliveries. Marketplace returns-to-origin are handled
--   by the marketplace and never reach the WMS, so their RTO shows as zero: read rates on tracked channels only.
-- courier_group: the courier company behind the WMS spelling. weight_kg: NULL above 100 kg per delivery (data entry).
CREATE OR REPLACE VIEW mart.v_fulfilment AS
WITH tracking AS (
    SELECT channel_key,
           count(*) FILTER (WHERE delivery_datetime IS NOT NULL)
               >= 0.5 * nullif(count(*) FILTER (WHERE ship_datetime IS NOT NULL), 0) AS is_delivery_tracked,
           count(*) FILTER (WHERE is_rto) >= 0.01 * count(*) AS is_rto_tracked
    FROM core.fact_shipment WHERE channel_key <> -1 GROUP BY channel_key)
SELECT f.outbound_delivery_number, f.invoice_number, d.calendar_date AS order_date, d.month_start_date, d.week_start_date,
       c.channel_code, c.channel_name, c.sub_channel_name, cr.courier_name, f.payment_type, f.shipment_status, f.is_rto, f.is_on_hold,
       f.delivery_qty, f.box_count, f.destination_pincode,
       round(extract(epoch FROM f.ship_datetime - f.order_datetime) / 3600, 1) AS order_to_ship_hours,
       round(extract(epoch FROM f.delivery_datetime - f.ship_datetime) / 86400, 1) AS ship_to_deliver_days,
       CASE WHEN f.ship_by_datetime IS NULL THEN NULL
            WHEN f.ship_datetime IS NOT NULL THEN f.ship_datetime > f.ship_by_datetime
            ELSE (SELECT period_end FROM meta.transform_run WHERE status = 'SUCCEEDED' ORDER BY transform_run_id DESC LIMIT 1) > f.ship_by_datetime::DATE
       END AS shipped_late,
       f.shipment_status = 'DELIVERED' AS is_delivered,
       cr.courier_group,
       coalesce(tr.is_delivery_tracked, FALSE) AS is_delivery_tracked,
       coalesce(tr.is_rto_tracked, FALSE) AS is_rto_tracked,
       CASE WHEN f.weight_kg <= 100 THEN f.weight_kg END AS weight_kg
FROM core.fact_shipment f
JOIN core.dim_date d ON d.date_key = f.order_date_key
JOIN core.dim_channel c ON c.channel_key = f.channel_key
JOIN core.dim_courier cr ON cr.courier_key = f.courier_key
LEFT JOIN tracking tr ON tr.channel_key = f.channel_key;

-- Stock on every saved snapshot day, each location from its own system of record (BR-025). History exists only from
-- the first saved day (BR-021, G-001): one row per day x location x SKU that was reported.
CREATE OR REPLACE VIEW mart.v_stock_position_daily AS
SELECT d.calendar_date AS snapshot_date, d.month_start_date, l.location_code, l.location_name, l.location_type, l.is_sellable_stock,
       p.sku_code, p.product_name, p.item_type, p.lifecycle_status, p.category, p.current_mrp,
       sum(s.on_hand_qty) AS on_hand_qty, sum(coalesce(s.sellable_qty, s.on_hand_qty)) AS sellable_qty, s.source_name
FROM core.fact_inventory_snapshot s
JOIN core.dim_location l ON l.location_key = s.location_key
JOIN core.dim_product p ON p.product_key = s.product_key
JOIN core.dim_date d ON d.date_key = s.snapshot_date_key
WHERE NOT l.is_unknown_member AND l.inventory_system_of_record = CASE s.source_name WHEN 'ERP_INVENTORY_SNAPSHOT' THEN 'ERP'
          WHEN 'BLINKIT_INVENTORY' THEN 'BLINKIT' WHEN 'INSTAMART_INVENTORY' THEN 'INSTAMART' END
GROUP BY d.calendar_date, d.month_start_date, l.location_code, l.location_name, l.location_type, l.is_sellable_stock, p.sku_code,
         p.product_name, p.item_type, p.lifecycle_status, p.category, p.current_mrp, s.source_name;

-- Returns with the sale they reverse (where the original invoice is loaded): how long after the sale goods come back.
CREATE OR REPLACE VIEW mart.v_return_to_sale AS
SELECT r.source_name, r.return_number, d.calendar_date AS return_date, d.month_start_date, c.channel_name, c.sub_channel_name,
       p.sku_code, p.product_name, p.category, r.quantity AS units_returned, coalesce(r.net_return_amount, 0) AS returns_value,
       sd.calendar_date AS sale_date, d.calendar_date - sd.calendar_date AS days_from_sale
FROM core.fact_return_line r
JOIN core.dim_date d ON d.date_key = r.return_date_key
JOIN core.dim_channel c ON c.channel_key = r.channel_key
JOIN core.dim_product p ON p.product_key = r.product_key
JOIN core.dim_partner pt ON pt.partner_key = r.partner_key
LEFT JOIN core.fact_sales_line s ON s.sales_line_id = r.original_sales_line_id
LEFT JOIN core.dim_date sd ON sd.date_key = s.bill_date_key
WHERE NOT pt.is_internal;

-- 2.4 Every PO line of the latest export per PO (open, received, over-received), with the flags the
-- Purchasing dashboard needs: over-received (pending below zero), no due date, as-of date assumed (D-094).
CREATE OR REPLACE VIEW mart.v_purchase_order_lines AS
SELECT po.po_number, d.calendar_date AS po_date, dd.calendar_date AS due_date, po.as_of_date, b.as_of_is_assumed,
       pt.partner_name AS supplier, pt.partner_type AS supplier_type, p.sku_code, p.product_name, p.lifecycle_status,
       po.order_qty, po.received_qty, po.pending_qty, po.purchase_price, po.po_status, po.document_type,
       (po.po_status IN ('OPEN','IN_PROGRESS','OVERDUE') AND coalesce(po.pending_qty, 0) > 0) AS is_open,
       (coalesce(po.pending_qty, 0) < 0) AS is_over_received,
       CASE WHEN po.pending_qty < 0 THEN -po.pending_qty END AS over_received_qty,
       (dd.calendar_date IS NOT NULL) AS has_due_date
FROM core.fact_purchase_order_line po
JOIN meta.load_batch b ON b.batch_id = po.batch_id
JOIN core.dim_date d ON d.date_key = po.po_date_key
LEFT JOIN core.dim_date dd ON dd.date_key = po.due_date_key
JOIN core.dim_partner pt ON pt.partner_key = po.partner_key
JOIN core.dim_product p ON p.product_key = po.product_key;
