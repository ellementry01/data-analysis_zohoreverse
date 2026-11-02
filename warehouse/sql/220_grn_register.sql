-- =============================================================================
-- 220  Schema 2.14: the ERP goods-receipt register (MRN Register) as a source (issues D-047, D-124).
-- One row per goods-receipt line with its own date, supplier, PO and quantity, for every GRN, including those on POs
-- the Pending PO export no longer lists (closed POs: 60,318 units Apr 2025 - Sep 2026). Normalised by
-- loader.normalise_grn_register (memo repeats kept once). core.fact_grn_line feeds the stock ledger and lead time.
-- =============================================================================

INSERT INTO meta.source_registry (source_name, source_system, description, grain, load_type, natural_key, date_format, known_issues)
VALUES ('ERP_GRN_REGISTER', 'ERP', 'ERP MRN Register (goods receipts), normalised: one row per goods-receipt line',
        'One row per GRN x product line', 'TRANSACTIONAL', 'GRN No. + Product No.', 'dd/mm/yyyy',
        'The report repeats item rows once per debit-note memo; the normaliser keeps them once (Repeats in source)')
ON CONFLICT (source_name) DO NOTHING;

-- ERP_GRN_REGISTER
CREATE TABLE IF NOT EXISTS raw.erp_grn_register (
    batch_id           BIGINT  NOT NULL REFERENCES meta.load_batch (batch_id),
    source_row_number  INTEGER NOT NULL,
    grn_no                                   TEXT,
    grn_date                                 TEXT,
    supplier                                 TEXT,
    po_no                                    TEXT,
    po_date                                  TEXT,
    bill_no                                  TEXT,
    bill_date                                TEXT,
    product_no                               TEXT,
    hsn_code                                 TEXT,
    product_description                      TEXT,
    bill_quantity                            TEXT,
    received_quantity                        TEXT,
    rate                                     TEXT,
    amount                                   TEXT,
    gst                                      TEXT,
    total_amount                             TEXT,
    repeats_in_source                        TEXT,
    PRIMARY KEY (batch_id, source_row_number)
);
COMMENT ON TABLE raw.erp_grn_register IS 'As received from ERP_GRN_REGISTER. Contract: loader/contracts/ERP_GRN_REGISTER.json';
COMMENT ON COLUMN raw.erp_grn_register.grn_no IS 'Source header: GRN No.';
COMMENT ON COLUMN raw.erp_grn_register.grn_date IS 'Source header: GRN Date';
COMMENT ON COLUMN raw.erp_grn_register.supplier IS 'Source header: Supplier';
COMMENT ON COLUMN raw.erp_grn_register.po_no IS 'Source header: PO No.';
COMMENT ON COLUMN raw.erp_grn_register.po_date IS 'Source header: PO Date';
COMMENT ON COLUMN raw.erp_grn_register.bill_no IS 'Source header: Bill No.';
COMMENT ON COLUMN raw.erp_grn_register.bill_date IS 'Source header: Bill Date';
COMMENT ON COLUMN raw.erp_grn_register.product_no IS 'Source header: Product No.';
COMMENT ON COLUMN raw.erp_grn_register.hsn_code IS 'Source header: HSN Code';
COMMENT ON COLUMN raw.erp_grn_register.product_description IS 'Source header: Product Description';
COMMENT ON COLUMN raw.erp_grn_register.bill_quantity IS 'Source header: Bill Quantity';
COMMENT ON COLUMN raw.erp_grn_register.received_quantity IS 'Source header: Received Quantity';
COMMENT ON COLUMN raw.erp_grn_register.rate IS 'Source header: Rate';
COMMENT ON COLUMN raw.erp_grn_register.amount IS 'Source header: Amount';
COMMENT ON COLUMN raw.erp_grn_register.gst IS 'Source header: GST %';
COMMENT ON COLUMN raw.erp_grn_register.total_amount IS 'Source header: Total Amount';
COMMENT ON COLUMN raw.erp_grn_register.repeats_in_source IS 'Source header: Repeats in source';


CREATE TABLE IF NOT EXISTS core.fact_grn_line (
    grn_line_id            BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    grn_number             VARCHAR(60)   NOT NULL,
    grn_date_key           INTEGER       NOT NULL REFERENCES core.dim_date (date_key),
    partner_key            INTEGER       NOT NULL REFERENCES core.dim_partner (partner_key),
    supplier_name          VARCHAR(200),
    po_number              VARCHAR(60),
    po_date_key            INTEGER       REFERENCES core.dim_date (date_key),
    po_line_id             BIGINT,
    product_key            INTEGER       NOT NULL REFERENCES core.dim_product (product_key),
    source_sku_code        VARCHAR(60),
    receiving_location_key SMALLINT      NOT NULL,
    received_qty           NUMERIC(14,3) NOT NULL,
    rate                   NUMERIC(14,4),
    amount                 NUMERIC(16,2),
    document_type          VARCHAR(8)    NOT NULL,
    document_type_basis    VARCHAR(20)   NOT NULL,
    batch_id               BIGINT        NOT NULL REFERENCES meta.load_batch (batch_id),
    source_row_number      INTEGER       NOT NULL
);
COMMENT ON TABLE core.fact_grn_line IS 'Goods-receipt lines from the ERP MRN Register: own date per receipt, every GRN (also on POs no longer in the Pending PO export)';
COMMENT ON COLUMN core.fact_grn_line.document_type IS 'PURCHASE or RETURN (return-inward), BR-031: the PO''s Document Remark; else the supplier''s POs; else PURCHASE';
COMMENT ON COLUMN core.fact_grn_line.document_type_basis IS 'How document_type was decided: PO_REMARK, SUPPLIER_POS or DEFAULT_PURCHASE';
COMMENT ON COLUMN core.fact_grn_line.receiving_location_key IS 'Bagru (setting goods_receipt_location, BR-032)';

ALTER TABLE core.fact_stock_movement DROP CONSTRAINT IF EXISTS fact_stock_movement_source_table_check;
ALTER TABLE core.fact_stock_movement ADD CONSTRAINT fact_stock_movement_source_table_check
    CHECK (source_table IN ('fact_sales_line','fact_return_line','fact_stock_transfer_line','fact_goods_receipt_line',
                            'fact_partner_sellout','fact_grn_line'));

INSERT INTO meta.schema_version (version, migration_file, description)
VALUES ('2.14', '220_grn_register.sql', 'ERP goods-receipt register as a source; receipts with their own dates');
