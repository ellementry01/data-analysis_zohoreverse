-- =============================================================================
-- 20  Dimensions. Upserted by natural key so keys stay stable between runs.
-- Rows are never deleted (history and agent outputs point at them).
-- =============================================================================

-- --------------------------------------------------------------------- channel
INSERT INTO core.dim_channel (channel_code, channel_name, sub_channel_name, channel_group, fulfilment_model, is_sale_or_return, is_active, is_confirmed)
SELECT channel_code, channel_name, sub_channel_name, channel_group, fulfilment_model, is_sale_or_return, is_active, is_confirmed
FROM ref.channel_master
ON CONFLICT (channel_code) DO UPDATE SET channel_name = EXCLUDED.channel_name, sub_channel_name = EXCLUDED.sub_channel_name,
    channel_group = EXCLUDED.channel_group, fulfilment_model = EXCLUDED.fulfilment_model,
    is_sale_or_return = EXCLUDED.is_sale_or_return, is_active = EXCLUDED.is_active, is_confirmed = EXCLUDED.is_confirmed;
UPDATE core.dim_channel SET is_active = FALSE
WHERE NOT is_unknown_member AND channel_code NOT IN (SELECT channel_code FROM ref.channel_master);

-- --------------------------------------------------------------------- partner
-- Every counterparty name seen, with the sources it was seen in.
CREATE TEMP TABLE seen_partner ON COMMIT DROP AS
SELECT DISTINCT contact_name AS partner_name, 'CUSTOMER'::VARCHAR(10) AS partner_role, 'ERP_RETAIL_SALES'::VARCHAR(60) AS source_name FROM stg.retail_sales WHERE contact_name IS NOT NULL
UNION SELECT DISTINCT contact_name, 'CUSTOMER', 'ERP_RETAIL_RETURN'   FROM stg.retail_return   WHERE contact_name IS NOT NULL
UNION SELECT DISTINCT contact_name, 'CUSTOMER', 'ERP_DOMESTIC_SALES'  FROM stg.domestic_sales  WHERE contact_name IS NOT NULL
UNION SELECT DISTINCT contact_name, 'CUSTOMER', 'ERP_DOMESTIC_RETURN' FROM stg.domestic_return WHERE contact_name IS NOT NULL
UNION SELECT DISTINCT contact_name, 'SUPPLIER', 'ERP_PURCHASE_ORDER'  FROM stg.purchase_order  WHERE contact_name IS NOT NULL;

-- Classification: listed name > default rule of the source. Retail defaults are business-confirmed
-- (BR-005, BR-009) and always apply. Elimination rules (domestic BR-011, PO BR-013) apply ONLY when
-- the business has confirmed the partner list is complete; until then the name stays UNCLASSIFIED.
CREATE TEMP TABLE partner_class ON COMMIT DROP AS
WITH names AS (SELECT partner_name, partner_role FROM seen_partner UNION SELECT partner_name, partner_role FROM ref.partner_list),
dflt AS (
    SELECT s.partner_name, s.partner_role, d.default_partner_type, d.rule_id,
           CASE WHEN s.source_name IN ('ERP_RETAIL_SALES','ERP_RETAIL_RETURN') THEN 1 ELSE 2 END AS prio
    FROM seen_partner s JOIN ref.partner_default_rule d ON d.source_name = s.source_name
    WHERE s.source_name IN ('ERP_RETAIL_SALES','ERP_RETAIL_RETURN') OR (SELECT partner_list_complete FROM ctx)),
best AS (SELECT DISTINCT ON (partner_name, partner_role) * FROM dflt ORDER BY partner_name, partner_role, prio)
SELECT n.partner_name, n.partner_role,
       coalesce(l.partner_type, b.default_partner_type, 'UNCLASSIFIED') AS partner_type,
       l.partner_group, l.channel_code AS listed_channel_code,
       CASE WHEN l.partner_name IS NOT NULL THEN 'LISTED' WHEN b.partner_name IS NOT NULL THEN 'DEFAULT_RULE' ELSE 'UNKNOWN' END AS method,
       coalesce(l.rule_id, b.rule_id) AS rule_id,
       coalesce(l.is_confirmed, b.partner_name IS NOT NULL) AS is_confirmed
FROM names n
LEFT JOIN ref.partner_list l ON l.partner_name = n.partner_name AND l.partner_role = n.partner_role
LEFT JOIN best b ON b.partner_name = n.partner_name AND b.partner_role = n.partner_role;

INSERT INTO core.dim_partner (partner_name, partner_role, partner_type, partner_group, is_internal, is_related_party,
    is_sale_or_return, default_channel_key, classification_method, classification_rule_id, is_confirmed)
SELECT pc.partner_name, pc.partner_role, pc.partner_type, pc.partner_group, pt.is_internal, pt.is_related_party,
       pt.is_sale_or_return, ch.channel_key, pc.method, pc.rule_id, pc.is_confirmed
FROM partner_class pc
JOIN ref.partner_type pt ON pt.partner_type = pc.partner_type
LEFT JOIN ref.partner_type_channel ptc ON ptc.partner_type = pc.partner_type
LEFT JOIN core.dim_channel ch ON ch.channel_code = coalesce(pc.listed_channel_code, ptc.channel_code)
ON CONFLICT (partner_name, partner_role) DO UPDATE SET partner_type = EXCLUDED.partner_type, partner_group = EXCLUDED.partner_group,
    is_internal = EXCLUDED.is_internal, is_related_party = EXCLUDED.is_related_party, is_sale_or_return = EXCLUDED.is_sale_or_return,
    default_channel_key = EXCLUDED.default_channel_key, classification_method = EXCLUDED.classification_method,
    classification_rule_id = EXCLUDED.classification_rule_id, is_confirmed = EXCLUDED.is_confirmed;

-- --------------------------------------------------------------------- location
INSERT INTO core.dim_location (location_code, erp_location_name, location_name, location_type, operated_by, partner_key,
    gst_state_code, state_name, city, is_stock_holding, is_sellable_stock, inventory_system_of_record,
    opening_date, closing_date, is_active, is_confirmed, rule_id)
SELECT lm.location_code, lm.erp_location_name, lm.location_name, lm.location_type, lm.operated_by,
       (SELECT min(dp.partner_key) FROM ref.partner_list pl
          JOIN core.dim_partner dp ON dp.partner_name = pl.partner_name AND dp.partner_role = pl.partner_role
         WHERE pl.consignment_location_code = lm.location_code),
       lm.gst_state_code, gs.state_name, lm.city, lm.is_stock_holding, lm.is_sellable_stock, lm.inventory_system_of_record,
       lm.opening_date, lm.closing_date, lm.is_active, lm.is_confirmed, lm.rule_id
FROM ref.location_master lm LEFT JOIN ref.gst_state gs ON gs.gst_state_code = lm.gst_state_code
ON CONFLICT (location_code) DO UPDATE SET erp_location_name = EXCLUDED.erp_location_name, location_name = EXCLUDED.location_name,
    location_type = EXCLUDED.location_type, operated_by = EXCLUDED.operated_by, partner_key = EXCLUDED.partner_key,
    gst_state_code = EXCLUDED.gst_state_code, state_name = EXCLUDED.state_name, city = EXCLUDED.city,
    is_stock_holding = EXCLUDED.is_stock_holding, is_sellable_stock = EXCLUDED.is_sellable_stock,
    inventory_system_of_record = EXCLUDED.inventory_system_of_record, opening_date = EXCLUDED.opening_date,
    closing_date = EXCLUDED.closing_date, is_active = EXCLUDED.is_active, is_confirmed = EXCLUDED.is_confirmed, rule_id = EXCLUDED.rule_id;

-- --------------------------------------------------------------------- product
-- Every item code from every source, with each attribute taken from the most authoritative source holding it.
CREATE TEMP TABLE product_src ON COMMIT DROP AS
SELECT sku_code, prio, product_name, product_type, category, sub_category, product_family, hsn_code, uom, ean_code, mrp, seen_date FROM (
    SELECT stg.sku(m.prod_num) sku_code, 1 prio, m.prod_name product_name, nullif(btrim(m.prod_type),'') product_type, NULL category,
           NULL sub_category, NULL product_family, NULL hsn_code, nullif(btrim(m.unit),'') uom, NULL ean_code, NULL::NUMERIC mrp, NULL::DATE seen_date
    FROM raw.product_master m
    WHERE m.batch_id = (SELECT batch_id FROM meta.load_batch WHERE source_name='PRODUCT_MASTER' AND status='LOADED' ORDER BY as_of_date DESC, batch_id DESC LIMIT 1)
    UNION ALL SELECT sku_code, 2, product_name, product_type, category, NULL, NULL, NULL, uom, NULL, NULL, snapshot_date
    FROM stg.inventory_snapshot WHERE source_name = 'ERP_INVENTORY_SNAPSHOT'
    UNION ALL SELECT sku_code, 3, product_name, NULL, category, NULL, product_family, hsn_code, uom, NULL, unit_mrp, bill_date FROM stg.retail_sales
    UNION ALL SELECT sku_code, 4, product_name, NULL, NULL, NULL, NULL, hsn_code, uom, NULL, unit_mrp, bill_date FROM stg.domestic_sales
    UNION ALL SELECT sku_code, 5, product_name, product_type, category, sub_category, NULL, NULL, uom, NULL, NULL, po_date FROM stg.purchase_order
    UNION ALL SELECT sku_code, 6, product_name, product_type, NULL, NULL, NULL, NULL, NULL, NULL, NULL, document_date FROM stg.transfer_out
    UNION ALL SELECT sku_code, 6, product_name, product_type, NULL, NULL, NULL, NULL, NULL, NULL, NULL, document_date FROM stg.transfer_in
    UNION ALL SELECT sku_code, 7, product_name, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, return_date FROM stg.retail_return
    UNION ALL SELECT sku_code, 7, product_name, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, return_date FROM stg.domestic_return
    UNION ALL SELECT sku_code, 8, product_name, NULL, NULL, NULL, NULL, NULL, NULL, ean_code, unit_mrp, order_date FROM stg.blinkit_sales
    UNION ALL SELECT sku_code, 8, product_name, NULL, NULL, NULL, NULL, NULL, NULL, NULL, unit_mrp, order_date FROM stg.instamart_sales
    UNION ALL SELECT sku_code, 8, product_name, NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL, snapshot_date FROM stg.inventory_snapshot
    WHERE source_name <> 'ERP_INVENTORY_SNAPSHOT'
    -- ERP item master last: it only fills what no transaction or master source above holds (mainly category)
    UNION ALL SELECT sku_code, 9, product_name, product_type, category, sub_category, NULL, hsn_code, uom, ean_code, mrp, as_of_date
    FROM stg.item_master
) x WHERE sku_code IS NOT NULL AND sku_code <> '';

CREATE TEMP TABLE product_attr ON COMMIT DROP AS
WITH pick AS (
    SELECT sku_code,
      (array_agg(product_name   ORDER BY prio, seen_date DESC NULLS LAST) FILTER (WHERE nullif(btrim(product_name),'') IS NOT NULL))[1] AS product_name,
      (array_agg(product_type   ORDER BY prio) FILTER (WHERE product_type IS NOT NULL))[1] AS product_type,
      (array_agg(category       ORDER BY prio, seen_date DESC NULLS LAST) FILTER (WHERE category IS NOT NULL))[1] AS category,
      (array_agg(sub_category   ORDER BY prio, seen_date DESC NULLS LAST) FILTER (WHERE sub_category IS NOT NULL))[1] AS sub_category,
      (array_agg(product_family ORDER BY prio, seen_date DESC NULLS LAST) FILTER (WHERE product_family IS NOT NULL))[1] AS product_family,
      (array_agg(hsn_code       ORDER BY prio, seen_date DESC NULLS LAST) FILTER (WHERE hsn_code IS NOT NULL))[1] AS hsn_code,
      (array_agg(uom            ORDER BY prio) FILTER (WHERE uom IS NOT NULL))[1] AS uom,
      (array_agg(ean_code       ORDER BY seen_date DESC NULLS LAST) FILTER (WHERE ean_code IS NOT NULL))[1] AS ean_code,
      min(seen_date) FILTER (WHERE prio < 9) AS first_seen_date
    FROM product_src GROUP BY sku_code
    HAVING min(prio) < 9),            -- an item only in the ERP item master (never traded, stocked or ordered) is not added
erp_mrp AS (   -- current MRP: latest ERP stock report (largest non-zero across locations) ...
    SELECT sku_code, max(unit_mrp) AS m FROM stg.inventory_snapshot
    WHERE source_name = 'ERP_INVENTORY_SNAPSHOT' AND unit_mrp > 0
      AND snapshot_date = (SELECT max(snapshot_date) FROM stg.inventory_snapshot WHERE source_name = 'ERP_INVENTORY_SNAPSHOT')
    GROUP BY sku_code),
inv_mrp AS (   -- ... else the latest invoice MRP
    SELECT DISTINCT ON (sku_code) sku_code, unit_mrp AS m FROM stg.retail_sales
    WHERE unit_mrp > 0 ORDER BY sku_code, bill_date DESC NULLS LAST, source_row_number DESC),
mrp AS (SELECT p.sku_code, coalesce(e.m, i.m, im.mrp) AS current_mrp FROM pick p     -- ... else the ERP item master
        LEFT JOIN erp_mrp e USING (sku_code) LEFT JOIN inv_mrp i USING (sku_code) LEFT JOIN stg.item_master im USING (sku_code))
SELECT p.*, m.current_mrp,
       coalesce(ov.standard_value, tn.standard_value, 'UNKNOWN') AS item_type,
       CASE WHEN coalesce(ov.standard_value, tn.standard_value) = 'TRADING' THEN
            CASE ms.status WHEN 'Continued' THEN 'CONTINUED' WHEN 'Discontinued' THEN 'DISCONTINUED' ELSE 'NOT_IN_MASTER' END
            ELSE 'NOT_APPLICABLE' END AS lifecycle_status
FROM pick p JOIN mrp m USING (sku_code)
LEFT JOIN ref.code_mapping ov ON ov.domain = 'ITEM_TYPE' AND ov.source_name = 'PRODUCT_MASTER' AND ov.source_value = p.sku_code
LEFT JOIN ref.code_mapping tn ON tn.domain = 'ITEM_TYPE_NAME' AND tn.source_name = 'PRODUCT_MASTER' AND tn.source_value = p.product_type
LEFT JOIN (SELECT DISTINCT ON (stg.sku(prod_num)) stg.sku(prod_num) sku_code, btrim(status) status FROM raw.product_master
           WHERE batch_id = (SELECT batch_id FROM meta.load_batch WHERE source_name='PRODUCT_MASTER' AND status='LOADED' ORDER BY as_of_date DESC, batch_id DESC LIMIT 1)
           ORDER BY stg.sku(prod_num), source_row_number) ms ON ms.sku_code = p.sku_code;

INSERT INTO core.dim_product (sku_code, product_name, item_type, category, sub_category, product_family, hsn_code, uom, ean_code,
    lifecycle_status, current_mrp, first_seen_date)
SELECT sku_code, coalesce(product_name, sku_code), item_type, category, sub_category, product_family, hsn_code, uom, ean_code,
       lifecycle_status, current_mrp, first_seen_date
FROM product_attr
ON CONFLICT (sku_code) DO UPDATE SET product_name = EXCLUDED.product_name, item_type = EXCLUDED.item_type, category = EXCLUDED.category,
    sub_category = EXCLUDED.sub_category, product_family = EXCLUDED.product_family, hsn_code = EXCLUDED.hsn_code, uom = EXCLUDED.uom,
    ean_code = coalesce(EXCLUDED.ean_code, core.dim_product.ean_code), lifecycle_status = EXCLUDED.lifecycle_status,
    current_mrp = EXCLUDED.current_mrp,
    first_seen_date = least(EXCLUDED.first_seen_date, core.dim_product.first_seen_date), updated_at = CURRENT_TIMESTAMP
WHERE (core.dim_product.product_name, core.dim_product.item_type, core.dim_product.category, core.dim_product.sub_category,
       core.dim_product.product_family, core.dim_product.hsn_code, core.dim_product.uom, core.dim_product.ean_code,
       core.dim_product.lifecycle_status, core.dim_product.current_mrp, core.dim_product.first_seen_date)
  IS DISTINCT FROM (EXCLUDED.product_name, EXCLUDED.item_type, EXCLUDED.category, EXCLUDED.sub_category,
       EXCLUDED.product_family, EXCLUDED.hsn_code, EXCLUDED.uom, coalesce(EXCLUDED.ean_code, core.dim_product.ean_code),
       EXCLUDED.lifecycle_status, EXCLUDED.current_mrp, least(EXCLUDED.first_seen_date, core.dim_product.first_seen_date));

-- Product history (type 2) for lifecycle, MRP, category, collection, dated by the master's as-of date.
CREATE TEMP TABLE hist_basis ON COMMIT DROP AS
SELECT coalesce((SELECT as_of_date FROM meta.load_batch WHERE source_name='PRODUCT_MASTER' AND status='LOADED' ORDER BY as_of_date DESC, batch_id DESC LIMIT 1),
                (SELECT max(snapshot_date) FROM stg.inventory_snapshot)) AS as_of,
       coalesce((SELECT batch_id FROM meta.load_batch WHERE source_name='PRODUCT_MASTER' AND status='LOADED' ORDER BY as_of_date DESC, batch_id DESC LIMIT 1),
                (SELECT max(batch_id) FROM meta.load_batch WHERE status='LOADED')) AS batch_id;

-- same-day re-run: update the current version in place
UPDATE core.dim_product_history h SET lifecycle_status = p.lifecycle_status, mrp = p.current_mrp, category = p.category, collection = p.collection
FROM core.dim_product p, hist_basis hb
WHERE h.product_key = p.product_key AND h.is_current AND h.valid_from = hb.as_of
  AND (h.lifecycle_status, h.mrp, h.category, h.collection) IS DISTINCT FROM (p.lifecycle_status, p.current_mrp, p.category, p.collection);
-- a later change: close the current version
UPDATE core.dim_product_history h SET valid_to = hb.as_of, is_current = FALSE
FROM core.dim_product p, hist_basis hb
WHERE h.product_key = p.product_key AND h.is_current AND h.valid_from < hb.as_of
  AND (h.lifecycle_status, h.mrp, h.category, h.collection) IS DISTINCT FROM (p.lifecycle_status, p.current_mrp, p.category, p.collection);
-- open a version for every product without a current one
INSERT INTO core.dim_product_history (product_key, lifecycle_status, mrp, category, collection, valid_from, valid_to, is_current, batch_id)
SELECT p.product_key, p.lifecycle_status, p.current_mrp, p.category, p.collection, hb.as_of, NULL, TRUE, hb.batch_id
FROM core.dim_product p CROSS JOIN hist_basis hb
WHERE NOT p.is_unknown_member AND hb.as_of IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM core.dim_product_history h WHERE h.product_key = p.product_key AND h.is_current);

-- --------------------------------------------------------------------- order
INSERT INTO core.dim_order (channel_key, external_order_number, first_seen_date_key)
SELECT coalesce(c.channel_key, -1), o.order_number, stg.date_key(min(o.d))
FROM (SELECT contact_name, order_number, coalesce(order_date, bill_date) d, 'ERP_RETAIL_SALES' src FROM stg.retail_sales WHERE order_number IS NOT NULL
      UNION ALL SELECT contact_name, order_number, return_date, 'ERP_RETAIL_RETURN' FROM stg.retail_return WHERE order_number IS NOT NULL) o
LEFT JOIN ref.channel_alias ca ON ca.source_name = o.src AND ca.source_field = 'CONTACTNAME' AND ca.source_value = o.contact_name
LEFT JOIN core.dim_channel c ON c.channel_code = ca.channel_code
GROUP BY coalesce(c.channel_key, -1), o.order_number
ON CONFLICT (channel_key, external_order_number) DO UPDATE
    SET first_seen_date_key = least(core.dim_order.first_seen_date_key, EXCLUDED.first_seen_date_key);

-- --------------------------------------------------------------------- courier
INSERT INTO core.dim_courier (courier_name)
SELECT DISTINCT courier_name FROM stg.retail_sales WHERE courier_name IS NOT NULL
ON CONFLICT (courier_name) DO NOTHING;
INSERT INTO core.dim_courier (courier_name)
SELECT DISTINCT left(courier_name, 100) FROM stg.wms_dispatch WHERE courier_name IS NOT NULL   -- WMS transporter as written
ON CONFLICT (courier_name) DO NOTHING;
-- courier company behind each spelling (ref.code_mapping COURIER); never NULL, so dashboards can group on it
UPDATE core.dim_courier c SET courier_group = coalesce(m.standard_value, CASE WHEN c.is_unknown_member THEN 'Not recorded' ELSE 'Other (unmapped)' END)
FROM core.dim_courier c2
LEFT JOIN (SELECT DISTINCT ON (source_value) source_value, standard_value FROM ref.code_mapping WHERE domain = 'COURIER'
           ORDER BY source_value, source_name) m ON m.source_value = c2.courier_name
WHERE c2.courier_key = c.courier_key
  AND c.courier_group IS DISTINCT FROM coalesce(m.standard_value, CASE WHEN c.is_unknown_member THEN 'Not recorded' ELSE 'Other (unmapped)' END);
