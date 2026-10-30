-- =============================================================================
-- 45  Stock movement check (a mart view, built here so the quality checks in 50 can use it).
-- =============================================================================
-- 2.11 Month-by-month stock check (ERP-reported locations): between two saved stock days, opening stock + recorded
-- movements should equal closing stock. unexplained_qty = closing - expected: negative = stock left with no document in
-- the exports (e.g. assembly, packaging use, write-off not exported); positive = stock arrived with no document.
-- A SKU missing from a day's report counts as 0 there. Movements dated on a stock day belong to that day (end of day).
CREATE OR REPLACE VIEW mart.v_stock_movement_check AS
WITH days AS (SELECT DISTINCT snapshot_date_key FROM core.fact_inventory_snapshot WHERE source_name = 'ERP_INVENTORY_SNAPSHOT'),
pairs AS (SELECT * FROM (SELECT lag(snapshot_date_key) OVER (ORDER BY snapshot_date_key) AS prev_key, snapshot_date_key AS cur_key FROM days) x
          WHERE prev_key IS NOT NULL),
locs AS (SELECT location_key FROM core.dim_location WHERE inventory_system_of_record = 'ERP' AND is_stock_holding AND NOT is_unknown_member),
snap AS (SELECT s.snapshot_date_key, s.location_key, s.product_key, sum(s.on_hand_qty) AS q
         FROM core.fact_inventory_snapshot s JOIN locs USING (location_key)
         WHERE s.source_name = 'ERP_INVENTORY_SNAPSHOT' AND s.product_key <> -1 GROUP BY 1, 2, 3),
mv AS (SELECT p.cur_key, m.location_key, m.product_key, mt.movement_code, sum(m.quantity) AS q
       FROM core.fact_stock_movement m JOIN locs USING (location_key)
       JOIN core.dim_movement_type mt USING (movement_type_key)
       JOIN pairs p ON m.movement_date_key > p.prev_key AND m.movement_date_key <= p.cur_key
       GROUP BY 1, 2, 3, 4),
mvp AS (SELECT cur_key, location_key, product_key, sum(q) AS moved,
               coalesce(sum(q) FILTER (WHERE movement_code IN ('GOODS_RECEIPT','RETURN_INWARD','PRODUCTION_RECEIPT')), 0) AS received,
               coalesce(sum(q) FILTER (WHERE movement_code IN ('SALE','ISSUE_UNCLASSIFIED','CONSIGNMENT_OUT')), 0) AS sold_or_issued,
               coalesce(sum(q) FILTER (WHERE movement_code IN ('SALE_RETURN','RECEIPT_UNCLASSIFIED','CONSIGNMENT_RETURN_IN')), 0) AS returned,
               coalesce(sum(q) FILTER (WHERE movement_code = 'TRANSFER_IN'), 0) AS transferred_in,
               coalesce(sum(q) FILTER (WHERE movement_code = 'TRANSFER_OUT'), 0) AS transferred_out
        FROM mv GROUP BY 1, 2, 3),
keys AS (SELECT p.prev_key, p.cur_key, s.location_key, s.product_key FROM pairs p JOIN snap s ON s.snapshot_date_key IN (p.prev_key, p.cur_key)
         UNION
         SELECT p.prev_key, p.cur_key, m.location_key, m.product_key FROM pairs p JOIN mvp m ON m.cur_key = p.cur_key)
SELECT dp.calendar_date AS period_from, dc.calendar_date AS period_to, dc.month_start_date,
       l.location_code, l.location_name, l.location_type, pr.sku_code, pr.product_name, pr.item_type, pr.category, pr.lifecycle_status,
       coalesce(o.q, 0) AS opening_qty, coalesce(m.received, 0) AS received_qty, coalesce(m.sold_or_issued, 0) AS sold_or_issued_qty,
       coalesce(m.returned, 0) AS returned_qty, coalesce(m.transferred_in, 0) AS transferred_in_qty,
       coalesce(m.transferred_out, 0) AS transferred_out_qty, coalesce(o.q, 0) + coalesce(m.moved, 0) AS expected_closing_qty,
       coalesce(c.q, 0) AS closing_qty, coalesce(c.q, 0) - coalesce(o.q, 0) - coalesce(m.moved, 0) AS unexplained_qty,
       (coalesce(c.q, 0) - coalesce(o.q, 0) - coalesce(m.moved, 0)) * pr.current_cost AS unexplained_value_cost
FROM keys k
JOIN core.dim_date dp ON dp.date_key = k.prev_key
JOIN core.dim_date dc ON dc.date_key = k.cur_key
JOIN core.dim_location l ON l.location_key = k.location_key
JOIN core.dim_product pr ON pr.product_key = k.product_key
LEFT JOIN snap o ON o.snapshot_date_key = k.prev_key AND o.location_key = k.location_key AND o.product_key = k.product_key
LEFT JOIN snap c ON c.snapshot_date_key = k.cur_key AND c.location_key = k.location_key AND c.product_key = k.product_key
LEFT JOIN mvp m ON m.cur_key = k.cur_key AND m.location_key = k.location_key AND m.product_key = k.product_key
WHERE pr.item_type NOT IN ('CHARGE','SERVICE');
