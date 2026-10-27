-- =============================================================================
-- 160  Schema 2.8: stock valued at cost. Additive only.
--   * core.dim_product.current_cost: unit cost from the ERP item master (Product Master List, COST column).
--   Business rules (Oct 2026), applied in the transform: stock value is at cost, not MRP; where MRPs disagree the
--   higher one is current (prices were raised; the lower MRP is old stock); category and sub-category come from the
--   ERP item master only, otherwise the product is uncategorised; Ellementry International = B2C export channel.
-- =============================================================================

ALTER TABLE core.dim_product ADD COLUMN IF NOT EXISTS current_cost NUMERIC(14,2);
COMMENT ON COLUMN core.dim_product.current_cost IS 'Unit cost (excl. GST) from the ERP item master COST column; NULL when the item master has none';

INSERT INTO meta.schema_version (version, migration_file, description)
VALUES ('2.8', '160_cost_and_category.sql', 'Product unit cost from the ERP item master; stock valued at cost');
