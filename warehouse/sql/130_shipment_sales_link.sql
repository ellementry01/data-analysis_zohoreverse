-- =============================================================================
-- 130  Schema 2.5: link WMS shipments to ERP bills. Additive only.
-- The WMS Invoice No is the marketplace's own invoice for most marketplace orders, so it rarely matches an ERP
-- bill. Shipments are now linked by Invoice No, else Extern Order No (= the bill's order number), else the AWB.
-- =============================================================================

ALTER TABLE core.fact_shipment ADD COLUMN IF NOT EXISTS sales_bill_number VARCHAR(60);
ALTER TABLE core.fact_shipment ADD COLUMN IF NOT EXISTS sales_link_method VARCHAR(10) NOT NULL DEFAULT 'NONE'
    CONSTRAINT ck_shipment_sales_link_method CHECK (sales_link_method IN ('INVOICE','ORDER','AWB','NONE'));
COMMENT ON COLUMN core.fact_shipment.sales_bill_number IS 'ERP bill this delivery ships (first of several when an order has more than one bill)';
COMMENT ON COLUMN core.fact_shipment.sales_link_method IS 'How the bill was found: INVOICE (WMS Invoice No), ORDER (Extern Order No = bill order number), AWB (Tracking No = bill AWB), NONE';

INSERT INTO meta.schema_version (version, migration_file, description)
VALUES ('2.5', '130_shipment_sales_link.sql', 'Shipments linked to ERP bills by invoice, order number or AWB');
