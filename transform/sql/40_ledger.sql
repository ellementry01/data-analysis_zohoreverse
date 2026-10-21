-- =============================================================================
-- 40  Stock ledger (core.fact_stock_movement): every stock movement, signed, at
-- the location where it happens. Built from the core facts.
-- Not stock: charge and service lines. Not placed: rows whose product or
-- location is unknown (counted by DQ checks, never guessed).
-- =============================================================================

CREATE TEMP TABLE mt ON COMMIT DROP AS SELECT movement_code, movement_type_key FROM core.dim_movement_type;
CREATE TEMP TABLE stock_product ON COMMIT DROP AS
SELECT product_key FROM core.dim_product WHERE NOT is_unknown_member AND item_type NOT IN ('CHARGE','SERVICE');
CREATE TEMP TABLE lk_consign ON COMMIT DROP AS          -- sale-or-return partner -> its consignment location (BR-022)
SELECT dp.partner_key, dl.location_key
FROM ref.partner_list pl
JOIN core.dim_partner dp ON dp.partner_name = pl.partner_name AND dp.partner_role = pl.partner_role
JOIN core.dim_location dl ON dl.location_code = pl.consignment_location_code;
CREATE TEMP TABLE emp_loc ON COMMIT DROP AS             -- stock with employees (BR-029)
SELECT dl.location_key FROM core.dim_location dl
WHERE dl.location_code = (SELECT setting_value FROM meta.pipeline_setting WHERE setting_key = 'employee_holding_location');

-- classify each sales line once
CREATE TEMP TABLE sales_mv ON COMMIT DROP AS
SELECT s.sales_line_id, s.bill_date_key d, s.location_key, s.product_key, s.quantity q, s.partner_key,
       CASE WHEN pt.is_internal THEN 'EMPLOYEE' WHEN pt.is_sale_or_return THEN 'CONSIGNMENT'
            WHEN pt.partner_type = 'UNCLASSIFIED' OR s.partner_key = -1 THEN 'UNCLASSIFIED' ELSE 'SALE' END AS kind,
       cs.location_key AS consign_loc
FROM core.fact_sales_line s
JOIN stock_product sp ON sp.product_key = s.product_key
JOIN core.dim_partner pt ON pt.partner_key = s.partner_key
LEFT JOIN lk_consign cs ON cs.partner_key = s.partner_key
WHERE s.location_key <> -1;

INSERT INTO core.fact_stock_movement (movement_date_key, location_key, product_key, movement_type_key, quantity,
    counterparty_location_key, partner_key, source_table, source_line_id)
SELECT d, location_key, product_key, (SELECT movement_type_key FROM mt WHERE movement_code = 'SALE'), -q, NULL::SMALLINT, partner_key, 'fact_sales_line', sales_line_id
FROM sales_mv WHERE kind = 'SALE'
UNION ALL
SELECT d, location_key, product_key, (SELECT movement_type_key FROM mt WHERE movement_code = 'ISSUE_UNCLASSIFIED'), -q, NULL::SMALLINT, partner_key, 'fact_sales_line', sales_line_id
FROM sales_mv WHERE kind = 'UNCLASSIFIED'
UNION ALL   -- consignment: out at the selling location, in at the partner's location (BR-022)
SELECT d, location_key, product_key, (SELECT movement_type_key FROM mt WHERE movement_code = 'CONSIGNMENT_OUT'), -q, consign_loc, partner_key, 'fact_sales_line', sales_line_id
FROM sales_mv WHERE kind = 'CONSIGNMENT' AND consign_loc IS NOT NULL
UNION ALL
SELECT d, consign_loc, product_key, (SELECT movement_type_key FROM mt WHERE movement_code = 'CONSIGNMENT_IN'), q, location_key, partner_key, 'fact_sales_line', sales_line_id
FROM sales_mv WHERE kind = 'CONSIGNMENT' AND consign_loc IS NOT NULL
UNION ALL   -- employees: a transfer to the employee holding location (BR-029)
SELECT d, location_key, product_key, (SELECT movement_type_key FROM mt WHERE movement_code = 'TRANSFER_OUT'), -q, (SELECT location_key FROM emp_loc), partner_key, 'fact_sales_line', sales_line_id
FROM sales_mv WHERE kind = 'EMPLOYEE' AND EXISTS (SELECT 1 FROM emp_loc)
UNION ALL
SELECT d, (SELECT location_key FROM emp_loc), product_key, (SELECT movement_type_key FROM mt WHERE movement_code = 'TRANSFER_IN'), q, location_key, partner_key, 'fact_sales_line', sales_line_id
FROM sales_mv WHERE kind = 'EMPLOYEE' AND EXISTS (SELECT 1 FROM emp_loc);

-- returns: stock timing = when the goods came back (last goods-receipt date for domestic, BR-023)
CREATE TEMP TABLE return_mv ON COMMIT DROP AS
SELECT r.return_line_id, coalesce(r.last_receipt_date_key, r.return_date_key) d, r.receiving_location_key location_key,
       r.product_key, r.quantity q, r.partner_key, r.source_name,
       CASE WHEN r.source_name = 'ERP_RETAIL_RETURN' THEN 'SALE_RETURN'
            WHEN pt.is_internal THEN 'EMPLOYEE' WHEN pt.is_sale_or_return THEN 'CONSIGNMENT'
            WHEN pt.partner_type = 'UNCLASSIFIED' OR r.partner_key = -1 THEN 'UNCLASSIFIED' ELSE 'SALE_RETURN' END AS kind,
       cs.location_key AS consign_loc
FROM core.fact_return_line r
JOIN stock_product sp ON sp.product_key = r.product_key
JOIN core.dim_partner pt ON pt.partner_key = r.partner_key
LEFT JOIN lk_consign cs ON cs.partner_key = r.partner_key
WHERE r.receiving_location_key <> -1;

INSERT INTO core.fact_stock_movement (movement_date_key, location_key, product_key, movement_type_key, quantity,
    counterparty_location_key, partner_key, source_table, source_line_id)
SELECT d, location_key, product_key, (SELECT movement_type_key FROM mt WHERE movement_code = 'SALE_RETURN'), q, NULL::SMALLINT, partner_key, 'fact_return_line', return_line_id
FROM return_mv WHERE kind = 'SALE_RETURN'
UNION ALL
SELECT d, location_key, product_key, (SELECT movement_type_key FROM mt WHERE movement_code = 'RECEIPT_UNCLASSIFIED'), q, NULL::SMALLINT, partner_key, 'fact_return_line', return_line_id
FROM return_mv WHERE kind = 'UNCLASSIFIED'
UNION ALL
SELECT d, consign_loc, product_key, (SELECT movement_type_key FROM mt WHERE movement_code = 'CONSIGNMENT_RETURN_OUT'), -q, location_key, partner_key, 'fact_return_line', return_line_id
FROM return_mv WHERE kind = 'CONSIGNMENT' AND consign_loc IS NOT NULL
UNION ALL
SELECT d, location_key, product_key, (SELECT movement_type_key FROM mt WHERE movement_code = 'CONSIGNMENT_RETURN_IN'), q, consign_loc, partner_key, 'fact_return_line', return_line_id
FROM return_mv WHERE kind = 'CONSIGNMENT' AND consign_loc IS NOT NULL
UNION ALL
SELECT d, (SELECT location_key FROM emp_loc), product_key, (SELECT movement_type_key FROM mt WHERE movement_code = 'TRANSFER_OUT'), -q, location_key, partner_key, 'fact_return_line', return_line_id
FROM return_mv WHERE kind = 'EMPLOYEE' AND EXISTS (SELECT 1 FROM emp_loc)
UNION ALL
SELECT d, location_key, product_key, (SELECT movement_type_key FROM mt WHERE movement_code = 'TRANSFER_IN'), q, (SELECT location_key FROM emp_loc), partner_key, 'fact_return_line', return_line_id
FROM return_mv WHERE kind = 'EMPLOYEE' AND EXISTS (SELECT 1 FROM emp_loc);

-- transfers: OUT leaves the sender on its date, IN arrives at the receiver on its date; the gap is stock in transit
INSERT INTO core.fact_stock_movement (movement_date_key, location_key, product_key, movement_type_key, quantity,
    counterparty_location_key, partner_key, source_table, source_line_id)
SELECT t.document_date_key, t.from_location_key, t.product_key, (SELECT movement_type_key FROM mt WHERE movement_code = 'TRANSFER_OUT'),
       -t.quantity, nullif(t.to_location_key, -1), -1, 'fact_stock_transfer_line', t.transfer_line_id
FROM core.fact_stock_transfer_line t JOIN stock_product sp ON sp.product_key = t.product_key
WHERE t.movement_direction = 'OUT' AND t.from_location_key <> -1
UNION ALL
SELECT t.document_date_key, t.to_location_key, t.product_key, (SELECT movement_type_key FROM mt WHERE movement_code = 'TRANSFER_IN'),
       t.quantity, nullif(t.from_location_key, -1), -1, 'fact_stock_transfer_line', t.transfer_line_id
FROM core.fact_stock_transfer_line t JOIN stock_product sp ON sp.product_key = t.product_key
WHERE t.movement_direction = 'IN' AND t.to_location_key <> -1;

-- goods receipts: purchase from a factory, or return-inward from another party (BR-013).
-- Placed only once the receiving location and the counterparty type are known.
INSERT INTO core.fact_stock_movement (movement_date_key, location_key, product_key, movement_type_key, quantity,
    counterparty_location_key, partner_key, source_table, source_line_id)
SELECT g.grn_date_key, g.receiving_location_key, g.product_key,
       (SELECT movement_type_key FROM mt WHERE movement_code = CASE pt.partner_type WHEN 'FACTORY_SUPPLIER' THEN 'GOODS_RECEIPT' ELSE 'RETURN_INWARD' END),
       g.received_qty, NULL, g.partner_key, 'fact_goods_receipt_line', g.receipt_line_id
FROM core.fact_goods_receipt_line g
JOIN stock_product sp ON sp.product_key = g.product_key
JOIN core.dim_partner pt ON pt.partner_key = g.partner_key
WHERE g.receiving_location_key <> -1 AND pt.partner_type IN ('FACTORY_SUPPLIER','RETURN_SOURCE');

-- partner sell-through leaves the partner location (demand, not revenue: BR-024)
INSERT INTO core.fact_stock_movement (movement_date_key, location_key, product_key, movement_type_key, quantity,
    counterparty_location_key, partner_key, source_table, source_line_id)
SELECT so.order_date_key, so.location_key, so.product_key, (SELECT movement_type_key FROM mt WHERE movement_code = 'CONSIGNMENT_SELLOUT'),
       -so.units_sold, NULL, so.partner_key, 'fact_partner_sellout', so.sellout_id
FROM core.fact_partner_sellout so JOIN stock_product sp ON sp.product_key = so.product_key
WHERE so.location_key <> -1 AND so.units_sold > 0;
