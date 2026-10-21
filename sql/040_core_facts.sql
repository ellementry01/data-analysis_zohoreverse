-- =============================================================================
-- 040_core_facts.sql  |  Fact tables
--
-- Conventions
--   * Every fact states its grain and has a UNIQUE natural key built from
--     SOURCE values (document number, source SKU text, line_occurrence).
--     line_occurrence numbers repeated doc+SKU pairs (they exist: 2 in the
--     inward transfer sample), so real rows are never rejected as duplicates.
--   * source_sku_code keeps the SKU exactly as received, so rows that map to
--     the Unknown product (-1) can still be traced and fixed.
--   * Quantities are stored POSITIVE; direction/meaning comes from the fact
--     itself (sale, return, transfer OUT/IN). ERP negative outward quantities
--     are flipped in staging.
--   * Amounts are INR, NUMERIC(14,2). Timestamps are IST without time zone.
--   * Business flags (revenue or not, internal or not) are NOT stored on
--     facts. They come from dim_partner / dim_channel at query time, so a
--     classification fix in ref corrects all history with no fact reload.
--   * No customer PII (names, phones, emails, street addresses) in core.
--     Only pincode / city / state for geography.
--   * Lineage on every row: batch_id + source_row_number.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- 1. Sales lines (ERP invoices = book of record for company sales)
--    Grain: one row per invoice line.  Serves: Stock AI (demand), Ops AI, Exec
-- ---------------------------------------------------------------------------
CREATE TABLE core.fact_sales_line (
    sales_line_id        BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_name          VARCHAR(60)   NOT NULL REFERENCES meta.source_registry (source_name)
                         CHECK (source_name IN ('ERP_RETAIL_SALES','ERP_DOMESTIC_SALES')),
    bill_number          VARCHAR(60)   NOT NULL,
    source_sku_code      VARCHAR(60)   NOT NULL,
    line_occurrence      SMALLINT      NOT NULL DEFAULT 1 CHECK (line_occurrence >= 1),
    bill_date_key        INTEGER       NOT NULL REFERENCES core.dim_date (date_key),
    bill_datetime        TIMESTAMP,
    order_number         VARCHAR(100),                 -- ERP ORDER NUMBER / RETAILORDERNUM
    order_date_key       INTEGER       REFERENCES core.dim_date (date_key),
    external_order_ref   VARCHAR(100),                 -- DOCREFNUM: marketplace / website order id
    product_key          INTEGER       NOT NULL REFERENCES core.dim_product (product_key),
    location_key         SMALLINT      NOT NULL REFERENCES core.dim_location (location_key),  -- billing / fulfilling location
    channel_key          SMALLINT      NOT NULL REFERENCES core.dim_channel (channel_key),
    partner_key          INTEGER       NOT NULL REFERENCES core.dim_partner (partner_key),
    payment_mode_raw     VARCHAR(200),
    courier_name         VARCHAR(100),
    awb_number           VARCHAR(60),
    ship_to_pincode      VARCHAR(10),
    ship_to_city         VARCHAR(80),
    ship_to_state_code   VARCHAR(5),
    quantity             NUMERIC(14,3) NOT NULL CHECK (quantity > 0),
    unit_rate            NUMERIC(14,2),
    unit_mrp             NUMERIC(14,2) CHECK (unit_mrp >= 0),
    gross_amount         NUMERIC(14,2),               -- before discount
    discount_amount      NUMERIC(14,2) CHECK (discount_amount >= 0),
    taxable_amount       NUMERIC(14,2) CHECK (taxable_amount >= 0),  -- NULL allowed: 209 domestic lines blank at source (DQ WARN)
    igst_amount          NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (igst_amount >= 0),
    cgst_amount          NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (cgst_amount >= 0),
    sgst_amount          NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (sgst_amount >= 0),
    cess_amount          NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (cess_amount >= 0),
    other_charge_amount  NUMERIC(14,2) NOT NULL DEFAULT 0,
    line_total_amount    NUMERIC(14,2),               -- as reported by ERP
    unit_cost            NUMERIC(14,2) CHECK (unit_cost >= 0),       -- ERP Cost Rate (sparse)
    batch_id             BIGINT        NOT NULL REFERENCES meta.load_batch (batch_id),
    source_row_number    INTEGER       NOT NULL,
    loaded_at            TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_fact_sales_line UNIQUE (source_name, bill_number, source_sku_code, line_occurrence)
);
CREATE INDEX ix_fact_sales_line_date    ON core.fact_sales_line (bill_date_key);
CREATE INDEX ix_fact_sales_line_product ON core.fact_sales_line (product_key, bill_date_key);
CREATE INDEX ix_fact_sales_line_bill    ON core.fact_sales_line (bill_number);

-- ---------------------------------------------------------------------------
-- 2. Sales return lines
--    Grain: one row per return / credit-note line.  Serves: Stock AI, Ops AI
-- ---------------------------------------------------------------------------
CREATE TABLE core.fact_sales_return_line (
    return_line_id           BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_name              VARCHAR(60)   NOT NULL REFERENCES meta.source_registry (source_name)
                             CHECK (source_name IN ('ERP_RETAIL_RETURN','ERP_DOMESTIC_RETURN')),
    return_number            VARCHAR(60)   NOT NULL,   -- retail: RETURNNUM; domestic: credit note BILLNUM
    source_sku_code          VARCHAR(60)   NOT NULL,
    line_occurrence          SMALLINT      NOT NULL DEFAULT 1 CHECK (line_occurrence >= 1),
    return_date_key          INTEGER       NOT NULL REFERENCES core.dim_date (date_key),
    goods_receipt_number     VARCHAR(60),               -- domestic: RTNFROMCUST
    original_bill_number     VARCHAR(60),
    original_bill_date_key   INTEGER       REFERENCES core.dim_date (date_key),
    original_sales_line_id   BIGINT        REFERENCES core.fact_sales_line (sales_line_id),  -- resolved when the original sale is loaded
    external_order_ref       VARCHAR(100),
    product_key              INTEGER       NOT NULL REFERENCES core.dim_product (product_key),
    receiving_location_key   SMALLINT      NOT NULL REFERENCES core.dim_location (location_key),
    channel_key              SMALLINT      NOT NULL REFERENCES core.dim_channel (channel_key),
    partner_key              INTEGER       NOT NULL REFERENCES core.dim_partner (partner_key),
    quantity                 NUMERIC(14,3) NOT NULL CHECK (quantity > 0),
    unit_rate                NUMERIC(14,2),
    discount_amount          NUMERIC(14,2) CHECK (discount_amount >= 0),
    taxable_amount           NUMERIC(14,2) CHECK (taxable_amount >= 0),
    igst_amount              NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (igst_amount >= 0),
    cgst_amount              NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (cgst_amount >= 0),
    sgst_amount              NUMERIC(14,2) NOT NULL DEFAULT 0 CHECK (sgst_amount >= 0),
    other_charge_amount      NUMERIC(14,2) NOT NULL DEFAULT 0,
    batch_id                 BIGINT        NOT NULL REFERENCES meta.load_batch (batch_id),
    source_row_number        INTEGER       NOT NULL,
    loaded_at                TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_fact_sales_return_line UNIQUE (source_name, return_number, source_sku_code, line_occurrence)
);
CREATE INDEX ix_fact_sales_return_date     ON core.fact_sales_return_line (return_date_key);
CREATE INDEX ix_fact_sales_return_origbill ON core.fact_sales_return_line (original_bill_number);

-- ---------------------------------------------------------------------------
-- 3. Stock transfer lines (both directions)
--    Grain: one row per transfer document line.  Serves: Stock AI, Ops AI
--    In-transit = OUT lines not yet matched by IN lines (linked via
--    linked_outward_document + SKU); computed in mart.
-- ---------------------------------------------------------------------------
CREATE TABLE core.fact_stock_transfer_line (
    transfer_line_id         BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_name              VARCHAR(60)   NOT NULL REFERENCES meta.source_registry (source_name)
                             CHECK (source_name IN ('ERP_STOCK_TRANSFER_OUT','ERP_STOCK_TRANSFER_IN')),
    document_number          VARCHAR(60)   NOT NULL,
    source_sku_code          VARCHAR(60)   NOT NULL,
    line_occurrence          SMALLINT      NOT NULL DEFAULT 1 CHECK (line_occurrence >= 1),
    movement_direction       CHAR(3)       NOT NULL CHECK (movement_direction IN ('OUT','IN')),
    document_date_key        INTEGER       NOT NULL REFERENCES core.dim_date (date_key),
    linked_outward_document  VARCHAR(60),               -- IN rows: REFDOCNUM1 = outward DOCNUM
    from_location_key        SMALLINT      NOT NULL REFERENCES core.dim_location (location_key),
    to_location_key          SMALLINT      NOT NULL REFERENCES core.dim_location (location_key),
    product_key              INTEGER       NOT NULL REFERENCES core.dim_product (product_key),
    quantity                 NUMERIC(14,3) NOT NULL CHECK (quantity > 0),
    unit_rate                NUMERIC(14,2) CHECK (unit_rate >= 0),
    transfer_value           NUMERIC(14,2) CHECK (transfer_value >= 0),
    document_status          VARCHAR(20),
    batch_id                 BIGINT        NOT NULL REFERENCES meta.load_batch (batch_id),
    source_row_number        INTEGER       NOT NULL,
    loaded_at                TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_fact_stock_transfer_line UNIQUE (source_name, document_number, source_sku_code, line_occurrence),
    CONSTRAINT ck_transfer_direction_source CHECK (
        (source_name = 'ERP_STOCK_TRANSFER_OUT' AND movement_direction = 'OUT')
     OR (source_name = 'ERP_STOCK_TRANSFER_IN'  AND movement_direction = 'IN')),
    CONSTRAINT ck_transfer_distinct_locations CHECK (
        from_location_key <> to_location_key OR from_location_key = -1)
);
CREATE INDEX ix_fact_transfer_link    ON core.fact_stock_transfer_line (linked_outward_document, source_sku_code);
CREATE INDEX ix_fact_transfer_date    ON core.fact_stock_transfer_line (document_date_key);

-- ---------------------------------------------------------------------------
-- 4. Purchase order lines (accumulating snapshot: latest state of each line)
--    Grain: one row per PO line.  Serves: Stock AI (replenishment, lead time)
--    Each new PO export REPLACES the state; history of exports stays in raw.
-- ---------------------------------------------------------------------------
CREATE TABLE core.fact_purchase_order_line (
    po_line_id               BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    po_number                VARCHAR(60)   NOT NULL,
    source_sku_code          VARCHAR(60)   NOT NULL,
    line_occurrence          SMALLINT      NOT NULL DEFAULT 1 CHECK (line_occurrence >= 1),
    po_date_key              INTEGER       NOT NULL REFERENCES core.dim_date (date_key),
    due_date_key             INTEGER       REFERENCES core.dim_date (date_key),
    partner_key              INTEGER       NOT NULL REFERENCES core.dim_partner (partner_key),  -- role SUPPLIER; type says purchase vs return-inward
    product_key              INTEGER       NOT NULL REFERENCES core.dim_product (product_key),
    order_qty                NUMERIC(14,3) NOT NULL CHECK (order_qty > 0),
    grn_qty                  NUMERIC(14,3) CHECK (grn_qty >= 0),
    returned_to_supplier_qty NUMERIC(14,3) CHECK (returned_to_supplier_qty >= 0),
    pending_qty              NUMERIC(14,3),            -- can be negative (excess received): kept as reported
    purchase_price           NUMERIC(14,2) CHECK (purchase_price >= 0),
    purchase_amount          NUMERIC(14,2),
    returned_value           NUMERIC(14,2),
    grn_number               VARCHAR(60),
    grn_date_key             INTEGER       REFERENCES core.dim_date (date_key),
    po_status                VARCHAR(12)   NOT NULL CHECK (po_status IN
                                ('OPEN','IN_PROGRESS','OVERDUE','RECEIVED','CLOSED','CANCELLED','UNMAPPED')),
    po_status_raw            VARCHAR(40)   NOT NULL,
    as_of_date               DATE          NOT NULL,   -- date of the export this state came from
    batch_id                 BIGINT        NOT NULL REFERENCES meta.load_batch (batch_id),
    source_row_number        INTEGER       NOT NULL,
    loaded_at                TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_fact_purchase_order_line UNIQUE (po_number, source_sku_code, line_occurrence),
    CONSTRAINT ck_po_grn_after_po CHECK (grn_date_key IS NULL OR grn_date_key >= po_date_key)
);
CREATE INDEX ix_fact_po_product ON core.fact_purchase_order_line (product_key, po_status);

-- ---------------------------------------------------------------------------
-- 5. Shipments (WMS order fulfilment)
--    Grain: one row per outbound delivery.  Serves: Ops AI (SLA, RTO, courier)
--    Durations (order->ship, ship->deliver) are derived in mart, not stored.
-- ---------------------------------------------------------------------------
CREATE TABLE core.fact_shipment (
    shipment_id                BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    outbound_delivery_number   VARCHAR(40)   NOT NULL UNIQUE,
    wms_order_number           VARCHAR(40)   NOT NULL,
    external_order_number      VARCHAR(100),
    invoice_number             VARCHAR(60),             -- joins to fact_sales_line.bill_number
    channel_key                SMALLINT      NOT NULL REFERENCES core.dim_channel (channel_key),
    fulfilment_location_key    SMALLINT      NOT NULL REFERENCES core.dim_location (location_key),
    payment_type               VARCHAR(10)   CHECK (payment_type IN ('COD','PREPAID','OTHER')),
    transporter_name           VARCHAR(100),
    tracking_number            VARCHAR(60),
    shipment_status            VARCHAR(20)   NOT NULL,   -- standardised via ref.code_mapping
    shipment_status_raw        VARCHAR(60)   NOT NULL,
    transporter_status         VARCHAR(60),
    transporter_remarks        VARCHAR(300),
    is_rto                     BOOLEAN       NOT NULL,
    is_on_hold                 BOOLEAN       NOT NULL DEFAULT FALSE,
    order_datetime             TIMESTAMP     NOT NULL,
    pick_datetime              TIMESTAMP,
    pack_datetime              TIMESTAMP,
    sortation_datetime         TIMESTAMP,
    ship_datetime              TIMESTAMP,
    delivery_datetime          TIMESTAMP,
    ship_by_datetime           TIMESTAMP,
    order_date_key             INTEGER       NOT NULL REFERENCES core.dim_date (date_key),
    ship_date_key              INTEGER       REFERENCES core.dim_date (date_key),
    delivery_date_key          INTEGER       REFERENCES core.dim_date (date_key),
    delivery_qty               NUMERIC(14,3) CHECK (delivery_qty >= 0),
    picked_qty                 NUMERIC(14,3) CHECK (picked_qty >= 0),
    box_count                  SMALLINT      CHECK (box_count >= 0),
    weight_kg                  NUMERIC(10,3) CHECK (weight_kg >= 0),
    length_cm                  NUMERIC(10,2) CHECK (length_cm >= 0),
    breadth_cm                 NUMERIC(10,2) CHECK (breadth_cm >= 0),
    height_cm                  NUMERIC(10,2) CHECK (height_cm >= 0),
    destination_pincode        VARCHAR(10),
    batch_id                   BIGINT        NOT NULL REFERENCES meta.load_batch (batch_id),
    source_row_number          INTEGER       NOT NULL,
    loaded_at                  TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_fact_shipment_invoice ON core.fact_shipment (invoice_number);
CREATE INDEX ix_fact_shipment_order   ON core.fact_shipment (order_date_key);

-- SKU detail of a shipment. The WMS puts several SKUs in one cell with one
-- combined quantity, so per-SKU quantity is taken from the ERP invoice line
-- when the invoice matches; otherwise it stays NULL (never guessed).
CREATE TABLE core.bridge_shipment_sku (
    shipment_id       BIGINT        NOT NULL REFERENCES core.fact_shipment (shipment_id),
    source_sku_code   VARCHAR(60)   NOT NULL,
    product_key       INTEGER       NOT NULL REFERENCES core.dim_product (product_key),
    quantity          NUMERIC(14,3) CHECK (quantity > 0),
    quantity_source   VARCHAR(20)   NOT NULL CHECK (quantity_source IN ('SINGLE_SKU_ROW','INVOICE_LINE','UNALLOCATED')),
    CONSTRAINT pk_bridge_shipment_sku PRIMARY KEY (shipment_id, source_sku_code),
    CONSTRAINT ck_bridge_qty_source CHECK ((quantity_source = 'UNALLOCATED') = (quantity IS NULL))
);

-- ---------------------------------------------------------------------------
-- 6. Quick-commerce sell-out (platform -> consumer). NOT company revenue:
--    company revenue is the ERP invoice. Kept separate so the two can never
--    be summed together by accident. Used for true consumer demand.
--    Grain: one row per platform x date x platform store x SKU.
-- ---------------------------------------------------------------------------
CREATE TABLE core.fact_platform_sellout (
    sellout_id           BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_name          VARCHAR(60)   NOT NULL REFERENCES meta.source_registry (source_name)
                         CHECK (source_name IN ('BLINKIT_SALES','INSTAMART_SALES')),
    order_date_key       INTEGER       NOT NULL REFERENCES core.dim_date (date_key),
    platform_store_code  VARCHAR(60)   NOT NULL,   -- Instamart STORE_ID; Blinkit supply city (no store id in export)
    source_sku_code      VARCHAR(60)   NOT NULL,
    channel_key          SMALLINT      NOT NULL REFERENCES core.dim_channel (channel_key),
    product_key          INTEGER       NOT NULL REFERENCES core.dim_product (product_key),
    platform_item_id     VARCHAR(40),
    city                 VARCHAR(80)   NOT NULL,
    units_sold           NUMERIC(14,3) NOT NULL CHECK (units_sold >= 0),
    combo_units_sold     NUMERIC(14,3) CHECK (combo_units_sold >= 0),
    order_count          INTEGER       CHECK (order_count >= 0),   -- Blinkit only
    mrp_value            NUMERIC(14,2) CHECK (mrp_value >= 0),
    selling_value        NUMERIC(14,2) CHECK (selling_value >= 0), -- Blinkit selling price x qty
    gmv_reported         NUMERIC(14,2) CHECK (gmv_reported >= 0),  -- Instamart GMV as reported
    tax_amount           NUMERIC(14,2) CHECK (tax_amount >= 0),
    batch_id             BIGINT        NOT NULL REFERENCES meta.load_batch (batch_id),
    loaded_at            TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_fact_platform_sellout UNIQUE (source_name, order_date_key, platform_store_code, source_sku_code)
);

-- ---------------------------------------------------------------------------
-- 7. Inventory snapshots (periodic snapshot)
--    Grain: one row per snapshot date x source location x SKU, NON-ZERO rows
--    only. A (location, SKU) absent from a loaded snapshot = zero stock.
--    The same physical stock can be reported by two systems (ERP location
--    "27 Blinkit - Pune P2" and Blinkit's own "Pune P2 - Feeder"). Both are
--    kept; mart counts each location once, from its
--    dim_location.inventory_system_of_record, and reports the difference.
-- ---------------------------------------------------------------------------
CREATE TABLE core.fact_inventory_snapshot (
    inventory_snapshot_id  BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_name            VARCHAR(60)   NOT NULL REFERENCES meta.source_registry (source_name)
                           CHECK (source_name IN ('ERP_INVENTORY_SNAPSHOT','BLINKIT_INVENTORY','INSTAMART_INVENTORY')),
    snapshot_date_key      INTEGER       NOT NULL REFERENCES core.dim_date (date_key),
    source_location_value  VARCHAR(200)  NOT NULL,
    source_sku_code        VARCHAR(60)   NOT NULL,
    location_key           SMALLINT      NOT NULL REFERENCES core.dim_location (location_key),
    product_key            INTEGER       NOT NULL REFERENCES core.dim_product (product_key),
    on_hand_qty            NUMERIC(14,3) NOT NULL,     -- no >= 0 check: negative ERP stock is real and flagged by DQ
    sellable_qty           NUMERIC(14,3),
    unsellable_qty         NUMERIC(14,3),
    in_transit_qty         NUMERIC(14,3),
    incoming_qty           NUMERIC(14,3),
    damaged_qty            NUMERIC(14,3),
    lost_qty               NUMERIC(14,3),
    expired_qty            NUMERIC(14,3),
    recalled_qty           NUMERIC(14,3),
    platform_net_scheduled_qty NUMERIC(14,3),          -- Blinkit field; meaning unconfirmed, excluded from metrics
    unit_mrp               NUMERIC(14,2) CHECK (unit_mrp >= 0),
    batch_id               BIGINT        NOT NULL REFERENCES meta.load_batch (batch_id),
    loaded_at              TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_fact_inventory_snapshot UNIQUE (source_name, snapshot_date_key, source_location_value, source_sku_code)
);
CREATE INDEX ix_fact_inventory_loc_prod ON core.fact_inventory_snapshot (snapshot_date_key, location_key, product_key);
