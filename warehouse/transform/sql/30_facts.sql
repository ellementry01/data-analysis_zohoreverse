-- =============================================================================
-- 30  Core facts, rebuilt each run from staging. Business rules are applied here.
-- Unmatched values map to the Unknown member (-1), never dropped (BR-027).
-- The prototype period (meta.pipeline_setting) is applied here (BR-020).
-- =============================================================================

DELETE FROM core.fact_stock_movement;
DELETE FROM core.bridge_return_goods_receipt;
DELETE FROM core.bridge_shipment_sku;
DELETE FROM core.fact_shipment;
DELETE FROM core.fact_return_line;
DELETE FROM core.bridge_goods_receipt_grn;
DELETE FROM core.fact_goods_receipt_line;
DELETE FROM core.fact_purchase_order_line;
DELETE FROM core.fact_sales_line;
DELETE FROM core.fact_stock_transfer_line;
DELETE FROM core.fact_partner_sellout;
DELETE FROM core.fact_inventory_snapshot;

-- lookups: every mapping resolved to a dimension key once
CREATE TEMP TABLE lk_loc ON COMMIT DROP AS
SELECT a.source_name, a.source_field, a.source_value, d.location_key
FROM ref.location_alias a JOIN core.dim_location d ON d.location_code = a.location_code;
CREATE TEMP TABLE lk_chan ON COMMIT DROP AS
SELECT a.source_name, a.source_field, a.source_value, d.channel_key
FROM ref.channel_alias a JOIN core.dim_channel d ON d.channel_code = a.channel_code;
CREATE TEMP TABLE lk_prefix ON COMMIT DROP AS
SELECT a.source_name, a.doc_prefix, d.location_key
FROM ref.document_prefix_location a JOIN core.dim_location d ON d.location_code = a.location_code;

-- --------------------------------------------------------------------- sales lines
INSERT INTO core.fact_sales_line (source_name, bill_number, source_sku_code, line_occurrence, bill_date_key, bill_datetime,
    order_key, product_key, location_key, channel_key, partner_key, payment_mode_raw, ship_to_pincode, ship_to_city,
    ship_to_state_code, quantity, unit_rate, unit_mrp, gross_amount, discount_amount, net_sales_amount, net_amount_method,
    tax_amount, line_total_amount, unit_cost, batch_id, source_row_number)
SELECT 'ERP_RETAIL_SALES', s.bill_number, s.source_sku_code, s.line_occurrence, stg.date_key(s.bill_date), s.bill_datetime,
       coalesce(o.order_key, -1), coalesce(p.product_key, -1), coalesce(l.location_key, -1), coalesce(c.channel_key, -1),
       coalesce(pt.partner_key, -1), s.payment_mode_raw, s.ship_to_pincode, s.ship_to_city, s.ship_to_state_code,
       s.quantity, s.unit_rate, s.unit_mrp, s.gross_amount, s.discount_amount, n.net, n.method,
       s.tax_amount, s.assessable_value, s.unit_cost, s.batch_id, s.source_row_number
FROM stg.retail_sales s
CROSS JOIN LATERAL (SELECT CASE WHEN s.doc_value >= 0 THEN s.doc_value                                   -- BR-002
                                WHEN s.doc_value IS NULL AND s.assessable_value - s.tax_amount >= 0 THEN s.assessable_value - s.tax_amount END AS net,
                           CASE WHEN s.doc_value >= 0 THEN 'SOURCE'
                                WHEN s.doc_value IS NULL AND s.assessable_value - s.tax_amount >= 0 THEN 'DERIVED' ELSE 'MISSING' END AS method) n
LEFT JOIN core.dim_product p ON p.sku_code = s.sku_code
LEFT JOIN lk_loc l ON l.source_name = 'ERP_RETAIL_SALES' AND l.source_field = 'CHANNELNAME' AND l.source_value = s.location_value
LEFT JOIN lk_chan c ON c.source_name = 'ERP_RETAIL_SALES' AND c.source_field = 'CONTACTNAME' AND c.source_value = s.contact_name   -- BR-006
LEFT JOIN core.dim_partner pt ON pt.partner_name = s.contact_name AND pt.partner_role = 'CUSTOMER'
LEFT JOIN core.dim_order o ON o.channel_key = coalesce(c.channel_key, -1) AND o.external_order_number = s.order_number
WHERE s.bill_date BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx) AND s.quantity > 0;

INSERT INTO core.fact_sales_line (source_name, bill_number, source_sku_code, line_occurrence, bill_date_key, bill_datetime,
    order_key, product_key, location_key, channel_key, partner_key, ship_to_pincode, ship_to_city,
    quantity, unit_rate, unit_mrp, gross_amount, discount_amount, net_sales_amount, net_amount_method,
    tax_amount, line_total_amount, batch_id, source_row_number)
SELECT 'ERP_DOMESTIC_SALES', s.bill_number, s.source_sku_code, s.line_occurrence, stg.date_key(s.bill_date), s.bill_datetime,
       -1, coalesce(p.product_key, -1), coalesce(l.location_key, -1), coalesce(pt.default_channel_key, -1), coalesce(pt.partner_key, -1),
       s.ship_to_pincode, s.ship_to_city, s.quantity, s.unit_rate, s.unit_mrp, s.gross_amount, s.discount_amount, n.net, n.method,
       s.tax_amount, s.net_amount, s.batch_id, s.source_row_number
FROM stg.domestic_sales s
CROSS JOIN LATERAL (SELECT CASE WHEN s.taxable >= 0 THEN s.taxable                                         -- BR-003
                                WHEN s.taxable IS NULL AND s.net_amount - s.tax_amount >= 0 THEN s.net_amount - s.tax_amount END AS net,
                           CASE WHEN s.taxable >= 0 THEN 'SOURCE'
                                WHEN s.taxable IS NULL AND s.net_amount - s.tax_amount >= 0 THEN 'DERIVED' ELSE 'MISSING' END AS method) n
LEFT JOIN core.dim_product p ON p.sku_code = s.sku_code
LEFT JOIN lk_loc l ON l.source_name = 'ERP_DOMESTIC_SALES' AND l.source_field = 'CHANNELNAME' AND l.source_value = s.location_value
LEFT JOIN core.dim_partner pt ON pt.partner_name = s.contact_name AND pt.partner_role = 'CUSTOMER'          -- channel via partner (BR-010)
WHERE s.bill_date BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx) AND s.quantity > 0;

-- --------------------------------------------------------------------- returns
INSERT INTO core.fact_return_line (source_name, return_number, source_sku_code, line_occurrence, return_date_key,
    first_receipt_date_key, last_receipt_date_key, original_bill_number, order_key, product_key, receiving_location_key,
    channel_key, partner_key, return_reason_key, quantity, unit_rate, discount_amount, net_return_amount, net_amount_method,
    tax_amount, batch_id, source_row_number)
SELECT 'ERP_RETAIL_RETURN', s.return_number, s.source_sku_code, s.line_occurrence, stg.date_key(s.return_date),
       stg.date_key(s.return_date), stg.date_key(s.return_date), s.original_bill_number,
       coalesce(o.order_key, -1), coalesce(p.product_key, -1), coalesce(l.location_key, -1), coalesce(c.channel_key, -1),
       coalesce(pt.partner_key, -1), -1, s.quantity, s.unit_rate, s.discount_amount, n.net, n.method, s.tax_amount,
       s.batch_id, s.source_row_number
FROM stg.retail_return s
CROSS JOIN LATERAL (SELECT CASE WHEN s.doc_value >= 0 THEN s.doc_value
                                WHEN s.doc_value IS NULL AND s.assessable_value - s.tax_amount >= 0 THEN s.assessable_value - s.tax_amount END AS net,
                           CASE WHEN s.doc_value >= 0 THEN 'SOURCE'
                                WHEN s.doc_value IS NULL AND s.assessable_value - s.tax_amount >= 0 THEN 'DERIVED' ELSE 'MISSING' END AS method) n
LEFT JOIN core.dim_product p ON p.sku_code = s.sku_code
LEFT JOIN lk_loc l ON l.source_name = 'ERP_RETAIL_RETURN' AND l.source_field = 'CONTACTNAME' AND l.source_value = s.contact_name   -- BR-009
LEFT JOIN lk_chan c ON c.source_name = 'ERP_RETAIL_RETURN' AND c.source_field = 'CONTACTNAME' AND c.source_value = s.contact_name
LEFT JOIN core.dim_partner pt ON pt.partner_name = s.contact_name AND pt.partner_role = 'CUSTOMER'
LEFT JOIN core.dim_order o ON o.channel_key = coalesce(c.channel_key, -1) AND o.external_order_number = s.order_number
WHERE s.return_date BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx) AND s.quantity > 0;

INSERT INTO core.fact_return_line (source_name, return_number, source_sku_code, line_occurrence, return_date_key,
    first_receipt_date_key, last_receipt_date_key, original_bill_number, order_key, product_key, receiving_location_key,
    channel_key, partner_key, return_reason_key, quantity, unit_rate, discount_amount, net_return_amount, net_amount_method,
    tax_amount, batch_id, source_row_number)
SELECT 'ERP_DOMESTIC_RETURN', s.return_number, s.source_sku_code, s.line_occurrence, stg.date_key(s.return_date),   -- credit-note date (BR-023)
       stg.date_key(rc.first_d), stg.date_key(rc.last_d), s.original_bill_number,
       -1, coalesce(p.product_key, -1), coalesce(l.location_key, -1), coalesce(pt.default_channel_key, -1),
       coalesce(pt.partner_key, -1), -1, s.quantity, s.unit_rate, s.discount_amount, n.net, n.method, s.tax_amount,
       s.batch_id, s.source_row_number
FROM stg.domestic_return s
CROSS JOIN LATERAL (SELECT CASE WHEN s.doc_value >= 0 THEN s.doc_value
                                WHEN s.doc_value IS NULL AND s.assessable_value - s.tax_amount >= 0 THEN s.assessable_value - s.tax_amount END AS net,
                           CASE WHEN s.doc_value >= 0 THEN 'SOURCE'
                                WHEN s.doc_value IS NULL AND s.assessable_value - s.tax_amount >= 0 THEN 'DERIVED' ELSE 'MISSING' END AS method) n
LEFT JOIN (SELECT batch_id, source_row_number, min(goods_receipt_date) first_d, max(goods_receipt_date) last_d
           FROM stg.domestic_return_receipt GROUP BY 1, 2) rc ON rc.batch_id = s.batch_id AND rc.source_row_number = s.source_row_number
LEFT JOIN core.dim_product p ON p.sku_code = s.sku_code
LEFT JOIN lk_loc l ON l.source_name = 'ERP_DOMESTIC_RETURN' AND l.source_field = 'CHANNELNAME' AND l.source_value = s.location_value
LEFT JOIN core.dim_partner pt ON pt.partner_name = s.contact_name AND pt.partner_role = 'CUSTOMER'
WHERE s.return_date BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx) AND s.quantity > 0;

INSERT INTO core.bridge_return_goods_receipt (return_line_id, receipt_seq, goods_receipt_number, goods_receipt_date)
SELECT f.return_line_id, r.receipt_seq, r.goods_receipt_number, r.goods_receipt_date
FROM stg.domestic_return_receipt r
JOIN core.fact_return_line f ON f.source_name = 'ERP_DOMESTIC_RETURN' AND f.batch_id = r.batch_id AND f.source_row_number = r.source_row_number
WHERE r.goods_receipt_date IS NOT NULL;

-- link each return to the invoice line it reverses (same bill, same product)
UPDATE core.fact_return_line r SET original_sales_line_id = s.sales_line_id
FROM (SELECT DISTINCT ON (bill_number, product_key) bill_number, product_key, sales_line_id
      FROM core.fact_sales_line WHERE product_key <> -1 ORDER BY bill_number, product_key, line_occurrence) s
WHERE s.bill_number = r.original_bill_number AND s.product_key = r.product_key;

-- --------------------------------------------------------------------- stock transfers
-- OUT: sender from the document prefix (until the ERP export carries a location), receiver from CONTACTNAME
INSERT INTO core.fact_stock_transfer_line (source_name, document_number, source_sku_code, line_occurrence, movement_direction,
    document_date_key, from_location_key, to_location_key, product_key, quantity, unit_rate, transfer_value, document_status,
    batch_id, source_row_number)
SELECT 'ERP_STOCK_TRANSFER_OUT', s.document_number, s.source_sku_code, s.line_occurrence, 'OUT', stg.date_key(s.document_date),
       coalesce(f.location_key, -1), coalesce(t.location_key, -1), coalesce(p.product_key, -1), s.quantity, s.unit_rate,
       s.transfer_value, s.document_status, s.batch_id, s.source_row_number
FROM stg.transfer_out s
LEFT JOIN lk_prefix f ON f.source_name = 'ERP_STOCK_TRANSFER_OUT' AND f.doc_prefix = s.doc_prefix
LEFT JOIN lk_loc t ON t.source_name = 'ERP_STOCK_TRANSFER_OUT' AND t.source_field = 'CONTACTNAME' AND t.source_value = s.contact_name
LEFT JOIN core.dim_product p ON p.sku_code = s.sku_code
WHERE s.document_date BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx) AND s.quantity > 0
  AND NOT (coalesce(f.location_key, -1) = coalesce(t.location_key, -1) AND coalesce(f.location_key, -1) <> -1);

-- IN: sender from CONTACTNAME, receiver = receiver of the linked outward document (the inward prefix is ambiguous)
INSERT INTO core.fact_stock_transfer_line (source_name, document_number, source_sku_code, line_occurrence, movement_direction,
    document_date_key, linked_outward_document, from_location_key, to_location_key, product_key, quantity, unit_rate,
    transfer_value, document_status, batch_id, source_row_number)
SELECT 'ERP_STOCK_TRANSFER_IN', s.document_number, s.source_sku_code, s.line_occurrence, 'IN', stg.date_key(s.document_date),
       s.linked_outward_document, coalesce(f.location_key, -1), coalesce(od.to_key, -1), coalesce(p.product_key, -1),
       s.quantity, s.unit_rate, s.transfer_value, s.document_status, s.batch_id, s.source_row_number
FROM stg.transfer_in s
LEFT JOIN lk_loc f ON f.source_name = 'ERP_STOCK_TRANSFER_IN' AND f.source_field = 'CONTACTNAME' AND f.source_value = s.contact_name
LEFT JOIN (SELECT o.document_number, min(t.location_key) to_key FROM stg.transfer_out o
           JOIN lk_loc t ON t.source_name = 'ERP_STOCK_TRANSFER_OUT' AND t.source_field = 'CONTACTNAME' AND t.source_value = o.contact_name
           GROUP BY o.document_number) od ON od.document_number = s.linked_outward_document
LEFT JOIN core.dim_product p ON p.sku_code = s.sku_code
WHERE s.document_date BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx) AND s.quantity > 0
  AND NOT (coalesce(f.location_key, -1) = coalesce(od.to_key, -1) AND coalesce(f.location_key, -1) <> -1);

-- --------------------------------------------------------------------- purchase orders and goods receipts
INSERT INTO core.fact_purchase_order_line (po_number, source_sku_code, line_occurrence, po_date_key, due_date_key, partner_key,
    product_key, order_qty, received_qty, returned_to_supplier_qty, pending_qty, purchase_price, purchase_amount, po_status,
    po_status_raw, as_of_date, document_type, batch_id, source_row_number)
SELECT s.po_number, s.source_sku_code, s.line_occurrence, stg.date_key(s.po_date), stg.date_key(s.due_date),
       coalesce(pt.partner_key, -1), coalesce(p.product_key, -1), s.order_qty, s.received_qty, s.returned_qty, s.pending_qty,
       s.purchase_price, s.purchase_amount, coalesce(st.standard_value, 'UNMAPPED'), coalesce(s.po_status_raw, ''), s.as_of_date,
       s.document_type, s.batch_id, s.source_row_number
FROM stg.purchase_order s
LEFT JOIN core.dim_partner pt ON pt.partner_name = s.contact_name AND pt.partner_role = 'SUPPLIER'
LEFT JOIN core.dim_product p ON p.sku_code = s.sku_code
LEFT JOIN ref.code_mapping st ON st.domain = 'PO_STATUS' AND st.source_name = 'ERP_PURCHASE_ORDER' AND st.source_value = s.po_status_raw
WHERE s.po_date BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx) AND s.order_qty > 0;

-- One receipt row per PO line as the report states it: quantity received to date and the ONE date given.
-- A part-delivered line lists several receipt numbers in one cell; they go to the bridge, without split quantities.
INSERT INTO core.fact_goods_receipt_line (po_line_id, po_number, source_sku_code, line_occurrence, grn_date_key, receipt_count,
    partner_key, product_key, receiving_location_key, received_qty, batch_id, source_row_number)
SELECT po.po_line_id, s.po_number, s.source_sku_code, s.line_occurrence, stg.date_key(s.grn_date),
       greatest(cardinality(array_remove(string_to_array(s.grn_number, ';'), '')), 1),
       po.partner_key, po.product_key,
       -1,                                            -- receiving location not in the export yet (gap G-025)
       s.received_qty, s.batch_id, s.source_row_number
FROM stg.purchase_order s
JOIN core.fact_purchase_order_line po ON po.po_number = s.po_number AND po.source_sku_code = s.source_sku_code
                                     AND po.line_occurrence = s.line_occurrence
WHERE s.grn_number IS NOT NULL AND s.received_qty > 0
  AND s.grn_date BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx);

INSERT INTO core.bridge_goods_receipt_grn (receipt_line_id, grn_seq, grn_number)
SELECT g.receipt_line_id, u.seq, btrim(u.grn)
FROM core.fact_goods_receipt_line g
JOIN stg.purchase_order s ON s.batch_id = g.batch_id AND s.source_row_number = g.source_row_number
CROSS JOIN LATERAL unnest(string_to_array(s.grn_number, ';')) WITH ORDINALITY AS u(grn, seq)
WHERE btrim(u.grn) <> '';

-- --------------------------------------------------------------------- platform sell-out (demand, not revenue: BR-024)
INSERT INTO core.fact_partner_sellout (source_name, order_date_key, platform_store_code, source_sku_code, channel_key, partner_key,
    location_key, product_key, city, units_sold, order_count, mrp_value, selling_value, batch_id)
SELECT 'BLINKIT_SALES', stg.date_key(s.order_date), coalesce(s.supply_city, 'UNKNOWN'), coalesce(s.source_sku_code, '#NO_SKU'),
       coalesce((SELECT channel_key FROM lk_chan WHERE source_name = 'BLINKIT_SALES' AND source_value = '*'), -1),
       coalesce((SELECT dp.partner_key FROM ref.code_mapping m JOIN core.dim_partner dp ON dp.partner_name = m.standard_value AND dp.partner_role = 'CUSTOMER'
                 WHERE m.domain = 'PLATFORM_PARTNER' AND m.source_name = 'BLINKIT_SALES'), -1),
       -1,                                            -- which Blinkit location the units left is not in the export
       coalesce(p.product_key, -1), coalesce(s.supply_city, 'UNKNOWN'),
       sum(s.quantity), count(DISTINCT s.order_id), sum(s.quantity * s.unit_mrp), sum(s.selling_value), max(s.batch_id)
FROM stg.blinkit_sales s LEFT JOIN core.dim_product p ON p.sku_code = s.sku_code
WHERE s.order_status = 'DELIVERED'                                                                         -- BR-018
  AND s.order_date BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx)
GROUP BY s.order_date, s.supply_city, coalesce(s.source_sku_code, '#NO_SKU'), p.product_key;   -- no SKU: kept, Unknown product (BR-027)

INSERT INTO core.fact_partner_sellout (source_name, order_date_key, platform_store_code, source_sku_code, channel_key, partner_key,
    location_key, product_key, city, units_sold, combo_units_sold, mrp_value, gmv_reported, batch_id)
SELECT 'INSTAMART_SALES', stg.date_key(s.order_date), s.store_id, coalesce(s.source_sku_code, '#NO_SKU'),
       coalesce((SELECT channel_key FROM lk_chan WHERE source_name = 'INSTAMART_SALES' AND source_value = '*'), -1),
       -1, -1, coalesce(p.product_key, -1), coalesce(max(s.city), 'UNKNOWN'),
       sum(s.units_sold), sum(s.combo_units_sold), sum(s.units_sold * s.unit_mrp), sum(s.gmv), max(s.batch_id)
FROM stg.instamart_sales s LEFT JOIN core.dim_product p ON p.sku_code = s.sku_code
WHERE s.order_date BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx) AND s.store_id IS NOT NULL
GROUP BY s.order_date, s.store_id, coalesce(s.source_sku_code, '#NO_SKU'), p.product_key;

-- --------------------------------------------------------------------- stock snapshots (non-zero rows only)
INSERT INTO core.fact_inventory_snapshot (source_name, snapshot_date_key, source_location_value, source_sku_code, location_key,
    product_key, on_hand_qty, sellable_qty, unsellable_qty, in_transit_qty, incoming_qty, damaged_qty, lost_qty, expired_qty,
    recalled_qty, platform_net_scheduled_qty, unit_mrp, batch_id)
SELECT s.source_name, stg.date_key(s.snapshot_date), s.location_value, s.source_sku_code, coalesce(l.location_key, -1),
       coalesce(p.product_key, -1), s.on_hand_qty, s.sellable_qty, s.unsellable_qty, s.in_transit_qty, s.incoming_qty,
       s.damaged_qty, s.lost_qty, s.expired_qty, s.recalled_qty, s.net_scheduled_qty,
       CASE WHEN s.unit_mrp >= 0 THEN s.unit_mrp END, s.batch_id
FROM stg.inventory_snapshot s
LEFT JOIN lk_loc l ON l.source_name = s.source_name AND l.source_value = s.location_value
                  AND l.source_field = CASE s.source_name WHEN 'ERP_INVENTORY_SNAPSHOT' THEN 'location column header'
                                                          WHEN 'BLINKIT_INVENTORY' THEN 'Warehouse Facility Name' ELSE 'FacilityName' END
LEFT JOIN core.dim_product p ON p.sku_code = s.sku_code
WHERE s.snapshot_date BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx)
  AND s.on_hand_qty IS NOT NULL
  AND (s.on_hand_qty <> 0 OR coalesce(s.in_transit_qty, 0) <> 0 OR coalesce(s.incoming_qty, 0) <> 0);

-- --------------------------------------------------------------------- shipments (WMS dispatch, BR-017)
-- One row per outbound delivery. Channel from Site Location (ref.channel_alias), falling back to the channel of the
-- invoice it ships; order from that invoice. Status and payment type standardised through ref.code_mapping.
-- Everything ships from Bagru (Order Serving Location 'Warehouse' -> BAGRU_WH). Nothing unknown is guessed: -1.
-- 2.5: the WMS Invoice No is the marketplace's own invoice for most marketplace orders (M26-, M44-...), not the ERP
-- bill. A shipment is linked to its ERP bill(s) by, in order: Invoice No = bill number; Extern Order No = the order
-- number on the bill (retail ORDER_NUMBER / DOCREFNUM, domestic DOCREFNUM); Tracking No = the bill's AWB.
CREATE TEMP TABLE lk_invoice ON COMMIT DROP AS
SELECT bill_number, min(order_key) FILTER (WHERE order_key <> -1) AS order_key, min(channel_key) AS channel_key
FROM core.fact_sales_line GROUP BY bill_number;

CREATE TEMP TABLE lk_bill_ref ON COMMIT DROP AS          -- reference (order number or AWB) -> loaded bill
SELECT DISTINCT 'ORDER' AS ref_type, x.ref, x.bill_number FROM (
    SELECT order_number AS ref, bill_number FROM stg.retail_sales
    UNION ALL SELECT order_reference, bill_number FROM stg.domestic_sales) x
JOIN lk_invoice i USING (bill_number) WHERE x.ref IS NOT NULL
UNION
SELECT DISTINCT 'AWB', x.ref, x.bill_number FROM (
    SELECT awb AS ref, bill_number FROM stg.retail_sales UNION ALL SELECT awb, bill_number FROM stg.domestic_sales) x
JOIN lk_invoice i USING (bill_number) WHERE x.ref IS NOT NULL;
CREATE INDEX ON lk_bill_ref (ref_type, ref);

CREATE TEMP TABLE lk_shipment_bill ON COMMIT DROP AS      -- every ERP bill of each dispatch row, by the first key that links
WITH s AS (SELECT batch_id, source_row_number, invoice_number, external_order_number, tracking_number FROM stg.wms_dispatch),
by_inv AS (SELECT s.batch_id, s.source_row_number, s.invoice_number AS bill_number, 'INVOICE' AS method
           FROM s JOIN lk_invoice i ON i.bill_number = s.invoice_number),
by_ord AS (SELECT s.batch_id, s.source_row_number, r.bill_number, 'ORDER' AS method
           FROM s JOIN lk_bill_ref r ON r.ref_type = 'ORDER' AND r.ref = s.external_order_number
           WHERE NOT EXISTS (SELECT 1 FROM by_inv b WHERE b.batch_id = s.batch_id AND b.source_row_number = s.source_row_number)),
by_awb AS (SELECT s.batch_id, s.source_row_number, r.bill_number, 'AWB' AS method
           FROM s JOIN lk_bill_ref r ON r.ref_type = 'AWB' AND r.ref = s.tracking_number
           WHERE NOT EXISTS (SELECT 1 FROM by_inv b WHERE b.batch_id = s.batch_id AND b.source_row_number = s.source_row_number)
             AND NOT EXISTS (SELECT 1 FROM by_ord o WHERE o.batch_id = s.batch_id AND o.source_row_number = s.source_row_number))
SELECT * FROM by_inv UNION ALL SELECT * FROM by_ord UNION ALL SELECT * FROM by_awb;
CREATE INDEX ON lk_shipment_bill (batch_id, source_row_number);

CREATE TEMP TABLE lk_shipment_link ON COMMIT DROP AS      -- one row per dispatch row: first bill, its order and channel
SELECT DISTINCT ON (b.batch_id, b.source_row_number) b.batch_id, b.source_row_number, b.bill_number, b.method,
       i.order_key, i.channel_key
FROM lk_shipment_bill b JOIN lk_invoice i USING (bill_number)
ORDER BY b.batch_id, b.source_row_number, i.order_key IS NULL, b.bill_number;

INSERT INTO core.fact_shipment (outbound_delivery_number, order_key, invoice_number, channel_key, fulfilment_location_key, courier_key,
    payment_type, tracking_number, shipment_status, shipment_status_raw, transporter_status, transporter_remarks, is_rto, is_on_hold,
    order_datetime, pick_datetime, pack_datetime, ship_datetime, delivery_datetime, ship_by_datetime, order_date_key, ship_date_key,
    delivery_date_key, delivery_qty, box_count, weight_kg, destination_pincode, batch_id, source_row_number,
    sales_bill_number, sales_link_method)
SELECT s.outbound_delivery_number, coalesce(inv.order_key, -1), s.invoice_number,
       coalesce(ch.channel_key, inv.channel_key, -1), coalesce(l.location_key, -1), coalesce(cr.courier_key, -1),
       CASE pay.standard_value WHEN 'PREPAID' THEN 'PREPAID' WHEN 'COD' THEN 'COD' ELSE 'OTHER' END,
       left(s.tracking_number, 60), coalesce(st.standard_value, 'UNMAPPED'), left(coalesce(s.status_raw, ''), 60),
       left(s.transporter_status, 60), s.transporter_remarks,
       coalesce(st.standard_value IN ('RTO_DELIVERED','RTO_INITIATED'), FALSE), coalesce(s.is_on_hold, FALSE),
       s.order_datetime, s.pick_datetime, s.pack_datetime, s.ship_datetime, s.delivery_datetime, s.ship_by_datetime,
       stg.date_key(s.order_date), stg.date_key(s.ship_datetime::DATE), stg.date_key(s.delivery_datetime::DATE),
       CASE WHEN s.delivery_qty >= 0 THEN s.delivery_qty END, CASE WHEN s.box_count >= 0 THEN s.box_count END,
       CASE WHEN s.weight_kg >= 0 THEN s.weight_kg END, left(s.destination_pincode, 10), s.batch_id, s.source_row_number,
       inv.bill_number, coalesce(inv.method, 'NONE')
FROM stg.wms_dispatch s
LEFT JOIN lk_chan ch ON ch.source_name = 'WMS_DISPATCH' AND ch.source_field = 'Site Location' AND ch.source_value = s.site_location
LEFT JOIN lk_shipment_link inv ON inv.batch_id = s.batch_id AND inv.source_row_number = s.source_row_number
LEFT JOIN lk_loc l ON l.source_name = 'WMS_DISPATCH' AND l.source_field = 'Order Serving Location' AND l.source_value = s.serving_location
LEFT JOIN core.dim_courier cr ON cr.courier_name = s.courier_name
LEFT JOIN ref.code_mapping st ON st.domain = 'SHIPMENT_STATUS' AND st.source_name = 'WMS_DISPATCH' AND st.source_value = s.status_raw
LEFT JOIN ref.code_mapping pay ON pay.domain = 'PAYMENT_TYPE' AND pay.source_name = 'WMS_DISPATCH' AND pay.source_value = s.order_type_raw
WHERE s.order_date BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx);

-- SKUs per shipment. A cell can list several SKUs with ONE combined quantity: a single-SKU row keeps the row quantity;
-- for several SKUs the quantity comes from the invoice line of that SKU when exactly one exists across the
-- shipment's linked bills (2.5: by invoice, order number or AWB); otherwise UNALLOCATED.
INSERT INTO core.bridge_shipment_sku (shipment_id, source_sku_code, product_key, quantity, quantity_source)
WITH skus AS (
    SELECT f.shipment_id, f.batch_id, f.source_row_number, f.delivery_qty, btrim(u.sku) AS source_sku_code,
           count(*) OVER (PARTITION BY f.shipment_id) AS n_skus
    FROM core.fact_shipment f
    JOIN stg.wms_dispatch s ON s.batch_id = f.batch_id AND s.source_row_number = f.source_row_number
    CROSS JOIN LATERAL (SELECT DISTINCT btrim(x) AS sku FROM unnest(string_to_array(s.sku_cell, ',')) x WHERE btrim(x) <> '') u),
inv AS (
    SELECT b.batch_id, b.source_row_number, stg.sku(l.source_sku_code) AS sku, sum(l.quantity) AS qty, count(*) AS n
    FROM lk_shipment_bill b JOIN core.fact_sales_line l ON l.bill_number = b.bill_number
    GROUP BY b.batch_id, b.source_row_number, stg.sku(l.source_sku_code))
SELECT k.shipment_id, k.source_sku_code, coalesce(p.product_key, -1),
       CASE WHEN k.n_skus = 1 AND k.delivery_qty > 0 THEN k.delivery_qty WHEN k.n_skus > 1 AND i.n = 1 AND i.qty > 0 THEN i.qty END,
       CASE WHEN k.n_skus = 1 AND k.delivery_qty > 0 THEN 'SINGLE_SKU_ROW' WHEN k.n_skus > 1 AND i.n = 1 AND i.qty > 0 THEN 'INVOICE_LINE'
            ELSE 'UNALLOCATED' END
FROM skus k
LEFT JOIN core.dim_product p ON p.sku_code = stg.sku(k.source_sku_code)
LEFT JOIN inv i ON i.batch_id = k.batch_id AND i.source_row_number = k.source_row_number AND i.sku = stg.sku(k.source_sku_code);
