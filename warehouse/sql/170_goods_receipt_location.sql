-- =============================================================================
-- 170  Schema 2.9: goods receipts arrive at Bagru (rule BR-032, business confirmed 2026-10-27).
-- The PO export has no receiving location (G-025, now closed): the transform places every goods receipt at the
-- location in setting goods_receipt_location. A setting, not a hard-coded code, so a future export with a real
-- receiving branch can replace it.
-- =============================================================================

INSERT INTO meta.pipeline_setting (setting_key, setting_value, description) VALUES
 ('goods_receipt_location', 'BAGRU_WH',
  'Location code where goods receipts against purchase orders arrive (BR-032). The PO export has no receiving branch.')
ON CONFLICT (setting_key) DO NOTHING;

INSERT INTO meta.schema_version (version, migration_file, description)
VALUES ('2.9', '170_goods_receipt_location.sql', 'Goods receipts placed at Bagru (BR-032)');
