-- =============================================================================
-- 110  PO document type (schema 2.3). Additive only: nothing renamed, retyped or dropped.
-- The Pending PO export gained a 'Document Remark' column holding Purchase or Return on every line.
-- It is stored as the export states it (raw), carried to core as document_type, and is only USED to
-- separate purchases from return-inwards once the business confirms it (rule BR-031, PROPOSED):
-- switch po_document_remark_confirmed, false until then, same pattern as partner_list_complete.
-- IF NOT EXISTS: a fresh build already has the raw column from the regenerated 070_raw_tables.sql.
-- =============================================================================

ALTER TABLE raw.erp_purchase_order ADD COLUMN IF NOT EXISTS document_remark TEXT;
COMMENT ON COLUMN raw.erp_purchase_order.document_remark IS 'Source header: Document Remark';

ALTER TABLE core.fact_purchase_order_line ADD COLUMN IF NOT EXISTS document_type VARCHAR(8) NOT NULL DEFAULT 'UNKNOWN'
    CONSTRAINT ck_po_document_type CHECK (document_type IN ('PURCHASE','RETURN','UNKNOWN'));

INSERT INTO meta.pipeline_setting (setting_key, setting_value, description) VALUES
 ('po_document_remark_confirmed', 'false',
  'true only once the business confirms rule BR-031 (PO Document Remark = Purchase / Return). While false, document_type is stored '
  'and reported but does not decide what counts as a purchase')
ON CONFLICT (setting_key) DO NOTHING;

INSERT INTO meta.schema_version (version, migration_file, description)
VALUES ('2.3', '110_po_document_type.sql', 'PO Document Remark: raw column, core document_type, confirmation switch');
