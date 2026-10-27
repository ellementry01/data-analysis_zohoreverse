-- =============================================================================
-- 50  Data-quality checks for this run -> meta.dq_check_result.
-- ERROR checks are a gate: any FAIL rolls the whole build back (see runner).
-- WARN checks are recorded and reported; they never hide data.
-- =============================================================================

CREATE TEMP TABLE dq (check_name TEXT, target_table TEXT, severity TEXT, n BIGINT, details TEXT) ON COMMIT DROP;

-- ============================================================ ERROR: reconciliation gate
-- Every in-period staged line must land exactly once in its fact: no lookup may drop or duplicate rows.
INSERT INTO dq SELECT 'sales_rows_reconcile', 'core.fact_sales_line', 'ERROR', abs(a - b),
       format('staged in-period lines %s, fact lines %s', a, b)
FROM (SELECT (SELECT count(*) FROM stg.retail_sales WHERE bill_date BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx) AND quantity > 0)
           + (SELECT count(*) FROM stg.domestic_sales WHERE bill_date BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx) AND quantity > 0) a,
             (SELECT count(*) FROM core.fact_sales_line) b) x;

INSERT INTO dq SELECT 'sales_value_reconcile', 'core.fact_sales_line', 'ERROR', CASE WHEN abs(a - b) > 0.01 THEN 1 ELSE 0 END,
       format('net sales excl. GST: from source columns %s, in fact %s', a, b)
FROM (SELECT coalesce((SELECT sum(doc_value) FROM stg.retail_sales WHERE bill_date BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx) AND quantity > 0 AND doc_value >= 0), 0)
           + coalesce((SELECT sum(taxable) FROM stg.domestic_sales WHERE bill_date BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx) AND quantity > 0 AND taxable >= 0), 0) a,
             coalesce((SELECT sum(net_sales_amount) FROM core.fact_sales_line WHERE net_amount_method = 'SOURCE'), 0) b) x;

INSERT INTO dq SELECT 'returns_rows_reconcile', 'core.fact_return_line', 'ERROR', abs(a - b), format('staged in-period lines %s, fact lines %s', a, b)
FROM (SELECT (SELECT count(*) FROM stg.retail_return WHERE return_date BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx) AND quantity > 0)
           + (SELECT count(*) FROM stg.domestic_return WHERE return_date BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx) AND quantity > 0) a,
             (SELECT count(*) FROM core.fact_return_line) b) x;

INSERT INTO dq SELECT 'inventory_units_reconcile', 'core.fact_inventory_snapshot', 'ERROR', CASE WHEN abs(a - b) > 0.001 THEN 1 ELSE 0 END,
       format('ERP stock report units in period: staged %s, fact %s', a, b)
FROM (SELECT coalesce((SELECT sum(on_hand_qty) FROM stg.inventory_snapshot WHERE source_name = 'ERP_INVENTORY_SNAPSHOT'
                         AND snapshot_date BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx)), 0) a,
             coalesce((SELECT sum(on_hand_qty) FROM core.fact_inventory_snapshot WHERE source_name = 'ERP_INVENTORY_SNAPSHOT'), 0) b) x;

INSERT INTO dq SELECT 'shipment_rows_reconcile', 'core.fact_shipment', 'ERROR', abs(a - b), format('staged in-period deliveries %s, fact rows %s', a, b)
FROM (SELECT (SELECT count(*) FROM stg.wms_dispatch WHERE order_date BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx)) a,
             (SELECT count(*) FROM core.fact_shipment) b) x;

INSERT INTO dq SELECT 'ledger_sign_matches_type', 'core.fact_stock_movement', 'ERROR', count(*), 'movements whose sign contradicts their movement type'
FROM core.fact_stock_movement m JOIN core.dim_movement_type t USING (movement_type_key) WHERE sign(m.quantity) <> t.stock_effect;

INSERT INTO dq SELECT 'transfer_rows_reconcile', 'core.fact_stock_transfer_line', 'ERROR', abs(a - b), format('staged in-period lines %s (minus same-location lines), fact lines %s', a, b)
FROM (SELECT (SELECT count(*) FROM stg.transfer_out WHERE document_date BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx) AND quantity > 0)
           + (SELECT count(*) FROM stg.transfer_in  WHERE document_date BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx) AND quantity > 0)
           - (SELECT count(*) FROM stg.transfer_out o
                LEFT JOIN lk_prefix f ON f.source_name = 'ERP_STOCK_TRANSFER_OUT' AND f.doc_prefix = o.doc_prefix
                LEFT JOIN lk_loc t ON t.source_name = 'ERP_STOCK_TRANSFER_OUT' AND t.source_field = 'CONTACTNAME' AND t.source_value = o.contact_name
               WHERE o.document_date BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx) AND o.quantity > 0
                 AND f.location_key = t.location_key) a,
             (SELECT count(*) FROM core.fact_stock_transfer_line) b) x;

-- ============================================================ WARN: unmatched values (BR-027)
INSERT INTO dq SELECT 'unknown_product', f, 'WARN', n, d FROM (
    SELECT 'core.fact_sales_line' f, count(*) n, string_agg(DISTINCT source_sku_code, ', ') d FROM core.fact_sales_line WHERE product_key = -1
    UNION ALL SELECT 'core.fact_return_line', count(*), string_agg(DISTINCT source_sku_code, ', ') FROM core.fact_return_line WHERE product_key = -1
    UNION ALL SELECT 'core.fact_stock_transfer_line', count(*), string_agg(DISTINCT source_sku_code, ', ') FROM core.fact_stock_transfer_line WHERE product_key = -1
    UNION ALL SELECT 'core.fact_partner_sellout', count(*), string_agg(DISTINCT source_sku_code, ', ') FROM core.fact_partner_sellout WHERE product_key = -1
    UNION ALL SELECT 'core.fact_inventory_snapshot', count(*), string_agg(DISTINCT source_sku_code, ', ') FROM core.fact_inventory_snapshot WHERE product_key = -1) x;

INSERT INTO dq SELECT 'unknown_location', f, 'WARN', n, d FROM (
    SELECT 'core.fact_sales_line' f, count(*) n, NULL d FROM core.fact_sales_line WHERE location_key = -1
    UNION ALL SELECT 'core.fact_return_line', count(*), NULL FROM core.fact_return_line WHERE receiving_location_key = -1
    UNION ALL SELECT 'core.fact_stock_transfer_line', count(*), 'from or to unknown (e.g. Dileep Essentials Pvt Ltd Bagru)'
              FROM core.fact_stock_transfer_line WHERE from_location_key = -1 OR to_location_key = -1
    UNION ALL SELECT 'core.fact_inventory_snapshot', count(*), string_agg(DISTINCT source_location_value, ', ') FROM core.fact_inventory_snapshot WHERE location_key = -1) x;

INSERT INTO dq SELECT 'unknown_channel', 'core.fact_sales_line', 'WARN', count(*),
       'lines by source: ' || coalesce(string_agg(DISTINCT source_name, ', '), '-') || ' (domestic lines take the channel from the partner type)'
FROM core.fact_sales_line WHERE channel_key = -1;

-- ============================================================ WARN: shipments (WMS dispatch)
INSERT INTO dq SELECT 'shipment_unknown_channel', 'core.fact_shipment', 'WARN', count(*),
       'Site Location values not in ref.channel_alias and invoice not matched: ' || coalesce(string_agg(DISTINCT s.site_location, ', '), '-')
FROM core.fact_shipment f JOIN stg.wms_dispatch s ON s.batch_id = f.batch_id AND s.source_row_number = f.source_row_number
WHERE f.channel_key = -1;

INSERT INTO dq SELECT 'shipment_status_unmapped', 'core.fact_shipment', 'WARN', count(*),
       'statuses not in ref.code_mapping SHIPMENT_STATUS: ' || coalesce(string_agg(DISTINCT shipment_status_raw, ', '), '-')
FROM core.fact_shipment WHERE shipment_status = 'UNMAPPED';

INSERT INTO dq SELECT 'courier_unmapped', 'core.dim_courier', 'WARN', count(*),
       'courier names not in ref.code_mapping COURIER: ' || coalesce(string_agg(courier_name, ', ' ORDER BY courier_name), '-')
FROM core.dim_courier WHERE courier_group = 'Other (unmapped)';

INSERT INTO dq SELECT 'shipment_weight_suspect', 'core.fact_shipment', 'WARN', count(*),
       'weight over 100 kg per delivery (likely grams typed as kg); left out of weight figures. Max: ' || coalesce(max(weight_kg)::TEXT, '-')
FROM core.fact_shipment WHERE weight_kg > 100;

INSERT INTO dq SELECT 'shipment_without_invoice_match', 'core.fact_shipment', 'WARN', count(*),
       'deliveries linked to no loaded sales bill by Invoice No, Extern Order No or AWB (bill outside the loaded period, or not exported)'
FROM core.fact_shipment f WHERE f.sales_link_method = 'NONE';

INSERT INTO dq SELECT 'shipment_sku_unallocated', 'core.bridge_shipment_sku', 'WARN', count(*),
       'SKUs in multi-SKU dispatch cells whose own quantity is not known (no single matching invoice line); left empty, never split'
FROM core.bridge_shipment_sku WHERE quantity_source = 'UNALLOCATED';

-- ============================================================ WARN: partner classification
INSERT INTO dq SELECT 'unclassified_partners', 'core.dim_partner', 'WARN', count(DISTINCT p.partner_key),
       format('%s lines, net Rs %s. Top: %s', sum(x.lines), round(sum(x.val), 0),
              (SELECT string_agg(nm, '; ') FROM (SELECT p2.partner_name || ' (' || count(*) || ')' nm FROM core.fact_sales_line s2
                 JOIN core.dim_partner p2 USING (partner_key) WHERE p2.partner_type = 'UNCLASSIFIED' GROUP BY p2.partner_name ORDER BY count(*) DESC LIMIT 8) t))
FROM core.dim_partner p
JOIN (SELECT partner_key, count(*) lines, sum(coalesce(net_sales_amount, 0)) val FROM core.fact_sales_line GROUP BY 1) x USING (partner_key)
WHERE p.partner_type = 'UNCLASSIFIED' AND NOT p.is_unknown_member;

INSERT INTO dq SELECT 'partners_classified_by_elimination', 'core.dim_partner', 'WARN', count(*),
       coalesce(string_agg(partner_name || ' -> ' || partner_type, '; '), 'none (partner_list_complete = false)')
FROM core.dim_partner WHERE classification_method = 'DEFAULT_RULE' AND partner_role = 'CUSTOMER' AND partner_type <> 'D2C_CHANNEL_ACCOUNT'
   OR (classification_method = 'DEFAULT_RULE' AND partner_role = 'SUPPLIER');

-- ============================================================ WARN: dates, amounts, cut-off
INSERT INTO dq SELECT 'outside_period_excluded', t, 'WARN', n, 'rows outside the prototype period (BR-020); kept in raw' FROM (
    SELECT 'stg.retail_sales' t, count(*) FILTER (WHERE bill_date NOT BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx)) n FROM stg.retail_sales
    UNION ALL SELECT 'stg.domestic_sales', count(*) FILTER (WHERE bill_date NOT BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx)) FROM stg.domestic_sales
    UNION ALL SELECT 'stg.retail_return', count(*) FILTER (WHERE return_date NOT BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx)) FROM stg.retail_return
    UNION ALL SELECT 'stg.domestic_return', count(*) FILTER (WHERE return_date NOT BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx)) FROM stg.domestic_return
    UNION ALL SELECT 'stg.purchase_order', count(*) FILTER (WHERE po_date NOT BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx)) FROM stg.purchase_order
    UNION ALL SELECT 'stg.blinkit_sales', count(*) FILTER (WHERE order_date NOT BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx)) FROM stg.blinkit_sales
    UNION ALL SELECT 'stg.instamart_sales', count(*) FILTER (WHERE order_date NOT BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx)) FROM stg.instamart_sales
    UNION ALL SELECT 'stg.inventory_snapshot', count(*) FILTER (WHERE snapshot_date NOT BETWEEN (SELECT period_start FROM ctx) AND (SELECT period_end FROM ctx)) FROM stg.inventory_snapshot) x;

INSERT INTO dq SELECT 'unparseable_dates', t, 'WARN', n, 'non-empty date text that is not a valid date; row excluded' FROM (
    SELECT 'stg.retail_sales' t, count(*) FILTER (WHERE bill_date IS NULL AND bill_date_raw IS NOT NULL) n FROM stg.retail_sales
    UNION ALL SELECT 'stg.domestic_sales', count(*) FILTER (WHERE bill_date IS NULL AND bill_date_raw IS NOT NULL) FROM stg.domestic_sales
    UNION ALL SELECT 'stg.retail_return', count(*) FILTER (WHERE return_date IS NULL AND return_date_raw IS NOT NULL) FROM stg.retail_return
    UNION ALL SELECT 'stg.domestic_return', count(*) FILTER (WHERE return_date IS NULL AND return_date_raw IS NOT NULL) FROM stg.domestic_return
    UNION ALL SELECT 'stg.transfer_out', count(*) FILTER (WHERE document_date IS NULL AND document_date_raw IS NOT NULL) FROM stg.transfer_out
    UNION ALL SELECT 'stg.transfer_in', count(*) FILTER (WHERE document_date IS NULL AND document_date_raw IS NOT NULL) FROM stg.transfer_in
    UNION ALL SELECT 'stg.purchase_order', count(*) FILTER (WHERE po_date IS NULL AND po_date_raw IS NOT NULL) FROM stg.purchase_order) x;

INSERT INTO dq SELECT 'net_amount_not_from_source', 'core.fact_sales_line', 'WARN',
       count(*) FILTER (WHERE net_amount_method <> 'SOURCE'),
       format('DERIVED %s lines (BR-002 / BR-003), MISSING %s lines', count(*) FILTER (WHERE net_amount_method = 'DERIVED'), count(*) FILTER (WHERE net_amount_method = 'MISSING'))
FROM core.fact_sales_line;

INSERT INTO dq SELECT 'return_receipt_dates_unusable', 'stg.domestic_return_receipt', 'WARN', count(*),
       'goods receipts whose date cannot be paired: the ERP date list is shorter than the receipt list, so which receipt lacks a date is unknown. Left out of the receipts bridge; the return uses the dates that are given'
FROM stg.domestic_return_receipt WHERE goods_receipt_date IS NULL;

-- ============================================================ WARN: links between documents
INSERT INTO dq SELECT 'transfer_in_without_outward', 'core.fact_stock_transfer_line', 'WARN', count(*),
       'receipts whose outward document is not loaded: receiving location unknown'
FROM core.fact_stock_transfer_line WHERE movement_direction = 'IN' AND to_location_key = -1;

INSERT INTO dq SELECT 'return_without_original_sale', 'core.fact_return_line', 'WARN', count(*),
       format('retail %s, domestic %s (expected for sales before the loaded period)',
              count(*) FILTER (WHERE source_name = 'ERP_RETAIL_RETURN'), count(*) FILTER (WHERE source_name = 'ERP_DOMESTIC_RETURN'))
FROM core.fact_return_line WHERE original_sales_line_id IS NULL;

INSERT INTO dq SELECT 'po_lines_with_several_receipts', 'core.fact_goods_receipt_line', 'WARN', count(*),
       format('%s receipts listed with one date and one total quantity; lead time approximate (gap G-027)', coalesce(sum(receipt_count), 0))
FROM core.fact_goods_receipt_line WHERE receipt_count > 1;

-- PO Document Remark (BR-031, proposed): lines the export does not mark Purchase / Return, and lines whose remark
-- contradicts the counterparty's classification. Both must be explained before the rule is confirmed.
INSERT INTO dq SELECT 'po_document_type_unknown', 'core.fact_purchase_order_line', 'WARN', count(*),
       format('%s PO line(s) without a Purchase / Return remark (exports before the column existed, or an unexpected value)', count(*))
FROM core.fact_purchase_order_line WHERE document_type = 'UNKNOWN';

INSERT INTO dq SELECT 'po_remark_contradicts_partner_type', 'core.fact_purchase_order_line', 'WARN', count(*),
       coalesce(string_agg(DISTINCT pt.partner_name || ' (' || pt.partner_type || ', remark ' || po.document_type || ')', '; '), '-')
FROM core.fact_purchase_order_line po JOIN core.dim_partner pt USING (partner_key)
WHERE (po.document_type = 'PURCHASE' AND pt.partner_type = 'RETURN_SOURCE')
   OR (po.document_type = 'RETURN' AND pt.partner_type = 'FACTORY_SUPPLIER');

-- ============================================================ WARN: products and stock
INSERT INTO dq SELECT 'trading_sku_not_in_master', 'core.dim_product', 'WARN', count(*), string_agg(sku_code, ', ' ORDER BY sku_code)
FROM core.dim_product WHERE lifecycle_status = 'NOT_IN_MASTER';

INSERT INTO dq SELECT 'unknown_item_type', 'core.dim_product', 'WARN', count(*), string_agg(sku_code, ', ' ORDER BY sku_code)
FROM core.dim_product WHERE item_type = 'UNKNOWN' AND NOT is_unknown_member;

INSERT INTO dq SELECT 'negative_stock', 'core.fact_inventory_snapshot', 'WARN', count(*),
       coalesce(string_agg(DISTINCT source_location_value, ', '), '-') FROM core.fact_inventory_snapshot WHERE on_hand_qty < 0;

INSERT INTO dq SELECT 'stock_at_inactive_location', 'core.fact_inventory_snapshot', 'WARN', count(*),
       coalesce(string_agg(DISTINCT l.location_code, ', '), '-')
FROM core.fact_inventory_snapshot s JOIN core.dim_location l USING (location_key) WHERE NOT l.is_active;

-- ============================================================ WARN: ledger completeness (nothing guessed)
INSERT INTO dq SELECT 'ledger_not_placed', what, 'WARN', n, why FROM (
    SELECT 'sales lines' what, count(*) n, 'unknown selling location or product' why FROM core.fact_sales_line s
      JOIN core.dim_product p USING (product_key) WHERE p.item_type NOT IN ('CHARGE','SERVICE') AND (s.location_key = -1 OR s.product_key = -1)
    UNION ALL SELECT 'goods receipts', count(*), 'purchase vs return-inward not known: supplier not classified (factory list, G-005) and rule BR-031 not confirmed'
      FROM core.fact_goods_receipt_line g JOIN core.dim_partner pt USING (partner_key)
      LEFT JOIN core.fact_purchase_order_line po ON po.po_line_id = g.po_line_id
     WHERE g.receiving_location_key = -1
        OR NOT (pt.partner_type IN ('FACTORY_SUPPLIER','RETURN_SOURCE')
                OR (po.document_type IN ('PURCHASE','RETURN') AND EXISTS (SELECT 1 FROM meta.pipeline_setting
                    WHERE setting_key = 'po_document_remark_confirmed' AND setting_value = 'true')))
    UNION ALL SELECT 'platform sell-out', count(*), 'the platform export does not say which of its locations the units left'
      FROM core.fact_partner_sellout WHERE location_key = -1
    UNION ALL SELECT 'consignment lines', count(*), 'sale-or-return partner has no consignment location in ref.partner_list'
      FROM core.fact_sales_line s JOIN core.dim_partner p USING (partner_key)
     WHERE p.is_sale_or_return AND NOT EXISTS (SELECT 1 FROM lk_consign c WHERE c.partner_key = s.partner_key)) x;

-- Opening stock implied by today's snapshot minus the recorded movements. Negative = an inflow is missing
-- from the ledger (expected while goods receipts cannot be placed).
INSERT INTO dq SELECT 'implied_negative_opening_stock', 'core.fact_stock_movement', 'WARN', count(*),
       format('location x SKU pairs whose snapshot minus recorded movements is below zero, as of %s', max(snap_date))
FROM (SELECT s.location_key, s.product_key, max(d.calendar_date) snap_date, sum(s.on_hand_qty) snap,
             coalesce((SELECT sum(m.quantity) FROM core.fact_stock_movement m WHERE m.location_key = s.location_key
                        AND m.product_key = s.product_key AND m.movement_date_key <= s.snapshot_date_key), 0) moved
      FROM core.fact_inventory_snapshot s JOIN core.dim_date d ON d.date_key = s.snapshot_date_key
      JOIN core.dim_location l ON l.location_key = s.location_key
      WHERE s.source_name = 'ERP_INVENTORY_SNAPSHOT' AND l.inventory_system_of_record = 'ERP' AND s.location_key <> -1 AND s.product_key <> -1
      GROUP BY s.location_key, s.product_key, s.snapshot_date_key) x
WHERE snap - moved < 0;

-- ============================================================ write results
INSERT INTO meta.dq_check_result (transform_run_id, check_name, target_table, severity, outcome, failed_row_count, details)
SELECT (SELECT run_id FROM ctx), check_name, target_table, severity, CASE WHEN n > 0 THEN 'FAIL' ELSE 'PASS' END,
       least(coalesce(n, 0), 2147483647), left(coalesce(details, ''), 4000)
FROM dq;
