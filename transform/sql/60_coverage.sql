-- =============================================================================
-- 60  Coverage per business process per month of the period (meta.process_coverage),
-- so a dashboard or agent says "no data" instead of showing zero.
-- FULL = rows exist and the process is fully covered by today's sources;
-- PARTIAL = rows exist but the design lists gaps; NONE = no rows that month.
-- =============================================================================
DELETE FROM meta.process_coverage
WHERE period_month BETWEEN date_trunc('month', (SELECT period_start FROM ctx))::DATE AND (SELECT period_end FROM ctx);

CREATE TEMP TABLE cov_rows ON COMMIT DROP AS
SELECT 'SALES' p, date_trunc('month', d.calendar_date)::DATE m, string_agg(DISTINCT f.source_name, ', ') src, count(*) n
  FROM core.fact_sales_line f JOIN core.dim_date d ON d.date_key = f.bill_date_key GROUP BY 1, 2
UNION ALL SELECT 'RETURNS', date_trunc('month', d.calendar_date)::DATE, string_agg(DISTINCT f.source_name, ', '), count(*)
  FROM core.fact_return_line f JOIN core.dim_date d ON d.date_key = f.return_date_key GROUP BY 1, 2
UNION ALL SELECT 'PARTNER_SELLOUT', date_trunc('month', d.calendar_date)::DATE, string_agg(DISTINCT f.source_name, ', '), count(*)
  FROM core.fact_partner_sellout f JOIN core.dim_date d ON d.date_key = f.order_date_key GROUP BY 1, 2
UNION ALL SELECT 'TRANSFERS', date_trunc('month', d.calendar_date)::DATE, string_agg(DISTINCT f.source_name, ', '), count(*)
  FROM core.fact_stock_transfer_line f JOIN core.dim_date d ON d.date_key = f.document_date_key GROUP BY 1, 2
UNION ALL SELECT 'PURCHASING', date_trunc('month', d.calendar_date)::DATE, 'ERP_PURCHASE_ORDER', count(*)
  FROM core.fact_purchase_order_line f JOIN core.dim_date d ON d.date_key = f.po_date_key GROUP BY 1, 2
UNION ALL SELECT 'GOODS_RECEIPT', date_trunc('month', d.calendar_date)::DATE, 'ERP_PURCHASE_ORDER', count(*)
  FROM core.fact_goods_receipt_line f JOIN core.dim_date d ON d.date_key = f.grn_date_key GROUP BY 1, 2
UNION ALL SELECT 'STOCK_LEDGER', date_trunc('month', d.calendar_date)::DATE, 'derived', count(*)
  FROM core.fact_stock_movement f JOIN core.dim_date d ON d.date_key = f.movement_date_key GROUP BY 1, 2
UNION ALL SELECT 'CONSIGNMENT', date_trunc('month', d.calendar_date)::DATE, 'derived', count(*)
  FROM core.fact_stock_movement f JOIN core.dim_date d ON d.date_key = f.movement_date_key
  JOIN core.dim_location l ON l.location_key = f.location_key WHERE l.location_type = 'PARTNER_CONSIGNMENT' GROUP BY 1, 2
UNION ALL SELECT 'STOCK_POSITION', date_trunc('month', d.calendar_date)::DATE, string_agg(DISTINCT f.source_name, ', '), count(*)
  FROM core.fact_inventory_snapshot f JOIN core.dim_date d ON d.date_key = f.snapshot_date_key GROUP BY 1, 2
UNION ALL SELECT 'FULFILMENT', date_trunc('month', d.calendar_date)::DATE, 'WMS_DISPATCH', count(*)
  FROM core.fact_shipment f JOIN core.dim_date d ON d.date_key = f.order_date_key GROUP BY 1, 2;

INSERT INTO meta.process_coverage (process_code, period_month, coverage, sources, notes)
SELECT bp.process_code, mo.m::DATE,
       CASE WHEN coalesce(c.n, 0) = 0 THEN 'NONE' WHEN bp.coverage = 'HAVE' THEN 'FULL' ELSE 'PARTIAL' END,
       c.src,
       CASE WHEN coalesce(c.n, 0) = 0 THEN 'No data for this month' ELSE c.n || ' rows' END
FROM meta.business_process bp
CROSS JOIN generate_series(date_trunc('month', (SELECT period_start FROM ctx)), (SELECT period_end FROM ctx), INTERVAL '1 month') mo(m)
LEFT JOIN cov_rows c ON c.p = bp.process_code AND c.m = mo.m::DATE
WHERE bp.process_code <> 'AGENT_OUTPUTS';
