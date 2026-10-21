-- =============================================================================
-- 020_ref.sql  |  Human-maintained reference and mapping tables
--
-- Rules for every ref table:
--   * Content is edited as CSV in git, reviewed, then loaded. Never hand-edited in the DB.
--   * is_confirmed = FALSE means "proposed by the data team, not yet signed off
--     by the business". Mart views can surface unconfirmed mappings.
--   * source_value is stored exactly as it appears in the source after TRIM.
--     Matching is exact (case-sensitive) so an unexpected new value is caught
--     as UNMAPPED instead of silently matching something similar.
-- =============================================================================

-- GST state codes. ERP location names are prefixed with them ("08 Jaipur Branch").
CREATE TABLE ref.gst_state (
    gst_state_code  CHAR(2)     PRIMARY KEY,
    state_name      VARCHAR(60) NOT NULL UNIQUE
);

INSERT INTO ref.gst_state (gst_state_code, state_name) VALUES
 ('06','Haryana'), ('07','Delhi'), ('08','Rajasthan'), ('09','Uttar Pradesh'),
 ('19','West Bengal'), ('24','Gujarat'), ('27','Maharashtra'), ('29','Karnataka'),
 ('30','Goa'), ('33','Tamil Nadu'), ('36','Telangana');

-- ---------------------------------------------------------------------------
-- Locations: every place stock can sit (own warehouses, stores, Amazon FBA,
-- Blinkit feeders, Instamart facilities, repair/damage bins, head office).
-- ---------------------------------------------------------------------------
CREATE TABLE ref.location_master (
    location_code               VARCHAR(40)  PRIMARY KEY,   -- stable internal code, never reused
    erp_location_name           VARCHAR(100) UNIQUE,        -- as in ERP CHANNELNAME / stock report; NULL if not an ERP location
    location_name               VARCHAR(100) NOT NULL,
    location_type               VARCHAR(30)  NOT NULL CHECK (location_type IN (
                                    'CENTRAL_WAREHOUSE','REGIONAL_WAREHOUSE','OFFLINE_WAREHOUSE',
                                    'OWN_STORE','POPUP_STORE','FRANCHISE_STORE',
                                    'AMAZON_FBA','QC_FEEDER_WAREHOUSE','QC_PLATFORM_FACILITY',
                                    'REPAIR_DAMAGE','HEAD_OFFICE','OTHER')),
    operated_by                 VARCHAR(20)  NOT NULL CHECK (operated_by IN
                                    ('SELF','AMAZON','BLINKIT','INSTAMART','FRANCHISE','OTHER')),
    gst_state_code              CHAR(2)      REFERENCES ref.gst_state (gst_state_code),
    city                        VARCHAR(60),
    is_stock_holding            BOOLEAN      NOT NULL,
    is_sellable_stock           BOOLEAN      NOT NULL,     -- counts toward sellable inventory in Stock AI
    inventory_system_of_record  VARCHAR(20)  NOT NULL CHECK (inventory_system_of_record IN
                                    ('ERP','BLINKIT','INSTAMART','AMAZON','NONE')),
    is_active                   BOOLEAN      NOT NULL DEFAULT TRUE,
    is_confirmed                BOOLEAN      NOT NULL DEFAULT FALSE,
    notes                       VARCHAR(500),
    CONSTRAINT ck_location_sellable_needs_stock CHECK (is_stock_holding OR NOT is_sellable_stock)
);

-- Crosswalk: the many spellings of one location across sources
-- e.g. ERP_STOCK_TRANSFER_OUT / CONTACTNAME / 'Dileep Essentials Pvt Ltd Ahmedabad FBA AMD2' -> AMD2 FBA
CREATE TABLE ref.location_alias (
    source_name     VARCHAR(60)  NOT NULL REFERENCES meta.source_registry (source_name),
    source_field    VARCHAR(60)  NOT NULL,
    source_value    VARCHAR(200) NOT NULL,
    location_code   VARCHAR(40)  NOT NULL REFERENCES ref.location_master (location_code),
    is_confirmed    BOOLEAN      NOT NULL DEFAULT FALSE,
    notes           VARCHAR(500),
    PRIMARY KEY (source_name, source_field, source_value)
);

-- Interim rule for documents whose location exists only inside the document
-- number (stock transfers, returns). Longest matching prefix wins.
-- To be retired once the ERP exports carry an explicit location column.
CREATE TABLE ref.document_prefix_location (
    source_name     VARCHAR(60) NOT NULL REFERENCES meta.source_registry (source_name),
    doc_prefix      VARCHAR(30) NOT NULL,
    location_code   VARCHAR(40) NOT NULL REFERENCES ref.location_master (location_code),
    is_confirmed    BOOLEAN     NOT NULL DEFAULT FALSE,
    notes           VARCHAR(500),
    PRIMARY KEY (source_name, doc_prefix)
);

-- ---------------------------------------------------------------------------
-- Sales channels
-- ---------------------------------------------------------------------------
CREATE TABLE ref.channel_master (
    channel_code      VARCHAR(40) PRIMARY KEY,           -- e.g. AMAZON_FBA
    channel_name      VARCHAR(60) NOT NULL,              -- e.g. Amazon
    sub_channel_name  VARCHAR(60) NOT NULL,              -- e.g. FBA
    channel_group     VARCHAR(20) NOT NULL CHECK (channel_group IN
                         ('MARKETPLACE','D2C_WEBSITE','OFFLINE_RETAIL','B2B','QUICK_COMMERCE','INTERNAL')),
    is_active         BOOLEAN     NOT NULL DEFAULT TRUE,
    is_confirmed      BOOLEAN     NOT NULL DEFAULT FALSE,
    notes             VARCHAR(500)
);

-- Maps raw values to a channel. Several fields feed this (retail Payment
-- mode/Account, retail CONTACTNAME, WMS Site Location, return CONTACTNAME).
-- priority decides which field wins when a row matches more than one.
CREATE TABLE ref.channel_alias (
    source_name     VARCHAR(60)  NOT NULL REFERENCES meta.source_registry (source_name),
    source_field    VARCHAR(60)  NOT NULL,
    source_value    VARCHAR(200) NOT NULL,
    channel_code    VARCHAR(40)  NOT NULL REFERENCES ref.channel_master (channel_code),
    priority        SMALLINT     NOT NULL DEFAULT 100 CHECK (priority > 0),  -- lower = stronger
    is_confirmed    BOOLEAN      NOT NULL DEFAULT FALSE,
    notes           VARCHAR(500),
    PRIMARY KEY (source_name, source_field, source_value)
);

-- ---------------------------------------------------------------------------
-- Business partners (counterparties on invoices, returns and POs)
-- ---------------------------------------------------------------------------
CREATE TABLE ref.partner_type (
    partner_type       VARCHAR(30)  PRIMARY KEY,
    description        VARCHAR(300) NOT NULL,
    is_internal        BOOLEAN      NOT NULL,   -- stock moving within Ellementry, not a sale to an outside party
    is_related_party   BOOLEAN      NOT NULL,   -- Dileep group entity
    is_sale_or_return  BOOLEAN      NOT NULL    -- partner returns unsold stock: invoice is provisional, stock may come back
);

-- Business rules confirmed by the business:
--  * In Domestic Sales only true B2B invoices are final. Franchise stores,
--    quick-commerce and SIS (shop-in-shop) are supplied sale-or-return.
--    Their billing names will be supplied by the business for ref.partner_list.
--  * Exports are routed through Dileep group entities and billed cost-to-cost.
INSERT INTO ref.partner_type (partner_type, description, is_internal, is_related_party, is_sale_or_return) VALUES
 ('D2C_CHANNEL_ACCOUNT',    'ERP pseudo-customer on retail invoices (Shopify_Customer, Amazon Website, Amazon FBA and own-store contacts)', FALSE, FALSE, FALSE),
 ('B2B_CUSTOMER',           'Outright B2B / wholesale sale. Final: not returned for being unsold', FALSE, FALSE, FALSE),
 ('FRANCHISE_PARTNER',      'Franchise store supplied sale-or-return', FALSE, FALSE, TRUE),
 ('SIS_PARTNER',            'Shop-in-shop counter inside a retailer, supplied sale-or-return', FALSE, FALSE, TRUE),
 ('QUICK_COMMERCE_PARTNER', 'Quick-commerce entity (e.g. Kiranakart Technologies = Blinkit), supplied sale-or-return', FALSE, FALSE, TRUE),
 ('GROUP_EXPORT',           'Dileep group entity billed cost-to-cost for export orders (exports are routed through Dileep)', FALSE, TRUE, FALSE),
 ('EXPORT_CUSTOMER',        'Overseas customer billed directly', FALSE, FALSE, FALSE),
 ('EMPLOYEE',               'Company employee taking stock out for exhibitions or demos and bringing it back', TRUE, FALSE, FALSE),
 ('FACTORY_SUPPLIER',       'Factory that goods are purchased from', FALSE, FALSE, FALSE),
 ('RETURN_SOURCE',          'Non-factory party on the PO report: a return-inward, not a purchase', FALSE, FALSE, FALSE),
 ('UNCLASSIFIED',           'Not yet classified. Must be zero before a mart is trusted', FALSE, FALSE, FALSE);

-- Explicit list of known partners. partner_role separates the same legal name
-- appearing as a customer on invoices and as a supplier on POs.
CREATE TABLE ref.partner_list (
    partner_name    VARCHAR(200) NOT NULL,     -- exactly as ERP CONTACTNAME
    partner_role    VARCHAR(10)  NOT NULL CHECK (partner_role IN ('CUSTOMER','SUPPLIER')),
    partner_type    VARCHAR(30)  NOT NULL REFERENCES ref.partner_type (partner_type),
    partner_group   VARCHAR(100),              -- groups branches of one account under one name
    is_confirmed    BOOLEAN      NOT NULL DEFAULT FALSE,
    notes           VARCHAR(500),
    PRIMARY KEY (partner_name, partner_role)
);

-- What an UNLISTED name means, per source (the "classification by elimination" rule).
-- Every partner classified by this rule is reported by a data-quality WARN on
-- each load, so a genuinely new B2B account is noticed instead of being
-- silently treated as an employee.
CREATE TABLE ref.partner_default_rule (
    source_name           VARCHAR(60)  PRIMARY KEY REFERENCES meta.source_registry (source_name),
    partner_role          VARCHAR(10)  NOT NULL CHECK (partner_role IN ('CUSTOMER','SUPPLIER')),
    default_partner_type  VARCHAR(30)  NOT NULL REFERENCES ref.partner_type (partner_type),
    rationale             VARCHAR(500) NOT NULL
);

INSERT INTO ref.partner_default_rule (source_name, partner_role, default_partner_type, rationale) VALUES
 ('ERP_RETAIL_SALES',    'CUSTOMER', 'D2C_CHANNEL_ACCOUNT', 'Every retail invoice is a genuine D2C / marketplace / store sale (business-confirmed)'),
 ('ERP_RETAIL_RETURN',   'CUSTOMER', 'D2C_CHANNEL_ACCOUNT', 'Every retail return is a genuine customer return, incl. those received at Amazon FBA (business-confirmed)'),
 ('ERP_DOMESTIC_SALES',  'CUSTOMER', 'EMPLOYEE',            'Any domestic name not on the business-account list is an employee (business-confirmed)'),
 ('ERP_DOMESTIC_RETURN', 'CUSTOMER', 'EMPLOYEE',            'Any domestic name not on the business-account list is an employee (business-confirmed)'),
 ('ERP_PURCHASE_ORDER',  'SUPPLIER', 'RETURN_SOURCE',       'Any PO counterparty not on the factory list is a return-inward (business-confirmed)');

-- ---------------------------------------------------------------------------
-- Generic code standardisation (statuses, payment types, ...)
-- ---------------------------------------------------------------------------
CREATE TABLE ref.code_mapping (
    domain          VARCHAR(40)  NOT NULL,   -- e.g. SHIPMENT_STATUS, PO_STATUS, PAYMENT_TYPE
    source_name     VARCHAR(60)  NOT NULL REFERENCES meta.source_registry (source_name),
    source_value    VARCHAR(200) NOT NULL,
    standard_value  VARCHAR(60)  NOT NULL,
    is_confirmed    BOOLEAN      NOT NULL DEFAULT FALSE,
    notes           VARCHAR(500),
    PRIMARY KEY (domain, source_name, source_value)
);
