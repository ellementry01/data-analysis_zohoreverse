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

-- 2.17 What the ERP's own documents explain. Per product, for the period of the loaded Document Wise Stock Movement
-- report: the net stock that moved with no document in the exports (all ERP locations and months of the stock check
-- together), beside the units the ERP moved on document types no export carries (scrap, stock increase / decrease,
-- inventory transfer, sub-contractor issue and receipt, return to supplier). explained_qty is the part of the
-- unexplained stock those documents account for (same direction only); still_unexplained_qty is the rest.
-- The report has no dates or locations inside its period, so this is a whole-period, company-wide reading.
CREATE OR REPLACE VIEW mart.v_unexplained_stock_by_document AS
WITH per AS (SELECT min(period_from) AS period_from, max(period_to) AS period_to FROM core.fact_erp_document_movement),
u AS (SELECT c.sku_code, sum(c.unexplained_qty) AS unexplained_qty
      FROM mart.v_stock_movement_check c, per WHERE c.period_to > per.period_from AND c.period_to <= per.period_to GROUP BY 1),
d AS (SELECT p.sku_code,
             coalesce(sum(f.quantity) FILTER (WHERE f.document_type = 'Scrap Note'), 0) AS scrap_qty,
             coalesce(sum(f.quantity) FILTER (WHERE f.document_type = 'Increase Stock'), 0) AS stock_increase_qty,
             coalesce(sum(f.quantity) FILTER (WHERE f.document_type = 'Decrease Stock'), 0) AS stock_decrease_qty,
             coalesce(sum(f.quantity) FILTER (WHERE f.document_type = 'Inventory Transfer'), 0) AS inventory_transfer_qty,
             coalesce(sum(f.quantity) FILTER (WHERE f.document_type = 'DN Sub Contractor'), 0) AS sent_to_subcontractor_qty,
             coalesce(sum(f.quantity) FILTER (WHERE f.document_type = 'GIN (SubContractor)'), 0) AS back_from_subcontractor_qty,
             coalesce(sum(f.quantity) FILTER (WHERE f.document_type = 'Return To Supplier'), 0) AS returned_to_supplier_qty,
             sum(f.quantity) AS documents_not_in_exports_qty
      FROM core.fact_erp_document_movement f JOIN core.dim_product p ON p.product_key = f.product_key
      WHERE NOT f.is_in_other_exports AND f.product_key <> -1 GROUP BY 1),
j AS (SELECT coalesce(u.sku_code, d.sku_code) AS sku_code, coalesce(u.unexplained_qty, 0) AS unexplained_qty,
             coalesce(d.scrap_qty, 0) AS scrap_qty, coalesce(d.stock_increase_qty, 0) AS stock_increase_qty,
             coalesce(d.stock_decrease_qty, 0) AS stock_decrease_qty, coalesce(d.inventory_transfer_qty, 0) AS inventory_transfer_qty,
             coalesce(d.sent_to_subcontractor_qty, 0) AS sent_to_subcontractor_qty,
             coalesce(d.back_from_subcontractor_qty, 0) AS back_from_subcontractor_qty,
             coalesce(d.returned_to_supplier_qty, 0) AS returned_to_supplier_qty,
             coalesce(d.documents_not_in_exports_qty, 0) AS documents_not_in_exports_qty
      FROM u FULL JOIN d ON d.sku_code = u.sku_code),
e AS (SELECT j.*, CASE WHEN sign(j.unexplained_qty) = sign(j.documents_not_in_exports_qty) AND j.unexplained_qty <> 0
                       THEN sign(j.unexplained_qty) * least(abs(j.unexplained_qty), abs(j.documents_not_in_exports_qty)) ELSE 0 END AS explained_qty
      FROM j)
SELECT per.period_from, per.period_to, pr.sku_code, pr.product_name, pr.item_type, pr.category, pr.lifecycle_status,
       e.unexplained_qty, e.scrap_qty, e.stock_increase_qty, e.stock_decrease_qty, e.inventory_transfer_qty,
       e.sent_to_subcontractor_qty, e.back_from_subcontractor_qty, e.returned_to_supplier_qty, e.documents_not_in_exports_qty,
       e.explained_qty, e.unexplained_qty - e.explained_qty AS still_unexplained_qty,
       (e.unexplained_qty - e.explained_qty) * pr.current_cost AS still_unexplained_value_cost
FROM e JOIN core.dim_product pr ON pr.sku_code = e.sku_code CROSS JOIN per
WHERE per.period_from IS NOT NULL AND pr.item_type NOT IN ('CHARGE','SERVICE')
  AND (e.unexplained_qty <> 0 OR e.documents_not_in_exports_qty <> 0);
