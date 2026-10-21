-- =============================================================================
-- 11  Staging: stock transfers, purchase orders, platform sell-out, stock snapshots.
-- =============================================================================

DROP TABLE IF EXISTS stg.transfer_out;
CREATE TABLE stg.transfer_out AS
WITH src AS (
    SELECT r.*, max(r.batch_id) OVER (PARTITION BY btrim(r.docnum)) AS latest_batch
    FROM raw.erp_stock_transfer_out r JOIN meta.load_batch b ON b.batch_id = r.batch_id AND b.status = 'LOADED')
SELECT s.batch_id, s.source_row_number, btrim(s.docnum) AS document_number, stg.doc_prefix(s.docnum) AS doc_prefix,
       s.prodnum AS source_sku_code, stg.sku(s.prodnum) AS sku_code,
       row_number() OVER (PARTITION BY s.batch_id, btrim(s.docnum), stg.sku(s.prodnum) ORDER BY s.source_row_number) AS line_occurrence,
       stg.ts(s.docopendate)::DATE AS document_date, btrim(s.contactname) AS contact_name,
       abs(stg.num(s.prodtransqty)) AS quantity, stg.num(s.rate) AS unit_rate, abs(stg.num(s.prodtransvalue)) AS transfer_value,
       nullif(btrim(s.docstatusname), '') AS document_status, s.prodname AS product_name, nullif(btrim(s.prodtypename), '') AS product_type,
       s.docopendate AS document_date_raw
FROM src s WHERE s.batch_id = s.latest_batch;

DROP TABLE IF EXISTS stg.transfer_in;
CREATE TABLE stg.transfer_in AS
WITH src AS (
    SELECT r.*, max(r.batch_id) OVER (PARTITION BY btrim(r.docnum)) AS latest_batch
    FROM raw.erp_stock_transfer_in r JOIN meta.load_batch b ON b.batch_id = r.batch_id AND b.status = 'LOADED')
SELECT s.batch_id, s.source_row_number, btrim(s.docnum) AS document_number,
       s.prodnum AS source_sku_code, stg.sku(s.prodnum) AS sku_code,
       row_number() OVER (PARTITION BY s.batch_id, btrim(s.docnum), stg.sku(s.prodnum) ORDER BY s.source_row_number) AS line_occurrence,
       stg.ts(s.docopendate)::DATE AS document_date, nullif(btrim(s.refdocnum1), '') AS linked_outward_document,
       btrim(s.contactname) AS contact_name,
       abs(stg.num(s.prodtransqty)) AS quantity, stg.num(s.rate) AS unit_rate, abs(stg.num(s.prodtransvalue)) AS transfer_value,
       nullif(btrim(s.docstatusname), '') AS document_status, s.prodname AS product_name, nullif(btrim(s.prodtypename), '') AS product_type,
       s.docopendate AS document_date_raw
FROM src s WHERE s.batch_id = s.latest_batch;

-- PO report is a state snapshot: only the latest export (by as-of date) is current.
DROP TABLE IF EXISTS stg.purchase_order;
CREATE TABLE stg.purchase_order AS
WITH b AS (SELECT batch_id, as_of_date FROM meta.load_batch
           WHERE source_name = 'ERP_PURCHASE_ORDER' AND status = 'LOADED' ORDER BY as_of_date DESC, batch_id DESC LIMIT 1)
SELECT r.batch_id, r.source_row_number, b.as_of_date,
       btrim(r.po_no) AS po_number, r.sku_no AS source_sku_code, stg.sku(r.sku_no) AS sku_code,
       row_number() OVER (PARTITION BY btrim(r.po_no), stg.sku(r.sku_no) ORDER BY r.source_row_number) AS line_occurrence,
       stg.ts(r.po_open_date)::DATE AS po_date, stg.ts(r.po_due_date)::DATE AS due_date,
       btrim(r.contactname) AS contact_name, nullif(btrim(r.prodtypename), '') AS product_type,
       nullif(btrim(r.category), '') AS category, nullif(btrim(r.sub_category), '') AS sub_category,
       r.product_description AS product_name, nullif(btrim(r.uom), '') AS uom,
       stg.num(r.order_qty) AS order_qty, stg.num(r.grn_qty) AS received_qty, stg.num(r.returned_qty) AS returned_qty,
       stg.num(r.po_pending_qty) AS pending_qty, stg.num(r.purchase_price) AS purchase_price,
       stg.num(r.purchase_amount) AS purchase_amount, stg.num(r.returned_value) AS returned_value,
       btrim(r.status) AS po_status_raw, nullif(btrim(r.currencycode), '') AS currency_code,
       nullif(btrim(r.grnnum), '') AS grn_number, stg.ts(r.grndocopendate)::DATE AS grn_date,
       r.po_open_date AS po_date_raw
FROM raw.erp_purchase_order r JOIN b ON b.batch_id = r.batch_id;

DROP TABLE IF EXISTS stg.blinkit_sales;
CREATE TABLE stg.blinkit_sales AS
WITH src AS (
    SELECT r.*, max(r.batch_id) OVER (PARTITION BY btrim(r.order_id), btrim(r.item_id)) AS latest_batch
    FROM raw.blinkit_sales r JOIN meta.load_batch b ON b.batch_id = r.batch_id AND b.status = 'LOADED')
SELECT s.batch_id, s.source_row_number, btrim(s.order_id) AS order_id, btrim(s.item_id) AS item_id,
       s.elle_sku AS source_sku_code, stg.sku(s.elle_sku) AS sku_code,
       stg.any_date(s.order_date) AS order_date, stg.sku(s.order_status) AS order_status,
       nullif(btrim(s.supply_city), '') AS supply_city,
       stg.num(s.quantity) AS quantity, stg.num(s.mrp_rs) AS unit_mrp,
       stg.num(s.total_gross_bill_amount) AS selling_value,               -- = quantity x selling price (verified)
       stg.num(s.total_tax) AS tax_amount, nullif(btrim(s.upc), '') AS ean_code, s.product_name
FROM src s WHERE s.batch_id = s.latest_batch;

DROP TABLE IF EXISTS stg.instamart_sales;
CREATE TABLE stg.instamart_sales AS
WITH src AS (
    SELECT r.*, max(r.batch_id) OVER (PARTITION BY stg.any_date(r.ordered_date)) AS latest_batch
    FROM raw.instamart_sales r JOIN meta.load_batch b ON b.batch_id = r.batch_id AND b.status = 'LOADED')
SELECT s.batch_id, s.source_row_number, stg.any_date(s.ordered_date) AS order_date, btrim(s.store_id) AS store_id,
       nullif(btrim(s.city), '') AS city, btrim(s.item_code) AS item_id,
       s.elle_sku AS source_sku_code, stg.sku(s.elle_sku) AS sku_code,
       stg.num(s.units_sold) AS units_sold, stg.num(s.combo_units_sold) AS combo_units_sold,
       stg.num(s.base_mrp) AS unit_mrp, stg.num(s.gmv) AS gmv, s.product_name
FROM src s WHERE s.batch_id = s.latest_batch;

-- Stock snapshots: per source and as-of date, the latest batch wins.
DROP TABLE IF EXISTS stg.inventory_snapshot;
CREATE TABLE stg.inventory_snapshot AS
WITH b AS (SELECT DISTINCT ON (source_name, as_of_date) source_name, batch_id, as_of_date FROM meta.load_batch
           WHERE source_name IN ('ERP_INVENTORY_SNAPSHOT','BLINKIT_INVENTORY','INSTAMART_INVENTORY') AND status = 'LOADED'
           ORDER BY source_name, as_of_date, batch_id DESC)
SELECT 'ERP_INVENTORY_SNAPSHOT'::VARCHAR(60) AS source_name, r.batch_id, b.as_of_date AS snapshot_date,
       btrim(r.location_header) AS location_value, r.prod_num AS source_sku_code, stg.sku(r.prod_num) AS sku_code,
       stg.num(r.qty) AS on_hand_qty, NULL::NUMERIC AS sellable_qty, NULL::NUMERIC AS unsellable_qty, NULL::NUMERIC AS in_transit_qty,
       NULL::NUMERIC AS incoming_qty, NULL::NUMERIC AS damaged_qty, NULL::NUMERIC AS lost_qty, NULL::NUMERIC AS expired_qty,
       NULL::NUMERIC AS recalled_qty, NULL::NUMERIC AS net_scheduled_qty, stg.num(r.active_mrp) AS unit_mrp,
       r.prod_name AS product_name, nullif(btrim(r.prod_type), '') AS product_type, nullif(btrim(r.unit), '') AS uom,
       nullif(btrim(r.prod_category), '') AS category, r.qty AS on_hand_raw
FROM raw.erp_inventory_snapshot r JOIN b ON b.batch_id = r.batch_id
UNION ALL
SELECT 'BLINKIT_INVENTORY', r.batch_id, b.as_of_date, btrim(r.warehouse_facility_name), r.sku, stg.sku(r.sku),
       coalesce(stg.num(r.total_sellable), 0) + coalesce(stg.num(r.total_unsellable), 0),
       stg.num(r.total_sellable),                 -- = warehouse + in-between + darkstore (verified)
       stg.num(r.total_unsellable), stg.num(r.in_between), stg.num(r.incoming_scheduled_inventory),
       stg.num(r.damaged), stg.num(r.lost), stg.num(r.expired), stg.num(r.recalled_inventory),
       stg.num(r.net_scheduled_inventory), NULL, r.item_name, NULL, NULL, NULL, r.total_sellable
FROM raw.blinkit_inventory r JOIN b ON b.batch_id = r.batch_id
UNION ALL
SELECT 'INSTAMART_INVENTORY', r.batch_id, b.as_of_date, btrim(r.facilityname), r.elle_sku, stg.sku(r.elle_sku),
       stg.num(r.warehouseqtyavailable), stg.num(r.warehouseqtyavailable), NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
       r.skudescription, NULL, NULL, NULL, r.warehouseqtyavailable
FROM raw.instamart_inventory r JOIN b ON b.batch_id = r.batch_id;
