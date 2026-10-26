-- =============================================================================
-- 105_goods_receipt_grain.sql  |  Migration (schema v2.2)
-- Found by the first transform run: a part-delivered PO line lists ALL its goods
-- receipts in one GRNNUM cell ('JPR/GRN/199;305;89'), with ONE date and ONE
-- total quantity. Per-receipt dates and quantities are not in the export.
-- The receipt table therefore records what the report states, per PO line,
-- and lists the receipt numbers in a bridge. Nothing is split by guesswork.
-- A per-receipt GRN register export would close the gap (gap G-027).
-- The table held no data (the first run was rolled back), so it is recreated.
-- =============================================================================

DROP TABLE core.fact_goods_receipt_line;

CREATE TABLE core.fact_goods_receipt_line (
    receipt_line_id         BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    po_line_id              BIGINT        NOT NULL REFERENCES core.fact_purchase_order_line (po_line_id),
    po_number               VARCHAR(60)   NOT NULL,
    source_sku_code         VARCHAR(60)   NOT NULL,
    line_occurrence         SMALLINT      NOT NULL CHECK (line_occurrence >= 1),
    grn_date_key            INTEGER       NOT NULL REFERENCES core.dim_date (date_key),
    receipt_count           SMALLINT      NOT NULL CHECK (receipt_count >= 1),
    partner_key             INTEGER       NOT NULL REFERENCES core.dim_partner (partner_key),
    product_key             INTEGER       NOT NULL REFERENCES core.dim_product (product_key),
    receiving_location_key  SMALLINT      NOT NULL REFERENCES core.dim_location (location_key),
    received_qty            NUMERIC(14,3) NOT NULL CHECK (received_qty > 0),
    batch_id                BIGINT        NOT NULL REFERENCES meta.load_batch (batch_id),
    source_row_number       INTEGER       NOT NULL,
    loaded_at               TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_fact_goods_receipt_line UNIQUE (po_number, source_sku_code, line_occurrence)
);

CREATE TABLE core.bridge_goods_receipt_grn (
    receipt_line_id  BIGINT      NOT NULL REFERENCES core.fact_goods_receipt_line (receipt_line_id),
    grn_seq          SMALLINT    NOT NULL CHECK (grn_seq >= 1),
    grn_number       VARCHAR(60) NOT NULL,
    PRIMARY KEY (receipt_line_id, grn_seq)
);

INSERT INTO meta.schema_version (version, migration_file, description) VALUES ('2.2','105_goods_receipt_grain.sql','Goods receipt grain = PO line as reported; receipt numbers in a bridge');
