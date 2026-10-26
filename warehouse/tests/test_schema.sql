-- =============================================================================
-- tests/test_schema.sql  |  Proves the schema accepts valid data and rejects bad data.
-- Runs inside one transaction and ROLLS BACK: leaves the database untouched.
-- [PG-ONLY] test harness (DO blocks). Prints PASS/FAIL per test; raises at end if any FAIL.
-- Run:  psql -d <db> -v ON_ERROR_STOP=1 -f tests/test_schema.sql
-- =============================================================================
BEGIN;

-- Prerequisite: the v2 warehouse needs its business rules and mappings (bash load_seeds.sh <db>).
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM meta.business_rule) THEN
        RAISE EXCEPTION 'Load the seeds first: bash load_seeds.sh <database>  (the v2 tables cite business rules that must exist)';
    END IF;
END $$;

CREATE TEMP TABLE test_result (test_name TEXT, passed BOOLEAN, detail TEXT);

-- helper: statement MUST fail
CREATE FUNCTION pg_temp.expect_fail(p_name TEXT, p_sql TEXT) RETURNS VOID AS $$
BEGIN
    BEGIN
        EXECUTE p_sql;
        INSERT INTO test_result VALUES (p_name, FALSE, 'statement succeeded but should have been rejected');
    EXCEPTION WHEN OTHERS THEN
        INSERT INTO test_result VALUES (p_name, TRUE, SQLERRM);
    END;
END $$ LANGUAGE plpgsql;

-- helper: statement MUST succeed
CREATE FUNCTION pg_temp.expect_ok(p_name TEXT, p_sql TEXT) RETURNS VOID AS $$
BEGIN
    BEGIN
        EXECUTE p_sql;
        INSERT INTO test_result VALUES (p_name, TRUE, 'ok');
    EXCEPTION WHEN OTHERS THEN
        INSERT INTO test_result VALUES (p_name, FALSE, SQLERRM);
    END;
END $$ LANGUAGE plpgsql;

-- helper: boolean assertion
CREATE FUNCTION pg_temp.expect_true(p_name TEXT, p_sql TEXT) RETURNS VOID AS $$
DECLARE v BOOLEAN;
BEGIN
    EXECUTE p_sql INTO v;
    INSERT INTO test_result VALUES (p_name, COALESCE(v, FALSE), p_sql);
END $$ LANGUAGE plpgsql;

-- ---------------------------------------------------------------- dim_date
SELECT pg_temp.expect_true('dim_date: every day 1-Apr-2024..31-Mar-2031 present exactly once',
  $q$SELECT count(*) = (DATE '2031-03-31' - DATE '2024-04-01') + 1 AND count(*) = count(DISTINCT calendar_date) FROM core.dim_date$q$);
SELECT pg_temp.expect_true('dim_date: 1-Apr-2026 is FY 2026-27, Q1, fiscal month 1',
  $q$SELECT fiscal_year_label = '2026-27' AND fiscal_quarter = 1 AND fiscal_month = 1 FROM core.dim_date WHERE date_key = 20260401$q$);
SELECT pg_temp.expect_true('dim_date: 31-Mar-2027 is FY 2026-27, Q4, month 12, month end',
  $q$SELECT fiscal_year_label = '2026-27' AND fiscal_quarter = 4 AND fiscal_month = 12 AND is_month_end FROM core.dim_date WHERE date_key = 20270331$q$);
SELECT pg_temp.expect_true('dim_date: 15-Sep-2026 is Tuesday, FY Q2, week starts 14-Sep',
  $q$SELECT day_name = 'Tuesday' AND fiscal_quarter = 2 AND week_start_date = DATE '2026-09-14' FROM core.dim_date WHERE date_key = 20260915$q$);
SELECT pg_temp.expect_true('dim_date: 29-Feb-2028 exists (leap year)',
  'SELECT count(*) = 1 FROM core.dim_date WHERE date_key = 20280229');

-- ---------------------------------------------------------------- meta
SELECT pg_temp.expect_ok('meta: register a load batch',
  $q$INSERT INTO meta.load_batch (source_name, file_name, file_sha256, period_start, period_end, status, loaded_by)
     VALUES ('ERP_RETAIL_SALES','Retail_Sales.xlsx', repeat('a',64), '2026-04-01','2026-09-15','LOADED','test')$q$);
SELECT pg_temp.expect_fail('meta: same file cannot be loaded twice while live',
  $q$INSERT INTO meta.load_batch (source_name, file_name, file_sha256, period_start, status, loaded_by)
     VALUES ('ERP_RETAIL_SALES','Retail_Sales_copy.xlsx', repeat('a',64), '2026-04-01','STARTED','test')$q$);
SELECT pg_temp.expect_ok('meta: a FAILED load of a file can be retried',
  $q$INSERT INTO meta.load_batch (source_name, file_name, file_sha256, period_start, status, loaded_by)
     VALUES ('ERP_DOMESTIC_SALES','d.xlsx', repeat('b',64), '2026-04-01','FAILED','test');
     INSERT INTO meta.load_batch (source_name, file_name, file_sha256, period_start, status, loaded_by)
     VALUES ('ERP_DOMESTIC_SALES','d.xlsx', repeat('b',64), '2026-04-01','STARTED','test')$q$);
SELECT pg_temp.expect_fail('meta: unregistered source rejected',
  $q$INSERT INTO meta.load_batch (source_name, file_name, file_sha256, period_start, loaded_by)
     VALUES ('SOME_RANDOM_SOURCE','x.xlsx', repeat('c',64), '2026-04-01','test')$q$);
SELECT pg_temp.expect_fail('meta: period_end before period_start rejected',
  $q$INSERT INTO meta.load_batch (source_name, file_name, file_sha256, period_start, period_end, loaded_by)
     VALUES ('ERP_RETAIL_SALES','y.xlsx', repeat('d',64), '2026-09-15','2026-04-01','test')$q$);

SELECT pg_temp.expect_ok('meta: a FAILED load with no dates is recorded (file rejected before any date was read)',
  $q$INSERT INTO meta.load_batch (source_name, file_name, file_sha256, status, loaded_by, notes)
     VALUES ('ERP_RETAIL_SALES','broken.xlsx', repeat('e',64), 'FAILED','test','ContractError: columns differ')$q$);
SELECT pg_temp.expect_fail('meta: a LOADED batch must have a period or an as-of date',
  $q$INSERT INTO meta.load_batch (source_name, file_name, file_sha256, status, loaded_by)
     VALUES ('ERP_RETAIL_SALES','nodate.xlsx', repeat('f',64), 'LOADED','test')$q$);

-- ---------------------------------------------------------------- ref
SELECT pg_temp.expect_ok('ref: add locations',
  $q$INSERT INTO ref.location_master (location_code, erp_location_name, location_name, location_type, operated_by,
        gst_state_code, city, is_stock_holding, is_sellable_stock, inventory_system_of_record)
     VALUES ('TEST_WH','99 TEST Warehouse','Test Warehouse','CENTRAL_WAREHOUSE','SELF','08','Jaipur',TRUE,TRUE,'ERP'),
            ('TEST_FBA','99 TEST FBA','Test FBA','AMAZON_FBA','AMAZON','24','Ahmedabad',TRUE,TRUE,'ERP')$q$);
SELECT pg_temp.expect_fail('ref: a second location cannot reuse an ERP location name',
  $q$INSERT INTO ref.location_master (location_code, erp_location_name, location_name, location_type, operated_by,
        is_stock_holding, is_sellable_stock, inventory_system_of_record)
     VALUES ('TEST_DUP','99 TEST Warehouse','Dup','OWN_STORE','SELF',TRUE,TRUE,'ERP')$q$);
SELECT pg_temp.expect_fail('ref: sellable location must hold stock',
  $q$INSERT INTO ref.location_master (location_code, location_name, location_type, operated_by,
        is_stock_holding, is_sellable_stock, inventory_system_of_record)
     VALUES ('BAD','Bad','OWN_STORE','SELF',FALSE,TRUE,'ERP')$q$);
SELECT pg_temp.expect_fail('ref: invalid location_type rejected',
  $q$INSERT INTO ref.location_master (location_code, location_name, location_type, operated_by,
        is_stock_holding, is_sellable_stock, inventory_system_of_record)
     VALUES ('BAD2','Bad','WAREHOUS','SELF',TRUE,TRUE,'ERP')$q$);
SELECT pg_temp.expect_fail('ref: alias must point to an existing location',
  $q$INSERT INTO ref.location_alias (source_name, source_field, source_value, location_code)
     VALUES ('ERP_STOCK_TRANSFER_OUT','CONTACTNAME','Dileep Essentials Pvt Ltd Ahmedabad FBA AMD2','NOPE')$q$);
SELECT pg_temp.expect_fail('ref: channel alias must point to an existing channel',
  $q$INSERT INTO ref.channel_alias (source_name, source_field, source_value, channel_code)
     VALUES ('ERP_RETAIL_SALES','Payment mode/Account','Prepaid - Amazon','NOPE')$q$);
SELECT pg_temp.expect_ok('ref: same legal name allowed as CUSTOMER and as SUPPLIER',
  $q$INSERT INTO ref.partner_list (partner_name, partner_role, partner_type)
     VALUES ('T Group Entity Pvt Ltd','CUSTOMER','GROUP_EXPORT'),
            ('Dileep Crafts Private Limited','SUPPLIER','FACTORY_SUPPLIER')$q$);

SELECT pg_temp.expect_true('ref: franchise, SIS and quick-commerce are sale-or-return; B2B is final',
  $q$SELECT bool_and(is_sale_or_return) FILTER (WHERE partner_type IN ('FRANCHISE_PARTNER','SIS_PARTNER','QUICK_COMMERCE_PARTNER'))
        AND NOT bool_or(is_sale_or_return) FILTER (WHERE partner_type = 'B2B_CUSTOMER') FROM ref.partner_type$q$);
SELECT pg_temp.expect_true('ref: group exports are related-party, employees are internal',
  $q$SELECT bool_and(is_related_party) FILTER (WHERE partner_type = 'GROUP_EXPORT')
        AND bool_and(is_internal) FILTER (WHERE partner_type = 'EMPLOYEE') FROM ref.partner_type$q$);
SELECT pg_temp.expect_fail('ref: retired type GROUP_COMPANY no longer accepted',
  $q$INSERT INTO ref.partner_list (partner_name, partner_role, partner_type) VALUES ('X','CUSTOMER','GROUP_COMPANY')$q$);

-- ---------------------------------------------------------------- context registers
SELECT pg_temp.expect_true('registers: business rules loaded, incl. design-approved BR-022 / BR-023 / BR-028',
  $q$SELECT count(*) >= 30 AND count(*) FILTER (WHERE rule_id IN ('BR-022','BR-023','BR-028') AND confirmation_source = 'DESIGN_APPROVAL') = 3 FROM meta.business_rule$q$);
SELECT pg_temp.expect_fail('registers: a SUPERSEDED rule must name its replacement',
  $q$INSERT INTO meta.business_rule (rule_id,title,statement,domain,applies_to,confirmation_source,recorded_on,status)
     VALUES ('BR-900','t','s','REVENUE','x','DESIGN',DATE '2026-10-01','SUPERSEDED')$q$);
SELECT pg_temp.expect_fail('registers: rule ids must look like BR-nnn',
  $q$INSERT INTO meta.business_rule (rule_id,title,statement,domain,applies_to,confirmation_source,recorded_on)
     VALUES ('RULE1','t','s','REVENUE','x','DESIGN',DATE '2026-10-01')$q$);
SELECT pg_temp.expect_fail('registers: a CLOSED gap needs a closing date',
  $q$INSERT INTO meta.data_gap (gap_id,title,needed_for,needed_by,how_to_fill,owner,priority,status)
     VALUES ('G-900','t','x','Stock','y','BUSINESS','LOW','CLOSED')$q$);
SELECT pg_temp.expect_fail('registers: a source note must cite an existing rule',
  $q$INSERT INTO meta.source_note (source_name,note_id,category,note,rule_id) VALUES ('ERP_RETAIL_SALES',99,'TRAP','x','BR-999')$q$);
SELECT pg_temp.expect_fail('registers: coverage is recorded per calendar month (day 1)',
  $q$INSERT INTO meta.process_coverage (process_code,period_month,coverage) VALUES ('SALES',DATE '2026-04-15','FULL')$q$);
SELECT pg_temp.expect_true('registers: every gap points at a known process',
  $q$SELECT bool_and(process_code IS NOT NULL) FROM meta.data_gap$q$);
SELECT pg_temp.expect_true('registers: every process built NOW has its table in the database (or is a mart view / insight)',
  $q$SELECT bool_and(to_regclass(p.table_name) IS NOT NULL OR p.table_name LIKE 'mart view%' OR p.table_name = 'insight.*')
     FROM meta.business_process p WHERE p.build_phase = 'NOW'$q$);
SELECT pg_temp.expect_true('registers: every core / insight column has a business definition',
  $q$SELECT count(*) = 0 FROM meta.column_dictionary WHERE table_schema IN ('core','insight') AND coalesce(business_definition,'') = ''$q$);
SELECT pg_temp.expect_true('registers: dictionary shows lineage and rules, e.g. net sales = BR-001..003',
  $q$SELECT lineage LIKE '%PRODDOCVALUE%' AND rules = 'BR-001, BR-002, BR-003' FROM meta.column_dictionary
     WHERE table_schema='core' AND table_name='fact_sales_line' AND column_name='net_sales_amount'$q$);
SELECT pg_temp.expect_true('safety: partner list starts as incomplete (no classification by elimination yet)',
  $q$SELECT setting_value = 'false' FROM meta.pipeline_setting WHERE setting_key = 'partner_list_complete'$q$);
SELECT pg_temp.expect_true('mappings: every ref mapping that cites a rule cites one that exists (FK) and Bagru cites BR-016',
  $q$SELECT rule_id = 'BR-016' FROM ref.location_master WHERE location_code = 'BAGRU_WH'$q$);

-- ---------------------------------------------------------------- dimensions
SELECT pg_temp.expect_ok('dim: add channel / partner / location / product / order / courier',
  $q$INSERT INTO core.dim_channel (channel_code, channel_name, sub_channel_name, channel_group, fulfilment_model, is_sale_or_return, is_active, is_confirmed)
       VALUES ('T_WEB','Own Website','Shopify','D2C_WEBSITE','SELF_SHIP',FALSE,TRUE,FALSE),
              ('T_QC','Blinkit','Quick commerce','QUICK_COMMERCE','PARTNER',TRUE,TRUE,TRUE);
     INSERT INTO core.dim_partner (partner_name, partner_role, partner_type, is_internal, is_related_party, is_sale_or_return,
       classification_method, classification_rule_id, is_confirmed)
       VALUES ('T Shopify_Customer','CUSTOMER','D2C_CHANNEL_ACCOUNT',FALSE,FALSE,FALSE,'DEFAULT_RULE','BR-005',TRUE),
              ('T KIRANAKART','CUSTOMER','QUICK_COMMERCE_PARTNER',FALSE,FALSE,TRUE,'LISTED','BR-012',TRUE),
              ('T Factory','SUPPLIER','FACTORY_SUPPLIER',FALSE,FALSE,FALSE,'LISTED','BR-013',FALSE);
     INSERT INTO core.dim_location (location_code, location_name, location_type, operated_by, is_stock_holding, is_sellable_stock,
       inventory_system_of_record, is_active, is_confirmed, rule_id)
       VALUES ('T_WH','Test Warehouse','CENTRAL_WAREHOUSE','SELF',TRUE,TRUE,'ERP',TRUE,FALSE,'BR-016'),
              ('T_FBA','Test FBA','AMAZON_FBA','AMAZON',TRUE,TRUE,'ERP',TRUE,FALSE,'BR-019');
     INSERT INTO core.dim_location (location_code, location_name, location_type, operated_by, partner_key, is_stock_holding,
       is_sellable_stock, inventory_system_of_record, is_active, is_confirmed, rule_id)
       SELECT 'T_CONSIGN','Test consignment','PARTNER_CONSIGNMENT','BLINKIT',partner_key,TRUE,TRUE,'NONE',TRUE,FALSE,'BR-022'
       FROM core.dim_partner WHERE partner_name = 'T KIRANAKART';
     INSERT INTO core.dim_product (sku_code, product_name, item_type, lifecycle_status, current_mrp)
       VALUES ('T_GSTEA2724','Glass Bottle','TRADING','CONTINUED',850), ('T_SET2','Bottle set of 2','TRADING','CONTINUED',1600),
              ('T_SHIPPING R','Shipping charge','CHARGE','NOT_APPLICABLE',NULL);
     INSERT INTO core.dim_order (channel_key, external_order_number, wms_order_number)
       SELECT channel_key,'T-124118580','T-M2819390' FROM core.dim_channel WHERE channel_code='T_WEB';
     INSERT INTO core.dim_courier (courier_name, service_level, aggregator) VALUES ('T Delhivery','SURFACE',NULL)$q$);
SELECT pg_temp.expect_fail('dim: a partner consignment location must name its partner',
  $q$INSERT INTO core.dim_location (location_code, location_name, location_type, operated_by, is_stock_holding, is_sellable_stock,
       inventory_system_of_record, is_active, is_confirmed) VALUES ('T_BAD','x','PARTNER_CONSIGNMENT','BLINKIT',TRUE,TRUE,'NONE',TRUE,FALSE)$q$);
SELECT pg_temp.expect_fail('dim: partner classification must cite an existing rule',
  $q$INSERT INTO core.dim_partner (partner_name, partner_role, partner_type, is_internal, is_related_party, is_sale_or_return,
       classification_method, classification_rule_id, is_confirmed) VALUES ('T X','CUSTOMER','B2B_CUSTOMER',FALSE,FALSE,FALSE,'LISTED','BR-999',FALSE)$q$);
SELECT pg_temp.expect_fail('dim: trading SKU cannot be NOT_APPLICABLE lifecycle',
  $q$INSERT INTO core.dim_product (sku_code, product_name, item_type, lifecycle_status) VALUES ('T_X1','x','TRADING','NOT_APPLICABLE')$q$);
SELECT pg_temp.expect_fail('dim: discontinue date before launch date rejected',
  $q$INSERT INTO core.dim_product (sku_code, product_name, item_type, lifecycle_status, launch_date, discontinue_date)
     VALUES ('T_X2','x','TRADING','DISCONTINUED',DATE '2026-05-01',DATE '2026-01-01')$q$);
SELECT pg_temp.expect_ok('dim: set composition (set of 2 = 2 x bottle)',
  $q$INSERT INTO core.bridge_product_component (set_product_key, component_product_key, component_quantity, valid_from)
     SELECT s.product_key, c.product_key, 2, DATE '2026-04-01' FROM core.dim_product s, core.dim_product c
     WHERE s.sku_code='T_SET2' AND c.sku_code='T_GSTEA2724'$q$);
SELECT pg_temp.expect_fail('dim: a set cannot contain itself',
  $q$INSERT INTO core.bridge_product_component (set_product_key, component_product_key, component_quantity, valid_from)
     SELECT product_key, product_key, 1, DATE '2026-04-01' FROM core.dim_product WHERE sku_code='T_SET2'$q$);
SELECT pg_temp.expect_fail('dim: an order needs a channel order number or a WMS order number',
  $q$INSERT INTO core.dim_order (channel_key) SELECT channel_key FROM core.dim_channel WHERE channel_code='T_WEB'$q$);
SELECT pg_temp.expect_fail('dim: the same channel order number cannot be two orders',
  $q$INSERT INTO core.dim_order (channel_key, external_order_number) SELECT channel_key,'T-124118580' FROM core.dim_channel WHERE channel_code='T_WEB'$q$);
SELECT pg_temp.expect_ok('dim: product history versions',
  $q$INSERT INTO core.dim_product_history (product_key, lifecycle_status, mrp, valid_from, valid_to, is_current, batch_id)
     SELECT product_key,'CONTINUED',800,DATE '2026-04-01',DATE '2026-09-01',FALSE,(SELECT min(batch_id) FROM meta.load_batch) FROM core.dim_product WHERE sku_code='T_GSTEA2724';
     INSERT INTO core.dim_product_history (product_key, lifecycle_status, mrp, valid_from, valid_to, is_current, batch_id)
     SELECT product_key,'CONTINUED',850,DATE '2026-09-01',NULL,TRUE,(SELECT min(batch_id) FROM meta.load_batch) FROM core.dim_product WHERE sku_code='T_GSTEA2724'$q$);
SELECT pg_temp.expect_fail('dim: two current versions of one product rejected',
  $q$INSERT INTO core.dim_product_history (product_key, lifecycle_status, valid_from, is_current, batch_id)
     SELECT product_key,'DISCONTINUED',DATE '2026-09-10',TRUE,(SELECT min(batch_id) FROM meta.load_batch) FROM core.dim_product WHERE sku_code='T_GSTEA2724'$q$);
SELECT pg_temp.expect_true('dim: 18 movement types (16 + 2 unclassified), each adding or removing stock',
  $q$SELECT count(*) = 18 AND bool_and(stock_effect IN (-1,1)) FROM core.dim_movement_type$q$);

CREATE TEMP TABLE k AS SELECT
  (SELECT min(batch_id) FROM meta.load_batch) AS b,
  (SELECT product_key FROM core.dim_product WHERE sku_code='T_GSTEA2724') AS p,
  (SELECT location_key FROM core.dim_location WHERE location_code='T_WH') AS l_wh,
  (SELECT location_key FROM core.dim_location WHERE location_code='T_FBA') AS l_fba,
  (SELECT location_key FROM core.dim_location WHERE location_code='T_CONSIGN') AS l_con,
  (SELECT channel_key FROM core.dim_channel WHERE channel_code='T_WEB') AS c,
  (SELECT channel_key FROM core.dim_channel WHERE channel_code='T_QC') AS c_qc,
  (SELECT partner_key FROM core.dim_partner WHERE partner_name='T Shopify_Customer') AS pt,
  (SELECT partner_key FROM core.dim_partner WHERE partner_name='T KIRANAKART') AS pt_qc,
  (SELECT partner_key FROM core.dim_partner WHERE partner_name='T Factory') AS pt_f,
  (SELECT order_key FROM core.dim_order WHERE external_order_number='T-124118580') AS o,
  (SELECT courier_key FROM core.dim_courier WHERE courier_name='T Delhivery') AS cr;

-- ---------------------------------------------------------------- sales
SELECT pg_temp.expect_ok('sales: valid invoice line with order and net sales from source',
  $q$INSERT INTO core.fact_sales_line (source_name, bill_number, source_sku_code, bill_date_key, order_key, product_key, location_key,
       channel_key, partner_key, quantity, net_sales_amount, net_amount_method, tax_amount, batch_id, source_row_number)
     SELECT 'ERP_RETAIL_SALES','T-JPR26SP-S1','GSTEA2724',20260401,o,p,l_wh,c,pt,1,705.93,'SOURCE',127.07,b,1 FROM k$q$);
SELECT pg_temp.expect_ok('sales: B2B line with no order (order -1) and derived net amount',
  $q$INSERT INTO core.fact_sales_line (source_name, bill_number, source_sku_code, bill_date_key, order_key, product_key, location_key,
       channel_key, partner_key, quantity, net_sales_amount, net_amount_method, batch_id, source_row_number)
     SELECT 'ERP_DOMESTIC_SALES','T-WSL-1','GSTEA2724',20260401,-1,p,l_wh,c_qc,pt_qc,10,8000,'DERIVED',b,2 FROM k$q$);
SELECT pg_temp.expect_fail('sales: a net amount marked MISSING cannot carry a value',
  $q$INSERT INTO core.fact_sales_line (source_name, bill_number, source_sku_code, bill_date_key, order_key, product_key, location_key,
       channel_key, partner_key, quantity, net_sales_amount, net_amount_method, batch_id, source_row_number)
     SELECT 'ERP_RETAIL_SALES','T-Z1','GSTEA2724',20260401,o,p,l_wh,c,pt,1,100,'MISSING',b,3 FROM k$q$);
SELECT pg_temp.expect_fail('sales: a net amount from SOURCE cannot be empty',
  $q$INSERT INTO core.fact_sales_line (source_name, bill_number, source_sku_code, bill_date_key, order_key, product_key, location_key,
       channel_key, partner_key, quantity, net_amount_method, batch_id, source_row_number)
     SELECT 'ERP_RETAIL_SALES','T-Z2','GSTEA2724',20260401,o,p,l_wh,c,pt,1,'SOURCE',b,4 FROM k$q$);
SELECT pg_temp.expect_fail('sales: duplicate natural key rejected (double-load protection)',
  $q$INSERT INTO core.fact_sales_line (source_name, bill_number, source_sku_code, bill_date_key, order_key, product_key, location_key,
       channel_key, partner_key, quantity, net_sales_amount, net_amount_method, batch_id, source_row_number)
     SELECT 'ERP_RETAIL_SALES','T-JPR26SP-S1','GSTEA2724',20260401,o,p,l_wh,c,pt,1,705.93,'SOURCE',b,9 FROM k$q$);
SELECT pg_temp.expect_fail('sales: zero quantity rejected',
  $q$INSERT INTO core.fact_sales_line (source_name, bill_number, source_sku_code, bill_date_key, order_key, product_key, location_key,
       channel_key, partner_key, quantity, net_amount_method, batch_id, source_row_number)
     SELECT 'ERP_RETAIL_SALES','T-Z3','GSTEA2724',20260401,o,p,l_wh,c,pt,0,'MISSING',b,5 FROM k$q$);

-- ---------------------------------------------------------------- returns
SELECT pg_temp.expect_ok('returns: domestic credit note with two goods receipts on different dates',
  $q$INSERT INTO core.fact_return_line (source_name, return_number, source_sku_code, return_date_key, first_receipt_date_key,
       last_receipt_date_key, order_key, product_key, receiving_location_key, channel_key, partner_key, return_reason_key, quantity,
       net_return_amount, net_amount_method, batch_id, source_row_number)
     SELECT 'ERP_DOMESTIC_RETURN','T-WH/CN/712','GSTEA2724',20260415,20260402,20260410,-1,p,l_wh,c_qc,pt_qc,-1,4,3200,'SOURCE',b,1 FROM k;
     INSERT INTO core.bridge_return_goods_receipt SELECT return_line_id, 1, 'JPR/GIR/3923', DATE '2026-04-02' FROM core.fact_return_line WHERE return_number='T-WH/CN/712';
     INSERT INTO core.bridge_return_goods_receipt SELECT return_line_id, 2, 'JPR/GIR/5011', DATE '2026-04-10' FROM core.fact_return_line WHERE return_number='T-WH/CN/712'$q$);
SELECT pg_temp.expect_fail('returns: last receipt date before first receipt date rejected',
  $q$INSERT INTO core.fact_return_line (source_name, return_number, source_sku_code, return_date_key, first_receipt_date_key,
       last_receipt_date_key, order_key, product_key, receiving_location_key, channel_key, partner_key, return_reason_key, quantity,
       net_amount_method, batch_id, source_row_number)
     SELECT 'ERP_DOMESTIC_RETURN','T-R2','GSTEA2724',20260415,20260410,20260402,-1,p,l_wh,c_qc,pt_qc,-1,1,'MISSING',b,2 FROM k$q$);
SELECT pg_temp.expect_fail('returns: the same receipt position cannot appear twice on one return line',
  $q$INSERT INTO core.bridge_return_goods_receipt SELECT return_line_id, 1, 'JPR/GIR/9999', DATE '2026-04-03' FROM core.fact_return_line WHERE return_number='T-WH/CN/712'$q$);
SELECT pg_temp.expect_fail('returns: unknown return reason key rejected (FK)',
  $q$INSERT INTO core.fact_return_line (source_name, return_number, source_sku_code, return_date_key, order_key, product_key,
       receiving_location_key, channel_key, partner_key, return_reason_key, quantity, net_amount_method, batch_id, source_row_number)
     SELECT 'ERP_RETAIL_RETURN','T-R3','GSTEA2724',20260415,o,p,l_wh,c,pt,999,1,'MISSING',b,3 FROM k$q$);

-- ---------------------------------------------------------------- transfers, purchasing, receipts
SELECT pg_temp.expect_ok('transfer: OUT line and matching IN line',
  $q$INSERT INTO core.fact_stock_transfer_line (source_name, document_number, source_sku_code, movement_direction, document_date_key,
       from_location_key, to_location_key, product_key, quantity, batch_id, source_row_number)
     SELECT 'ERP_STOCK_TRANSFER_OUT','T-JPR/DC/1','GSTEA2724','OUT',20260405,l_wh,l_fba,p,10,b,1 FROM k;
     INSERT INTO core.fact_stock_transfer_line (source_name, document_number, source_sku_code, movement_direction, document_date_key,
       linked_outward_document, from_location_key, to_location_key, product_key, quantity, batch_id, source_row_number)
     SELECT 'ERP_STOCK_TRANSFER_IN','T-REC/1','GSTEA2724','IN',20260409,'T-JPR/DC/1',l_wh,l_fba,p,10,b,1 FROM k$q$);
SELECT pg_temp.expect_fail('transfer: direction must match source file',
  $q$INSERT INTO core.fact_stock_transfer_line (source_name, document_number, source_sku_code, movement_direction, document_date_key,
       from_location_key, to_location_key, product_key, quantity, batch_id, source_row_number)
     SELECT 'ERP_STOCK_TRANSFER_OUT','T-T2','GSTEA2724','IN',20260405,l_wh,l_fba,p,10,b,1 FROM k$q$);
SELECT pg_temp.expect_ok('purchasing: PO line and its receipt row as reported (three receipts, one date, one total)',
  $q$INSERT INTO core.fact_purchase_order_line (po_number, source_sku_code, po_date_key, due_date_key, partner_key, product_key, order_qty,
       received_qty, pending_qty, po_status, po_status_raw, as_of_date, batch_id, source_row_number)
     SELECT 'T-PO/1','GSTEA2724',20260401,20260420,pt_f,p,1000,749,251,'IN_PROGRESS','In Progress',DATE '2026-09-24',b,1 FROM k;
     INSERT INTO core.fact_goods_receipt_line (po_line_id, po_number, source_sku_code, line_occurrence, grn_date_key, receipt_count,
       partner_key, product_key, receiving_location_key, received_qty, batch_id, source_row_number)
     SELECT (SELECT po_line_id FROM core.fact_purchase_order_line WHERE po_number='T-PO/1'),'T-PO/1','GSTEA2724',1,20260805,3,pt_f,p,-1,749,b,1 FROM k;
     INSERT INTO core.bridge_goods_receipt_grn SELECT receipt_line_id, s, 'T-GRN/' || s FROM core.fact_goods_receipt_line, generate_series(1,3) s
     WHERE po_number = 'T-PO/1'$q$);
SELECT pg_temp.expect_fail('purchasing: one receipt row per PO line (a second one is rejected)',
  $q$INSERT INTO core.fact_goods_receipt_line (po_line_id, po_number, source_sku_code, line_occurrence, grn_date_key, receipt_count,
       partner_key, product_key, receiving_location_key, received_qty, batch_id, source_row_number)
     SELECT (SELECT po_line_id FROM core.fact_purchase_order_line WHERE po_number='T-PO/1'),'T-PO/1','GSTEA2724',1,20260806,1,pt_f,p,-1,10,b,2 FROM k$q$);
SELECT pg_temp.expect_fail('purchasing: a receipt of zero units rejected',
  $q$INSERT INTO core.fact_goods_receipt_line (po_line_id, po_number, source_sku_code, line_occurrence, grn_date_key, receipt_count,
       partner_key, product_key, receiving_location_key, received_qty, batch_id, source_row_number)
     SELECT (SELECT po_line_id FROM core.fact_purchase_order_line WHERE po_number='T-PO/1'),'T-PO/1','GSTEA2724',2,20260806,1,pt_f,p,-1,0,b,3 FROM k$q$);
SELECT pg_temp.expect_fail('purchasing: a receipt must belong to a PO line',
  $q$INSERT INTO core.fact_goods_receipt_line (po_number, source_sku_code, line_occurrence, grn_date_key, receipt_count,
       partner_key, product_key, receiving_location_key, received_qty, batch_id, source_row_number)
     SELECT 'T-PO/X','GSTEA2724',1,20260806,1,pt_f,p,-1,5,b,4 FROM k$q$);

-- ---------------------------------------------------------------- shipments, sell-out, inventory
SELECT pg_temp.expect_ok('shipment: linked to order and courier, multi-SKU bridge',
  $q$INSERT INTO core.fact_shipment (outbound_delivery_number, order_key, invoice_number, channel_key, fulfilment_location_key, courier_key,
       payment_type, shipment_status, shipment_status_raw, is_rto, order_datetime, order_date_key, batch_id, source_row_number)
     SELECT 'T-EWH000242328',o,'T-JPR26SP-S1',c,l_wh,cr,'COD','DELIVERED','delivered',FALSE,TIMESTAMP '2026-04-01 07:28',20260401,b,1 FROM k;
     INSERT INTO core.bridge_shipment_sku SELECT shipment_id,'GSTEA2724',(SELECT p FROM k),1,'INVOICE_LINE' FROM core.fact_shipment WHERE outbound_delivery_number='T-EWH000242328';
     INSERT INTO core.bridge_shipment_sku SELECT shipment_id,'WDSWA2926',-1,NULL,'UNALLOCATED' FROM core.fact_shipment WHERE outbound_delivery_number='T-EWH000242328'$q$);
SELECT pg_temp.expect_fail('shipment: UNALLOCATED bridge row cannot carry a guessed quantity',
  $q$INSERT INTO core.bridge_shipment_sku SELECT shipment_id,'XXXX',-1,1,'UNALLOCATED' FROM core.fact_shipment WHERE outbound_delivery_number='T-EWH000242328'$q$);
SELECT pg_temp.expect_ok('sell-out: Blinkit day / city / SKU with partner and location',
  $q$INSERT INTO core.fact_partner_sellout (source_name, order_date_key, platform_store_code, source_sku_code, channel_key, partner_key,
       location_key, product_key, city, units_sold, order_count, batch_id)
     SELECT 'BLINKIT_SALES',20260904,'Pune','GSTEA2724',c_qc,pt_qc,l_con,p,'Pune',3,3,b FROM k$q$);
SELECT pg_temp.expect_ok('inventory: negative ERP on-hand accepted (real, flagged by checks)',
  $q$INSERT INTO core.fact_inventory_snapshot (source_name, snapshot_date_key, source_location_value, source_sku_code, location_key, product_key, on_hand_qty, batch_id)
     SELECT 'ERP_INVENTORY_SNAPSHOT',20260915,'T 08 Jaipur Branch','GSTEA2724',l_wh,p,-3,b FROM k$q$);

-- ---------------------------------------------------------------- stock ledger
SELECT pg_temp.expect_ok('ledger: a transfer becomes two signed movements (out at warehouse, in at FBA)',
  $q$INSERT INTO core.fact_stock_movement (movement_date_key, location_key, product_key, movement_type_key, quantity,
       counterparty_location_key, partner_key, source_table, source_line_id)
     SELECT 20260405, l_wh, p, 8, -10, l_fba, -1, 'fact_stock_transfer_line', 1 FROM k
     UNION ALL SELECT 20260409, l_fba, p, 9, 10, l_wh, -1, 'fact_stock_transfer_line', 2 FROM k$q$);
SELECT pg_temp.expect_ok('ledger: consignment out to a sale-or-return partner and in at its location (BR-022)',
  $q$INSERT INTO core.fact_stock_movement (movement_date_key, location_key, product_key, movement_type_key, quantity,
       counterparty_location_key, partner_key, source_table, source_line_id)
     SELECT 20260401, l_wh, p, 3, -10, l_con, pt_qc, 'fact_sales_line', 2 FROM k
     UNION ALL SELECT 20260401, l_con, p, 4, 10, l_wh, pt_qc, 'fact_sales_line', 2 FROM k$q$);
SELECT pg_temp.expect_true('ledger: stock at the partner location = 10 sent - 0 sold, before sell-out is applied',
  $q$SELECT sum(quantity) = 10 FROM core.fact_stock_movement WHERE location_key = (SELECT l_con FROM k)$q$);
SELECT pg_temp.expect_fail('ledger: a zero movement rejected',
  $q$INSERT INTO core.fact_stock_movement (movement_date_key, location_key, product_key, movement_type_key, quantity, partner_key, source_table, source_line_id)
     SELECT 20260405, l_wh, p, 8, 0, -1, 'fact_stock_transfer_line', 3 FROM k$q$);
SELECT pg_temp.expect_fail('ledger: the same source line cannot create the same movement twice',
  $q$INSERT INTO core.fact_stock_movement (movement_date_key, location_key, product_key, movement_type_key, quantity, partner_key, source_table, source_line_id)
     SELECT 20260405, l_wh, p, 8, -10, -1, 'fact_stock_transfer_line', 1 FROM k$q$);
SELECT pg_temp.expect_fail('ledger: movements only come from known fact tables',
  $q$INSERT INTO core.fact_stock_movement (movement_date_key, location_key, product_key, movement_type_key, quantity, partner_key, source_table, source_line_id)
     SELECT 20260405, l_wh, p, 14, 5, -1, 'manual_spreadsheet', 1 FROM k$q$);

-- ---------------------------------------------------------------- agent outputs
SELECT pg_temp.expect_ok('insight: a run, its forecast and a transfer recommendation',
  $q$INSERT INTO insight.model_run (agent, run_type, model_name, model_version, data_as_of_date) VALUES ('STOCK','DEMAND_FORECAST','test','0.1',DATE '2026-09-15');
     INSERT INTO insight.demand_forecast SELECT max(run_id), (SELECT p FROM k), (SELECT l_fba FROM k), (SELECT c FROM k), 'WEEK', DATE '2026-09-21', 12, 8, 16 FROM insight.model_run;
     INSERT INTO insight.recommendation (run_id, recommendation_type, product_key, from_location_key, to_location_key, quantity, reason, rule_ids, priority)
     SELECT (SELECT max(run_id) FROM insight.model_run), 'TRANSFER', p, l_wh, l_fba, 12, 'Cover at FBA below 7 days', 'BR-025', 'HIGH' FROM k$q$);
SELECT pg_temp.expect_fail('insight: forecast outside its own range rejected',
  $q$INSERT INTO insight.demand_forecast SELECT max(run_id), (SELECT p FROM k), (SELECT l_wh FROM k), (SELECT c FROM k), 'WEEK', DATE '2026-09-28', 20, 8, 16 FROM insight.model_run$q$);
SELECT pg_temp.expect_fail('insight: an ACCEPTED recommendation must say who decided and when',
  $q$UPDATE insight.recommendation SET status = 'ACCEPTED' WHERE reason = 'Cover at FBA below 7 days'$q$);
SELECT pg_temp.expect_ok('insight: recording the human decision',
  $q$UPDATE insight.recommendation SET status = 'ACCEPTED', decided_by = 'ops lead', decided_at = TIMESTAMP '2026-09-16 10:00' WHERE reason = 'Cover at FBA below 7 days'$q$);
SELECT pg_temp.expect_fail('insight: a TRANSFER recommendation needs both locations',
  $q$INSERT INTO insight.recommendation (run_id, recommendation_type, product_key, quantity, reason, priority)
     SELECT (SELECT max(run_id) FROM insight.model_run), 'TRANSFER', p, 5, 'x', 'LOW' FROM k$q$);
SELECT pg_temp.expect_fail('insight: a finished run must be marked finished (and vice versa)',
  $q$INSERT INTO insight.model_run (agent, run_type, model_name, model_version, data_as_of_date, status) VALUES ('STOCK','X','t','1',DATE '2026-09-15','SUCCEEDED')$q$);

-- ---------------------------------------------------------------- report
DO $$
DECLARE n_fail INT; n_total INT; r RECORD;
BEGIN
    FOR r IN SELECT * FROM test_result ORDER BY passed, test_name LOOP
        RAISE NOTICE '% | %', CASE WHEN r.passed THEN 'PASS' ELSE 'FAIL' END, r.test_name
            || CASE WHEN r.passed THEN '' ELSE '  -->  ' || r.detail END;
    END LOOP;
    SELECT count(*) FILTER (WHERE NOT passed), count(*) INTO n_fail, n_total FROM test_result;
    RAISE NOTICE '---- % of % tests passed ----', n_total - n_fail, n_total;
    IF n_fail > 0 THEN RAISE EXCEPTION '% schema test(s) FAILED', n_fail; END IF;
END $$;

ROLLBACK;
