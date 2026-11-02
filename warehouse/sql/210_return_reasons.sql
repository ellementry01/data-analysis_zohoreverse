-- =============================================================================
-- 210  Schema 2.13: Amazon FBA customer returns (return reasons) as a source, for the Returns dashboard (gap G-009,
-- issue D-105). Raw keeps the file as received, incl. customer-comments (free text: raw only, never in core or mart).
-- core.fact_return_reason_line: one row per returned unit with Amazon's reason and the condition it came back in.
-- IF NOT EXISTS / ON CONFLICT: a fresh build already has the raw table from 070.
-- =============================================================================

ALTER TABLE meta.source_registry DROP CONSTRAINT IF EXISTS source_registry_source_system_check;
ALTER TABLE meta.source_registry ADD CONSTRAINT source_registry_source_system_check
    CHECK (source_system IN ('ERP','WMS','BLINKIT','INSTAMART','PRODUCT_MASTER','AMAZON'));

INSERT INTO meta.source_registry (source_name, source_system, description, grain, load_type, natural_key, date_format, known_issues)
VALUES ('AMAZON_CUSTOMER_RETURNS', 'AMAZON', 'Amazon Seller Central FBA customer returns report: reason and disposition per returned unit',
        'One row per returned unit (license plate)', 'TRANSACTIONAL', 'license-plate-number', 'ISO 8601 timestamp, UTC',
        'FBA orders only (Amazon-fulfilled); SKUs carry an -FBA suffix; customer-comments is free text and stays in raw')
ON CONFLICT (source_name) DO NOTHING;

-- AMAZON_CUSTOMER_RETURNS
CREATE TABLE IF NOT EXISTS raw.amazon_customer_returns (
    batch_id           BIGINT  NOT NULL REFERENCES meta.load_batch (batch_id),
    source_row_number  INTEGER NOT NULL,
    return_date                              TEXT,
    order_id                                 TEXT,
    sku                                      TEXT,
    asin                                     TEXT,
    fnsku                                    TEXT,
    product_name                             TEXT,
    quantity                                 TEXT,
    fulfillment_center_id                    TEXT,
    detailed_disposition                     TEXT,
    reason                                   TEXT,
    license_plate_number                     TEXT,
    customer_comments                        TEXT,
    PRIMARY KEY (batch_id, source_row_number)
);
COMMENT ON TABLE raw.amazon_customer_returns IS 'As received from AMAZON_CUSTOMER_RETURNS. Contract: loader/contracts/AMAZON_CUSTOMER_RETURNS.json';
COMMENT ON COLUMN raw.amazon_customer_returns.return_date IS 'Source header: return-date';
COMMENT ON COLUMN raw.amazon_customer_returns.order_id IS 'Source header: order-id';
COMMENT ON COLUMN raw.amazon_customer_returns.sku IS 'Source header: sku';
COMMENT ON COLUMN raw.amazon_customer_returns.asin IS 'Source header: asin';
COMMENT ON COLUMN raw.amazon_customer_returns.fnsku IS 'Source header: fnsku';
COMMENT ON COLUMN raw.amazon_customer_returns.product_name IS 'Source header: product-name';
COMMENT ON COLUMN raw.amazon_customer_returns.quantity IS 'Source header: quantity';
COMMENT ON COLUMN raw.amazon_customer_returns.fulfillment_center_id IS 'Source header: fulfillment-center-id';
COMMENT ON COLUMN raw.amazon_customer_returns.detailed_disposition IS 'Source header: detailed-disposition';
COMMENT ON COLUMN raw.amazon_customer_returns.reason IS 'Source header: reason';
COMMENT ON COLUMN raw.amazon_customer_returns.license_plate_number IS 'Source header: license-plate-number';
COMMENT ON COLUMN raw.amazon_customer_returns.customer_comments IS 'Source header: customer-comments';


CREATE TABLE IF NOT EXISTS core.fact_return_reason_line (
    return_reason_line_id  BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_name            VARCHAR(60)   NOT NULL REFERENCES meta.source_registry (source_name),
    return_date_key        INTEGER       NOT NULL REFERENCES core.dim_date (date_key),
    channel_key            SMALLINT      NOT NULL REFERENCES core.dim_channel (channel_key),
    product_key            INTEGER       NOT NULL REFERENCES core.dim_product (product_key),
    source_sku_code        VARCHAR(60),
    order_number           VARCHAR(60),
    reason_code            VARCHAR(60)   NOT NULL,
    disposition            VARCHAR(60),
    fulfilment_centre      VARCHAR(20),
    quantity               NUMERIC(12,3) NOT NULL,
    batch_id               BIGINT        NOT NULL REFERENCES meta.load_batch (batch_id),
    source_row_number      INTEGER       NOT NULL
);
COMMENT ON TABLE core.fact_return_reason_line IS 'Returned units with the platform''s return reason and condition (Amazon FBA customer returns). Reasons only: return value stays in fact_return_line (ERP credit notes)';
COMMENT ON COLUMN core.fact_return_reason_line.reason_code IS 'Platform reason code as given, e.g. DEFECTIVE, UNDELIVERABLE_REFUSED';
COMMENT ON COLUMN core.fact_return_reason_line.disposition IS 'Condition on return, e.g. SELLABLE, CUSTOMER_DAMAGED, CARRIER_DAMAGED';

INSERT INTO meta.schema_version (version, migration_file, description)
VALUES ('2.13', '210_return_reasons.sql', 'Amazon FBA customer returns: return reasons and condition');
