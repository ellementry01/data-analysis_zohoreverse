-- =============================================================================
-- 10  Staging: sales and returns. Typed, trimmed, one-to-one with source.
-- Only LOADED batches are read. If a document appears in more than one batch
-- (a re-export), the LATEST batch holding it wins, whole document at once.
-- No business rules here except parsing; rules are applied in 30_facts.
-- =============================================================================

DROP TABLE IF EXISTS stg.retail_sales;
CREATE TABLE stg.retail_sales AS
WITH src AS (
    SELECT r.*, max(r.batch_id) OVER (PARTITION BY btrim(r.billnum)) AS latest_batch
    FROM raw.erp_retail_sales r JOIN meta.load_batch b ON b.batch_id = r.batch_id AND b.status = 'LOADED')
SELECT s.batch_id, s.source_row_number,
       btrim(s.billnum)                                  AS bill_number,
       s.prodnum                                         AS source_sku_code,
       stg.sku(s.prodnum)                           AS sku_code,
       row_number() OVER (PARTITION BY s.batch_id, btrim(s.billnum), stg.sku(s.prodnum) ORDER BY s.source_row_number) AS line_occurrence,
       stg.ts(s.billdate)                                AS bill_datetime,
       stg.ts(s.billdate)::DATE                          AS bill_date,
       CASE WHEN ph.source_value IS NULL THEN nullif(btrim(s.order_number), '') END AS order_number,
       stg.ts(s.order_date)::DATE                        AS order_date,
       btrim(s.channelname)                              AS location_value,
       btrim(s.contactname)                              AS contact_name,
       s.payment_mode_account                            AS payment_mode_raw,
       nullif(btrim(s.courier), '')                      AS courier_name,
       nullif(btrim(s.shipping_pincode), '')             AS ship_to_pincode,
       nullif(btrim(s.ship_to_city), '')                 AS ship_to_city,
       nullif(btrim(s.docdestcontactaddressstatecode), '') AS ship_to_state_code,
       stg.num(s.prodcontactqty)                         AS quantity,
       stg.num(s.prodcontactrate)                        AS unit_rate,
       stg.num(s.prodmrp)                                AS unit_mrp,
       stg.num(s.prodbeforedisc)                         AS gross_amount,
       stg.num(s.proddisc)                               AS discount_amount,
       coalesce(stg.num(s.igst_amount), 0) + coalesce(stg.num(s.cgst_amount), 0)
         + coalesce(stg.num(s.sgst_amount), 0) + coalesce(stg.num(s.cess_amount), 0) AS tax_amount,
       stg.num(s.proddocvalue)                           AS doc_value,           -- excl. GST (BR-002)
       stg.num(s.prodassessablevalue)                    AS assessable_value,    -- INCL. GST (BR-002)
       stg.num(s.cost_rate)                              AS unit_cost,
       s.prodname                                        AS product_name,
       nullif(btrim(s.prodcategoryname), '')             AS category,
       nullif(btrim(s.prodfamilyname), '')               AS product_family,
       nullif(btrim(s.prodhsncode), '')                  AS hsn_code,
       nullif(btrim(s.uomname), '')                      AS uom,
       s.billdate AS bill_date_raw, s.prodcontactqty AS quantity_raw,
       nullif(btrim(s.awb), '') AS awb                   -- courier AWB: links WMS shipments (2.5)
FROM src s
LEFT JOIN ref.code_mapping ph ON ph.domain = 'ORDER_NUMBER_PLACEHOLDER' AND ph.source_name = 'ERP_RETAIL_SALES'
                             AND ph.source_value = btrim(s.order_number)
WHERE s.batch_id = s.latest_batch;

DROP TABLE IF EXISTS stg.domestic_sales;
CREATE TABLE stg.domestic_sales AS
WITH src AS (
    SELECT r.*, max(r.batch_id) OVER (PARTITION BY btrim(r.billnum)) AS latest_batch
    FROM raw.erp_domestic_sales r JOIN meta.load_batch b ON b.batch_id = r.batch_id AND b.status = 'LOADED')
SELECT s.batch_id, s.source_row_number,
       btrim(s.billnum) AS bill_number, s.prodnum AS source_sku_code, stg.sku(s.prodnum) AS sku_code,
       row_number() OVER (PARTITION BY s.batch_id, btrim(s.billnum), stg.sku(s.prodnum) ORDER BY s.source_row_number) AS line_occurrence,
       stg.ts(s.billdatetime) AS bill_datetime, stg.ts(s.billdatetime)::DATE AS bill_date,
       btrim(s.channelname) AS location_value, btrim(s.contactname) AS contact_name,
       nullif(btrim(s.shippostalcode), '') AS ship_to_pincode, nullif(btrim(s.shipcity), '') AS ship_to_city,
       stg.num(s.quantity) AS quantity, stg.num(s.price) AS unit_rate, stg.num(s.mrp) AS unit_mrp,
       stg.num(s.prodbeforedisc) AS gross_amount, stg.num(s.proddisc) AS discount_amount,
       stg.num(s.taxable) AS taxable,                                   -- excl. GST (BR-003)
       stg.num(s.net_amount) AS net_amount,                             -- INCL. GST (BR-003)
       coalesce(stg.num(s.total_tax), coalesce(stg.num(s.igstamount), 0) + coalesce(stg.num(s.cgstamount), 0)
                + coalesce(stg.num(s.sgstamount), 0)) AS tax_amount,
       s.prodname AS product_name, nullif(btrim(s.prodhsncode), '') AS hsn_code, nullif(btrim(s.uomname), '') AS uom,
       s.billdatetime AS bill_date_raw, s.quantity AS quantity_raw,
       nullif(btrim(s.docrefnum), '') AS order_reference, nullif(btrim(s.awbno), '') AS awb   -- link WMS shipments (2.5)
FROM src s WHERE s.batch_id = s.latest_batch;

DROP TABLE IF EXISTS stg.retail_return;
CREATE TABLE stg.retail_return AS
WITH src AS (
    SELECT r.*, max(r.batch_id) OVER (PARTITION BY btrim(r.returnnum)) AS latest_batch
    FROM raw.erp_retail_return r JOIN meta.load_batch b ON b.batch_id = r.batch_id AND b.status = 'LOADED')
SELECT s.batch_id, s.source_row_number,
       btrim(s.returnnum) AS return_number, s.prodnum AS source_sku_code, stg.sku(s.prodnum) AS sku_code,
       row_number() OVER (PARTITION BY s.batch_id, btrim(s.returnnum), stg.sku(s.prodnum) ORDER BY s.source_row_number) AS line_occurrence,
       stg.ts(s.returndate)::DATE AS return_date,
       nullif(btrim(s.billnum), '') AS original_bill_number, nullif(btrim(s.docrefnum), '') AS order_number,
       btrim(s.contactname) AS contact_name,
       stg.num(s.prodcontactqty) AS quantity, stg.num(s.prodcontactrate) AS unit_rate, stg.num(s.proddisc) AS discount_amount,
       coalesce(stg.num(s.igstamount), 0) + coalesce(stg.num(s.cgstamount), 0) + coalesce(stg.num(s.sgstamount), 0) AS tax_amount,
       stg.num(s.proddocvalue) AS doc_value, stg.num(s.prodassessablevalue) AS assessable_value, s.prodname AS product_name,
       s.returndate AS return_date_raw
FROM src s WHERE s.batch_id = s.latest_batch;

DROP TABLE IF EXISTS stg.domestic_return;
CREATE TABLE stg.domestic_return AS
WITH src AS (
    SELECT r.*, max(r.batch_id) OVER (PARTITION BY btrim(r.billnum)) AS latest_batch
    FROM raw.erp_domestic_return r JOIN meta.load_batch b ON b.batch_id = r.batch_id AND b.status = 'LOADED')
SELECT s.batch_id, s.source_row_number,
       btrim(s.billnum) AS return_number, s.prodnum AS source_sku_code, stg.sku(s.prodnum) AS sku_code,
       row_number() OVER (PARTITION BY s.batch_id, btrim(s.billnum), stg.sku(s.prodnum) ORDER BY s.source_row_number) AS line_occurrence,
       stg.ts(s.billdate)::DATE AS return_date,                          -- credit-note date (BR-023)
       nullif(btrim(s.docrefnum), '') AS original_bill_number,
       s.rtnfromcust AS receipt_numbers_raw, s.rtnfromcustdt AS receipt_dates_raw,
       btrim(s.channelname) AS location_value, btrim(s.contactname) AS contact_name,
       stg.num(s.prodcontactqty) AS quantity, stg.num(s.prodcontactrate) AS unit_rate, stg.num(s.proddisc) AS discount_amount,
       coalesce(stg.num(s.igstamount), 0) + coalesce(stg.num(s.cgstamount), 0) + coalesce(stg.num(s.sgstamount), 0) AS tax_amount,
       stg.num(s.proddocvalue) AS doc_value, stg.num(s.prodassessablevalue) AS assessable_value, s.prodname AS product_name,
       s.billdate AS return_date_raw
FROM src s WHERE s.batch_id = s.latest_batch;

-- One row per goods receipt of a credit-note line: numbers and dates are ';'-lists paired by position.
-- A single date for several receipts applies to all of them; any other mismatch leaves the date NULL (DQ check).
DROP TABLE IF EXISTS stg.domestic_return_receipt;
CREATE TABLE stg.domestic_return_receipt AS
WITH n AS (
    SELECT batch_id, source_row_number,
           string_to_array(receipt_numbers_raw, ';') AS nums,
           string_to_array(coalesce(receipt_dates_raw, ''), ';') AS dts
    FROM stg.domestic_return WHERE nullif(btrim(receipt_numbers_raw), '') IS NOT NULL)
SELECT n.batch_id, n.source_row_number, u.seq::SMALLINT AS receipt_seq, btrim(u.num) AS goods_receipt_number,
       CASE WHEN cardinality(n.dts) = cardinality(n.nums) THEN stg.any_date(n.dts[u.seq])
            WHEN cardinality(n.dts) = 1 THEN stg.any_date(n.dts[1]) END AS goods_receipt_date,
       cardinality(n.nums) AS n_receipts, cardinality(n.dts) AS n_dates
FROM n CROSS JOIN LATERAL unnest(n.nums) WITH ORDINALITY AS u(num, seq)
WHERE btrim(u.num) <> '';
