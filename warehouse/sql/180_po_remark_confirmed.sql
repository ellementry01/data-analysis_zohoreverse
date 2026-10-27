-- =============================================================================
-- 180  Schema 2.10: rule BR-031 confirmed by the business (2026-10-27). The PO export's Document Remark decides:
-- 'Purchase' lines are factory purchases, 'Return' lines are return-inwards. Effects (all in the transform):
-- return-inward lines leave v_open_purchase_orders and v_supplier_lead_time, and goods receipts (at Bagru, BR-032)
-- enter the stock ledger as GOODS_RECEIPT or RETURN_INWARD.
-- =============================================================================

UPDATE meta.pipeline_setting SET setting_value = 'true', updated_at = CURRENT_TIMESTAMP
WHERE setting_key = 'po_document_remark_confirmed';

INSERT INTO meta.schema_version (version, migration_file, description)
VALUES ('2.10', '180_po_remark_confirmed.sql', 'BR-031 confirmed: PO Document Remark separates purchases from return-inwards');
