-- =============================================================================
-- 12  Staging: WMS dispatch (order fulfilment from Bagru, BR-017). Typed, one row per outbound delivery.
-- If a delivery appears in more than one batch (a re-export), the LATEST batch holding it wins.
-- Customer name, address, phone and e-mail stay in raw: they are never carried beyond it (personal data).
-- =============================================================================

DROP TABLE IF EXISTS stg.wms_dispatch;
CREATE TABLE stg.wms_dispatch AS
WITH src AS (
    SELECT r.*, max(r.batch_id) OVER (PARTITION BY btrim(r.outbound_delivery_no)) AS latest_batch
    FROM raw.wms_dispatch r JOIN meta.load_batch b ON b.batch_id = r.batch_id AND b.status = 'LOADED')
SELECT s.batch_id, s.source_row_number,
       btrim(s.outbound_delivery_no)                              AS outbound_delivery_number,
       nullif(btrim(s.order_no), '')                              AS wms_order_number,
       nullif(btrim(s.extern_order_no), '')                       AS external_order_number,
       nullif(btrim(s.invoice_no), '')                            AS invoice_number,
       btrim(s.site_location)                                     AS site_location,
       btrim(s.order_serving_location)                            AS serving_location,
       btrim(s.order_type)                                        AS order_type_raw,
       btrim(s.status)                                            AS status_raw,
       coalesce(nullif(btrim(s.transporter), ''), nullif(btrim(s.ext_transporter_name), '')) AS courier_name,
       nullif(btrim(s.tracking_no), '')                           AS tracking_number,
       nullif(btrim(s.transporter_status), '')                    AS transporter_status,
       left(nullif(btrim(s.transporter_remarks), ''), 300)        AS transporter_remarks,
       btrim(s.onhold) = '1'                                      AS is_on_hold,
       stg.ts(s.order_date)                                       AS order_datetime,
       stg.ts(s.order_date)::DATE                                 AS order_date,
       stg.ts(s.pick_date)                                        AS pick_datetime,
       stg.ts(s.pack_date)                                        AS pack_datetime,
       stg.ts(s.ship_date)                                        AS ship_datetime,
       stg.ts(s.delivery_date)                                    AS delivery_datetime,
       stg.ts(s.ship_by_date)                                     AS ship_by_datetime,
       stg.num(s.delivery_qty)                                    AS delivery_qty,
       stg.num(s.no_of_boxes)::SMALLINT                           AS box_count,
       stg.num(s.weight)                                          AS weight_kg,
       nullif(btrim(s.customer_pincode), '')                      AS destination_pincode,
       s.sku                                                      AS sku_cell,
       s.order_date                                               AS order_date_raw
FROM src s WHERE s.batch_id = s.latest_batch;
