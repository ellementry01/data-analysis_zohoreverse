-- =============================================================================
-- 250  Schema 2.17 (warehouse review, 12 Nov 2026): two exports that were received but never loaded.
--  * AMAZON_SELLER_RETURNS: Seller Central "Manage Seller Fulfilled Returns" reports (Amazon orders we ship ourselves),
--    normalised by loader.normalise_amazon_seller_returns. Return reasons for self-shipped Amazon orders (D-079, G-009)
--    and the refused / undelivered returns the WMS never records for Amazon (D-112). They land in the existing
--    core.fact_return_reason_line, channel AMAZON_SELF_SHIP.
--  * ERP_DOC_STOCK_MOVEMENT: the ERP 'Document Wise Stock Movement' report, normalised by
--    loader.normalise_doc_stock_movement: units per product and ERP document type for a whole period, all locations
--    together. It names the documents the other exports lack (Scrap Note, Increase / Decrease Stock, Inventory Transfer,
--    sub-contractor DN / GIN, Return To Supplier), so the stock check can say how much of the unexplained stock those
--    documents account for (D-124). It has no dates or locations inside the period, so it never enters the stock ledger.
-- IF NOT EXISTS / ON CONFLICT: a fresh build already has the raw tables from 070.
-- =============================================================================

INSERT INTO meta.source_registry (source_name, source_system, description, grain, load_type, natural_key, date_format, known_issues)
VALUES ('AMAZON_SELLER_RETURNS', 'AMAZON', 'Amazon Seller Central seller-fulfilled returns reports, normalised: reason, return type and resolution per return request line',
        'One row per return request line (Amazon RMA ID x order item)', 'TRANSACTIONAL', 'Amazon RMA ID + Order Item ID', 'yyyy-mm-dd (normalised from dd-Mon-yyyy)',
        'Self-shipped Amazon orders only (FBA returns are AMAZON_CUSTOMER_RETURNS); Return type Rejected / Undelivered = not delivered; several download windows overlap, identical rows kept once'),
       ('ERP_DOC_STOCK_MOVEMENT', 'ERP', 'ERP Document Wise Stock Movement report, normalised: units and value per product and ERP document type for one period, all locations together',
        'One row per product x document type for the period in the report title', 'STATE_SNAPSHOT', 'Product No. + Document Type + period', 'yyyy-mm-dd (period from the report title)',
        'No dates or locations inside the period; OPENING and CLOSING are rows too; used to explain unexplained stock, never placed in the stock ledger')
ON CONFLICT (source_name) DO NOTHING;

-- AMAZON_SELLER_RETURNS
CREATE TABLE IF NOT EXISTS raw.amazon_seller_returns (
    batch_id           BIGINT  NOT NULL REFERENCES meta.load_batch (batch_id),
    source_row_number  INTEGER NOT NULL,
    order_id                                 TEXT,
    order_date                               TEXT,
    return_request_date                      TEXT,
    return_request_status                    TEXT,
    amazon_rma_id                            TEXT,
    seller_rma_id                            TEXT,
    label_type                               TEXT,
    label_cost                               TEXT,
    currency_code                            TEXT,
    return_carrier                           TEXT,
    tracking_id                              TEXT,
    label_to_be_paid_by                      TEXT,
    a_to_z_claim                             TEXT,
    is_prime                                 TEXT,
    asin                                     TEXT,
    merchant_sku                             TEXT,
    item_name                                TEXT,
    return_quantity                          TEXT,
    return_reason                            TEXT,
    in_policy                                TEXT,
    return_type                              TEXT,
    resolution                               TEXT,
    invoice_number                           TEXT,
    return_delivery_date                     TEXT,
    order_amount                             TEXT,
    order_quantity                           TEXT,
    safet_action_reason                      TEXT,
    safet_claim_id                           TEXT,
    safet_claim_state                        TEXT,
    safet_claim_creation_time                TEXT,
    safet_claim_reimbursement_amount         TEXT,
    refunded_amount                          TEXT,
    category                                 TEXT,
    order_item_id                            TEXT,
    PRIMARY KEY (batch_id, source_row_number)
);
COMMENT ON TABLE raw.amazon_seller_returns IS 'As received from AMAZON_SELLER_RETURNS. Contract: loader/contracts/AMAZON_SELLER_RETURNS.json';
COMMENT ON COLUMN raw.amazon_seller_returns.order_id IS 'Source header: Order ID';
COMMENT ON COLUMN raw.amazon_seller_returns.order_date IS 'Source header: Order date';
COMMENT ON COLUMN raw.amazon_seller_returns.return_request_date IS 'Source header: Return request date';
COMMENT ON COLUMN raw.amazon_seller_returns.return_request_status IS 'Source header: Return request status';
COMMENT ON COLUMN raw.amazon_seller_returns.amazon_rma_id IS 'Source header: Amazon RMA ID';
COMMENT ON COLUMN raw.amazon_seller_returns.seller_rma_id IS 'Source header: Seller RMA ID';
COMMENT ON COLUMN raw.amazon_seller_returns.label_type IS 'Source header: Label type';
COMMENT ON COLUMN raw.amazon_seller_returns.label_cost IS 'Source header: Label cost';
COMMENT ON COLUMN raw.amazon_seller_returns.currency_code IS 'Source header: Currency code';
COMMENT ON COLUMN raw.amazon_seller_returns.return_carrier IS 'Source header: Return carrier';
COMMENT ON COLUMN raw.amazon_seller_returns.tracking_id IS 'Source header: Tracking ID';
COMMENT ON COLUMN raw.amazon_seller_returns.label_to_be_paid_by IS 'Source header: Label to be paid by';
COMMENT ON COLUMN raw.amazon_seller_returns.a_to_z_claim IS 'Source header: A-to-z claim';
COMMENT ON COLUMN raw.amazon_seller_returns.is_prime IS 'Source header: Is prime';
COMMENT ON COLUMN raw.amazon_seller_returns.asin IS 'Source header: ASIN';
COMMENT ON COLUMN raw.amazon_seller_returns.merchant_sku IS 'Source header: Merchant SKU';
COMMENT ON COLUMN raw.amazon_seller_returns.item_name IS 'Source header: Item Name';
COMMENT ON COLUMN raw.amazon_seller_returns.return_quantity IS 'Source header: Return quantity';
COMMENT ON COLUMN raw.amazon_seller_returns.return_reason IS 'Source header: Return reason';
COMMENT ON COLUMN raw.amazon_seller_returns.in_policy IS 'Source header: In policy';
COMMENT ON COLUMN raw.amazon_seller_returns.return_type IS 'Source header: Return type';
COMMENT ON COLUMN raw.amazon_seller_returns.resolution IS 'Source header: Resolution';
COMMENT ON COLUMN raw.amazon_seller_returns.invoice_number IS 'Source header: Invoice number';
COMMENT ON COLUMN raw.amazon_seller_returns.return_delivery_date IS 'Source header: Return delivery date';
COMMENT ON COLUMN raw.amazon_seller_returns.order_amount IS 'Source header: Order Amount';
COMMENT ON COLUMN raw.amazon_seller_returns.order_quantity IS 'Source header: Order quantity';
COMMENT ON COLUMN raw.amazon_seller_returns.safet_action_reason IS 'Source header: SafeT Action reason';
COMMENT ON COLUMN raw.amazon_seller_returns.safet_claim_id IS 'Source header: SafeT claim ID';
COMMENT ON COLUMN raw.amazon_seller_returns.safet_claim_state IS 'Source header: SafeT claim state';
COMMENT ON COLUMN raw.amazon_seller_returns.safet_claim_creation_time IS 'Source header: SafeT claim creation time';
COMMENT ON COLUMN raw.amazon_seller_returns.safet_claim_reimbursement_amount IS 'Source header: SafeT claim reimbursement amount';
COMMENT ON COLUMN raw.amazon_seller_returns.refunded_amount IS 'Source header: Refunded Amount';
COMMENT ON COLUMN raw.amazon_seller_returns.category IS 'Source header: Category';
COMMENT ON COLUMN raw.amazon_seller_returns.order_item_id IS 'Source header: Order Item ID';


-- ERP_DOC_STOCK_MOVEMENT
CREATE TABLE IF NOT EXISTS raw.erp_doc_stock_movement (
    batch_id           BIGINT  NOT NULL REFERENCES meta.load_batch (batch_id),
    source_row_number  INTEGER NOT NULL,
    product_no                               TEXT,
    product_description                      TEXT,
    document_type                            TEXT,
    quantity                                 TEXT,
    value                                    TEXT,
    period_from                              TEXT,
    period_to                                TEXT,
    PRIMARY KEY (batch_id, source_row_number)
);
COMMENT ON TABLE raw.erp_doc_stock_movement IS 'As received from ERP_DOC_STOCK_MOVEMENT. Contract: loader/contracts/ERP_DOC_STOCK_MOVEMENT.json';
COMMENT ON COLUMN raw.erp_doc_stock_movement.product_no IS 'Source header: Product No.';
COMMENT ON COLUMN raw.erp_doc_stock_movement.product_description IS 'Source header: Product Description';
COMMENT ON COLUMN raw.erp_doc_stock_movement.document_type IS 'Source header: Document Type';
COMMENT ON COLUMN raw.erp_doc_stock_movement.quantity IS 'Source header: Quantity';
COMMENT ON COLUMN raw.erp_doc_stock_movement.value IS 'Source header: Value';
COMMENT ON COLUMN raw.erp_doc_stock_movement.period_from IS 'Source header: Period From';
COMMENT ON COLUMN raw.erp_doc_stock_movement.period_to IS 'Source header: Period To';


CREATE TABLE IF NOT EXISTS core.fact_erp_document_movement (
    erp_document_movement_id  BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_name               VARCHAR(60)   NOT NULL REFERENCES meta.source_registry (source_name),
    period_from               DATE          NOT NULL,
    period_to                 DATE          NOT NULL,
    product_key               INTEGER       NOT NULL REFERENCES core.dim_product (product_key),
    source_sku_code           VARCHAR(60),
    document_type             VARCHAR(60)   NOT NULL,
    is_in_other_exports       BOOLEAN       NOT NULL,
    quantity                  NUMERIC(14,3) NOT NULL,
    value_amount              NUMERIC(16,2),
    batch_id                  BIGINT        NOT NULL REFERENCES meta.load_batch (batch_id),
    source_row_number         INTEGER       NOT NULL
);
COMMENT ON TABLE core.fact_erp_document_movement IS 'Units per product and ERP document type over one period, all locations together (ERP Document Wise Stock Movement). A summary for explaining unexplained stock: it has no dates or locations, so it is never part of the stock ledger';
COMMENT ON COLUMN core.fact_erp_document_movement.erp_document_movement_id IS 'Surrogate key';
COMMENT ON COLUMN core.fact_erp_document_movement.source_name IS 'Source the row came from (ERP_DOC_STOCK_MOVEMENT)';
COMMENT ON COLUMN core.fact_erp_document_movement.period_from IS 'First day of the period the report covers (from its title)';
COMMENT ON COLUMN core.fact_erp_document_movement.period_to IS 'Last day of the period the report covers (from its title)';
COMMENT ON COLUMN core.fact_erp_document_movement.product_key IS 'Product (core.dim_product); -1 when the report''s product code is not a known SKU';
COMMENT ON COLUMN core.fact_erp_document_movement.source_sku_code IS 'Product code as printed in the report';
COMMENT ON COLUMN core.fact_erp_document_movement.document_type IS 'ERP document type as printed, e.g. Scrap Note, Increase Stock, Goods Receipt Note (OPENING and CLOSING are left out)';
COMMENT ON COLUMN core.fact_erp_document_movement.is_in_other_exports IS 'True when the same documents also reach the warehouse through another export (sales, returns, transfers, goods receipts); false for the types no other export carries (ref.code_mapping ERP_DOCUMENT_COVERAGE)';
COMMENT ON COLUMN core.fact_erp_document_movement.quantity IS 'Units moved by this document type in the period: positive = into stock, negative = out of stock';
COMMENT ON COLUMN core.fact_erp_document_movement.value_amount IS 'Value of those units as the ERP reports it';
COMMENT ON COLUMN core.fact_erp_document_movement.batch_id IS 'Load batch the row came from (meta.load_batch): traces the row to the exact source file';
COMMENT ON COLUMN core.fact_erp_document_movement.source_row_number IS 'Row number in the loaded file';

INSERT INTO meta.schema_version (version, migration_file, description)
VALUES ('2.17', '250_review_sources.sql', 'Amazon seller-fulfilled returns; ERP document-wise stock movement summary');
