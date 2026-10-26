-- =============================================================================
-- 150  Schema 2.7: two exact rules for SKU quantities in multi-SKU dispatch rows. Additive only.
--   ONE_EACH:  the row's quantity equals the number of SKUs listed, so each SKU shipped exactly 1.
--   REMAINDER: every other SKU of the row has a known quantity, so this one is the row quantity minus theirs.
-- Neither guesses: both follow from the row's total. Anything else stays UNALLOCATED.
-- =============================================================================

DO $$
DECLARE c text;
BEGIN
    SELECT conname INTO c FROM pg_constraint
    WHERE conrelid = 'core.bridge_shipment_sku'::regclass AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%SINGLE_SKU_ROW%' AND pg_get_constraintdef(oid) NOT LIKE '%IS NULL%';
    IF c IS NOT NULL THEN
        EXECUTE format('ALTER TABLE core.bridge_shipment_sku DROP CONSTRAINT %I', c);
    END IF;
END $$;
ALTER TABLE core.bridge_shipment_sku ADD CONSTRAINT ck_bridge_quantity_source
    CHECK (quantity_source IN ('SINGLE_SKU_ROW','INVOICE_LINE','ONE_EACH','REMAINDER','UNALLOCATED'));
COMMENT ON COLUMN core.bridge_shipment_sku.quantity_source IS
    'SINGLE_SKU_ROW, INVOICE_LINE (from the linked bills), ONE_EACH (row quantity = number of SKUs), REMAINDER (row quantity minus the other SKUs), or UNALLOCATED (not known)';

INSERT INTO meta.schema_version (version, migration_file, description)
VALUES ('2.7', '150_shipment_sku_quantity_rules.sql', 'Exact SKU quantity rules for multi-SKU dispatch rows: ONE_EACH, REMAINDER');
