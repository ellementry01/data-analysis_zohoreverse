-- =============================================================================
-- 260  Schema 2.18 (14 Nov 2026): stock availability (ideal stock and reorder).
--  * SKU_PLANNING_MASTER: the team's reorder sheet ("SKU MASTER", e.g. 12-11-26.xls), normalised by
--    loader.normalise_planning_master to its planning columns: factory, MOQ, MLT, grade, top 40, replacement product,
--    launch date, and the sheet's own PO pending and warehouse stock (kept only to cross-check the ERP). Loaded with
--    --as-of = the sheet's date; every sheet is kept, the newest one is used.
--  * core.dim_product_planning: one row per product per sheet.
--  * Settings (owner, 14 Nov 2026): ideal stock = daily sales x (the product's MLT + 15 days transit and buffer); daily
--    sales = the last 12 months of sales, every channel except B2B bulk orders; reorder = shortfall against stock at the
--    goods-receipt warehouse plus open purchase orders, rounded up to the MOQ.
--  * The view mart.v_stock_availability is created by transform/sql/70_marts.sql.
-- IF NOT EXISTS / ON CONFLICT: a fresh build already has the raw table from 070.
-- =============================================================================

INSERT INTO meta.source_registry (source_name, source_system, description, grain, load_type, natural_key, date_format, known_issues)
VALUES ('SKU_PLANNING_MASTER', 'PRODUCT_MASTER', 'Team reorder sheet (SKU MASTER), normalised to its planning columns: factory, MOQ, MLT, grade, top 40, replacement product, launch date',
        'One row per product for the sheet date (--as-of)', 'STATE_SNAPSHOT', 'SKU + sheet date', 'yyyy-mm-dd (normalised from dd-mm-yyyy)',
        'Kept by hand; MLT is sometimes text (NOT) or empty and MOQ sometimes empty or 0; PO pending and warehouse stock in the sheet are typed in and only cross-check the ERP')
ON CONFLICT (source_name) DO NOTHING;

-- SKU_PLANNING_MASTER
CREATE TABLE IF NOT EXISTS raw.sku_planning_master (
    batch_id           BIGINT  NOT NULL REFERENCES meta.load_batch (batch_id),
    source_row_number  INTEGER NOT NULL,
    sku                                      TEXT,
    product_name                             TEXT,
    list_group                               TEXT,
    top_40                                   TEXT,
    grade                                    TEXT,
    amazon_now                               TEXT,
    instamart                                TEXT,
    launch_date                              TEXT,
    replacement_sku                          TEXT,
    factory                                  TEXT,
    moq                                      TEXT,
    mlt_days                                 TEXT,
    po_pending                               TEXT,
    po_delivery_date                         TEXT,
    warehouse_stock                          TEXT,
    PRIMARY KEY (batch_id, source_row_number)
);
COMMENT ON TABLE raw.sku_planning_master IS 'As received from SKU_PLANNING_MASTER. Contract: loader/contracts/SKU_PLANNING_MASTER.json';
COMMENT ON COLUMN raw.sku_planning_master.sku IS 'Source header: SKU';
COMMENT ON COLUMN raw.sku_planning_master.product_name IS 'Source header: Product Name';
COMMENT ON COLUMN raw.sku_planning_master.list_group IS 'Source header: List Group';
COMMENT ON COLUMN raw.sku_planning_master.top_40 IS 'Source header: Top 40';
COMMENT ON COLUMN raw.sku_planning_master.grade IS 'Source header: Grade';
COMMENT ON COLUMN raw.sku_planning_master.amazon_now IS 'Source header: Amazon Now';
COMMENT ON COLUMN raw.sku_planning_master.instamart IS 'Source header: Instamart';
COMMENT ON COLUMN raw.sku_planning_master.launch_date IS 'Source header: Launch Date';
COMMENT ON COLUMN raw.sku_planning_master.replacement_sku IS 'Source header: Replacement SKU';
COMMENT ON COLUMN raw.sku_planning_master.factory IS 'Source header: Factory';
COMMENT ON COLUMN raw.sku_planning_master.moq IS 'Source header: MOQ';
COMMENT ON COLUMN raw.sku_planning_master.mlt_days IS 'Source header: MLT Days';
COMMENT ON COLUMN raw.sku_planning_master.po_pending IS 'Source header: PO Pending';
COMMENT ON COLUMN raw.sku_planning_master.po_delivery_date IS 'Source header: PO Delivery Date';
COMMENT ON COLUMN raw.sku_planning_master.warehouse_stock IS 'Source header: Warehouse Stock';


CREATE TABLE IF NOT EXISTS core.dim_product_planning (
    product_planning_id    BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    as_of_date             DATE          NOT NULL,
    product_key            INTEGER       NOT NULL REFERENCES core.dim_product (product_key),
    source_sku_code        VARCHAR(60)   NOT NULL,
    list_group             VARCHAR(60),
    is_top_40              BOOLEAN       NOT NULL,
    grade                  VARCHAR(10),
    on_amazon_now          BOOLEAN       NOT NULL,
    on_instamart           BOOLEAN       NOT NULL,
    launch_date            DATE,
    replacement_sku_code   VARCHAR(60),
    factory_name           VARCHAR(200),
    moq                    INTEGER,
    mlt_days               INTEGER,
    mlt_as_written         VARCHAR(30),
    sheet_po_pending_qty   NUMERIC(14,3),
    sheet_po_delivery_date DATE,
    sheet_warehouse_stock  NUMERIC(14,3),
    batch_id               BIGINT        NOT NULL REFERENCES meta.load_batch (batch_id),
    source_row_number      INTEGER       NOT NULL
);
COMMENT ON TABLE core.dim_product_planning IS 'Planning fields per product from the team reorder sheet (SKU_PLANNING_MASTER), one row per product per sheet date; mart.v_stock_availability uses the newest sheet';
COMMENT ON COLUMN core.dim_product_planning.product_planning_id IS 'Surrogate key';
COMMENT ON COLUMN core.dim_product_planning.as_of_date IS 'Date of the sheet (the --as-of it was loaded with)';
COMMENT ON COLUMN core.dim_product_planning.product_key IS 'Product (core.dim_product); -1 when the sheet''s product code is not a known SKU';
COMMENT ON COLUMN core.dim_product_planning.source_sku_code IS 'Product code as written in the sheet';
COMMENT ON COLUMN core.dim_product_planning.list_group IS 'The sheet''s list column (e.g. TOP 42 SKU, 118 SKU, 121 SKU, 198 SKU, hold) as written';
COMMENT ON COLUMN core.dim_product_planning.is_top_40 IS 'Marked in the sheet''s top 40 column';
COMMENT ON COLUMN core.dim_product_planning.grade IS 'Grade given by the team (A, B, C ...)';
COMMENT ON COLUMN core.dim_product_planning.on_amazon_now IS 'Marked yes in the sheet''s Amazon Now column';
COMMENT ON COLUMN core.dim_product_planning.on_instamart IS 'Marked yes in the sheet''s Instamart column';
COMMENT ON COLUMN core.dim_product_planning.launch_date IS 'Launch date in the sheet (empty when the sheet has Excel''s blank date)';
COMMENT ON COLUMN core.dim_product_planning.replacement_sku_code IS 'Product that replaces this one, as written in the sheet';
COMMENT ON COLUMN core.dim_product_planning.factory_name IS 'Supplier (factory) that makes the product, as written in the sheet';
COMMENT ON COLUMN core.dim_product_planning.moq IS 'Minimum order quantity in units; empty when the sheet has none or 0';
COMMENT ON COLUMN core.dim_product_planning.mlt_days IS 'Manufacturing lead time in days; empty when the sheet has none or text';
COMMENT ON COLUMN core.dim_product_planning.mlt_as_written IS 'MLT as typed in the sheet (shows text such as NOT)';
COMMENT ON COLUMN core.dim_product_planning.sheet_po_pending_qty IS 'PO pending typed in the sheet: only to cross-check the ERP''s open purchase orders';
COMMENT ON COLUMN core.dim_product_planning.sheet_po_delivery_date IS 'PO delivery date typed in the sheet';
COMMENT ON COLUMN core.dim_product_planning.sheet_warehouse_stock IS 'Warehouse stock typed in the sheet: only to cross-check the ERP stock report';
COMMENT ON COLUMN core.dim_product_planning.batch_id IS 'Load batch the row came from (meta.load_batch): traces the row to the exact source file';
COMMENT ON COLUMN core.dim_product_planning.source_row_number IS 'Row number in the loaded file';

INSERT INTO meta.pipeline_setting (setting_key, setting_value, description) VALUES
('availability.transit_buffer_days', '15', 'Days added to each product''s MLT for transit and buffer: ideal stock = daily sales x (MLT + this) (owner, 14 Nov 2026)'),
('availability.default_mlt_days', '45', 'MLT used when the reorder sheet has none for a product'),
('availability.sales_window_days', '365', 'Days of sales (up to the end of the data) that set the daily sales rate (owner: the last 12 months)'),
('availability.excluded_channels', 'B2B,EXPORT_DIRECT,EXPORT_VIA_DILEEP,#UNKNOWN', 'Channel codes whose sales do not count towards ideal stock: B2B and export bulk orders (made to order) and sales with no known channel (owner: every channel except B2B bulk)'),
('availability.overstock_multiple', '3', 'Stock plus open orders above this many times the ideal is shown as too much stock')
ON CONFLICT (setting_key) DO NOTHING;

INSERT INTO meta.schema_version (version, migration_file, description)
VALUES ('2.18', '260_stock_availability.sql', 'Stock availability: team reorder sheet (MOQ, MLT, factory) and the ideal-stock view');
