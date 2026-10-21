-- =============================================================================
-- 080_context_registers.sql  |  Migration (schema v2.0, part 1 of 3)
-- Makes the knowledge that lives in people's heads part of the database:
-- numbered business rules, what each source file really means, the business
-- process map, every known gap, coverage per month, and column lineage.
-- Content is maintained as reviewed CSVs in seeds/ (loaded by loader.seeds).
-- Rules, processes, gaps and notes are NEVER deleted: they are retired,
-- superseded or closed, so history of decisions stays visible.
-- =============================================================================

CREATE TABLE meta.schema_version (
    version         VARCHAR(10)  NOT NULL,
    migration_file  VARCHAR(100) PRIMARY KEY,
    description     VARCHAR(300) NOT NULL,
    applied_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO meta.schema_version (version, migration_file, description) VALUES
 ('1.0','000_schemas.sql','Layered schemas'),
 ('1.0','010_meta.sql','Source registry, load audit, DQ results, settings'),
 ('1.0','015_meta_seed.sql','Registered sources and settings'),
 ('1.0','020_ref.sql','Reference and mapping tables'),
 ('1.0','030_core_dimensions.sql','Core dimensions v1 (superseded by 085)'),
 ('1.0','040_core_facts.sql','Core facts v1 (superseded by 085)'),
 ('1.0','050_seed_dim_date.sql','Calendar'),
 ('1.2','060_ref_partner_channel.sql','Partner-type to channel link'),
 ('1.3','065_meta_audit_failed_loads.sql','Audit failed loads'),
 ('1.3','070_raw_tables.sql','Raw landing tables (generated)'),
 ('2.0','080_context_registers.sql','Context registers');

-- Safety switch: until the business confirms the partner list is complete, an unlisted
-- domestic / PO name stays UNCLASSIFIED instead of being classified by elimination
-- (e.g. as an employee), so no real revenue is silently treated as internal.
INSERT INTO meta.pipeline_setting (setting_key, setting_value, description) VALUES
 ('partner_list_complete', 'false', 'true only once the business confirms ref.partner_list holds every B2B, franchise, SIS, quick-commerce, group and factory name. While false, default partner rules are not applied');

-- ---------------------------------------------------------------------------
-- Business rules
-- ---------------------------------------------------------------------------
CREATE TABLE meta.business_rule (
    rule_id              VARCHAR(10)   PRIMARY KEY CHECK (rule_id LIKE 'BR-%'),
    title                VARCHAR(150)  NOT NULL,
    statement            VARCHAR(2000) NOT NULL,
    domain               VARCHAR(30)   NOT NULL CHECK (domain IN
                            ('REVENUE','SALES','RETURNS','PARTNERS','PRODUCT','LOCATION','STOCK',
                             'PURCHASING','FULFILMENT','QUICK_COMMERCE','DATA_HANDLING','AGENTS')),
    applies_to           VARCHAR(500)  NOT NULL,     -- sources / tables / columns affected, in words
    confirmation_source  VARCHAR(20)   NOT NULL CHECK (confirmation_source IN
                            ('BUSINESS','DATA_EVIDENCE','DESIGN','DESIGN_APPROVAL')),
                            -- BUSINESS: stated by the business; DATA_EVIDENCE: verified in the data;
                            -- DESIGN: data-team design rule; DESIGN_APPROVAL: proposal approved with the design
    evidence             VARCHAR(1000),
    recorded_on          DATE          NOT NULL,
    status               VARCHAR(12)   NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','PROPOSED','SUPERSEDED','RETIRED')),
    superseded_by        VARCHAR(10)   REFERENCES meta.business_rule (rule_id),
    CONSTRAINT ck_rule_superseded CHECK ((status = 'SUPERSEDED') = (superseded_by IS NOT NULL))
);

-- ---------------------------------------------------------------------------
-- Business process map (the "bus matrix" of the target design)
-- ---------------------------------------------------------------------------
CREATE TABLE meta.business_process (
    process_code   VARCHAR(30)  PRIMARY KEY,
    process_name   VARCHAR(100) NOT NULL,
    domain         VARCHAR(30)  NOT NULL CHECK (domain IN ('SALES_DEMAND','MARKETING','SUPPLY_CHAIN','FINANCE','CUSTOMER_TEAM','AGENT_OUTPUTS')),
    table_name     VARCHAR(100) NOT NULL,          -- target table (existing or planned)
    grain          VARCHAR(200) NOT NULL,
    dimensions     VARCHAR(300) NOT NULL,
    agents         VARCHAR(200) NOT NULL,
    build_phase    VARCHAR(10)  NOT NULL CHECK (build_phase IN ('NOW','LATER')),
    coverage       VARCHAR(10)  NOT NULL CHECK (coverage IN ('HAVE','PARTIAL','GAP','N/A')),
    current_source VARCHAR(500) NOT NULL
);

-- Coverage per process per month, so a dashboard or agent says "no data" instead of showing zero.
CREATE TABLE meta.process_coverage (
    process_code   VARCHAR(30)  NOT NULL REFERENCES meta.business_process (process_code),
    period_month   DATE         NOT NULL CHECK (EXTRACT(DAY FROM period_month) = 1),
    coverage       VARCHAR(10)  NOT NULL CHECK (coverage IN ('FULL','PARTIAL','NONE')),
    sources        VARCHAR(300),
    notes          VARCHAR(500),
    refreshed_at   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (process_code, period_month)
);

-- ---------------------------------------------------------------------------
-- Gaps between the target design and today's data
-- ---------------------------------------------------------------------------
CREATE TABLE meta.data_gap (
    gap_id          VARCHAR(10)   PRIMARY KEY CHECK (gap_id LIKE 'G-%'),
    title           VARCHAR(150)  NOT NULL,
    process_code    VARCHAR(30)   REFERENCES meta.business_process (process_code),
    needed_for      VARCHAR(300)  NOT NULL,       -- tables / columns that stay empty or partial
    needed_by       VARCHAR(200)  NOT NULL,       -- agents
    how_to_fill     VARCHAR(500)  NOT NULL,
    owner           VARCHAR(20)   NOT NULL CHECK (owner IN ('BUSINESS','ERP_TEAM','DATA_TEAM')),
    priority        VARCHAR(10)   NOT NULL CHECK (priority IN ('HIGH','MEDIUM','LOW','LATER')),
    status          VARCHAR(12)   NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','IN_PROGRESS','CLOSED')),
    closed_on       DATE,
    resolution      VARCHAR(500),
    CONSTRAINT ck_gap_closed CHECK ((status = 'CLOSED') = (closed_on IS NOT NULL))
);

-- ---------------------------------------------------------------------------
-- What only the person handling a file knows
-- ---------------------------------------------------------------------------
CREATE TABLE meta.source_note (
    source_name    VARCHAR(60)   NOT NULL REFERENCES meta.source_registry (source_name),
    note_id        SMALLINT      NOT NULL CHECK (note_id > 0),
    category       VARCHAR(20)   NOT NULL CHECK (category IN
                       ('COLUMN_MEANING','TRAP','EXPORT_PROCESS','COVERAGE','LAYOUT','CONTENT')),
    source_header  VARCHAR(100),                 -- column the note is about, exactly as in the file
    note           VARCHAR(1000) NOT NULL,
    rule_id        VARCHAR(10)   REFERENCES meta.business_rule (rule_id),
    evidence       VARCHAR(500),
    status         VARCHAR(10)   NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','RETIRED')),
    PRIMARY KEY (source_name, note_id)
);

-- ---------------------------------------------------------------------------
-- Column lineage: where each derived warehouse column comes from, and which rules shape it
-- ---------------------------------------------------------------------------
CREATE TABLE meta.column_lineage (
    table_schema   VARCHAR(30)  NOT NULL,
    table_name     VARCHAR(100) NOT NULL,
    column_name    VARCHAR(100) NOT NULL,
    source_name    VARCHAR(60)  NOT NULL REFERENCES meta.source_registry (source_name),
    source_header  VARCHAR(200),                 -- file column(s), exactly as in the file
    derivation     VARCHAR(1000) NOT NULL,
    PRIMARY KEY (table_schema, table_name, column_name, source_name)
);

CREATE TABLE meta.column_rule (
    table_schema   VARCHAR(30)  NOT NULL,
    table_name     VARCHAR(100) NOT NULL,
    column_name    VARCHAR(100) NOT NULL,
    rule_id        VARCHAR(10)  NOT NULL REFERENCES meta.business_rule (rule_id),
    PRIMARY KEY (table_schema, table_name, column_name, rule_id)
);

-- ---------------------------------------------------------------------------
-- Rule links on reference data: every mapping / classification cites its rule
-- ---------------------------------------------------------------------------
ALTER TABLE ref.partner_type             ADD COLUMN rule_id VARCHAR(10) REFERENCES meta.business_rule (rule_id);
ALTER TABLE ref.partner_default_rule     ADD COLUMN rule_id VARCHAR(10) REFERENCES meta.business_rule (rule_id);
ALTER TABLE ref.partner_list             ADD COLUMN rule_id VARCHAR(10) REFERENCES meta.business_rule (rule_id);
ALTER TABLE ref.partner_type_channel     ADD COLUMN rule_id VARCHAR(10) REFERENCES meta.business_rule (rule_id);
ALTER TABLE ref.location_alias           ADD COLUMN rule_id VARCHAR(10) REFERENCES meta.business_rule (rule_id);
ALTER TABLE ref.document_prefix_location ADD COLUMN rule_id VARCHAR(10) REFERENCES meta.business_rule (rule_id);
ALTER TABLE ref.channel_alias            ADD COLUMN rule_id VARCHAR(10) REFERENCES meta.business_rule (rule_id);
ALTER TABLE ref.code_mapping             ADD COLUMN rule_id VARCHAR(10) REFERENCES meta.business_rule (rule_id);
ALTER TABLE ref.location_master          ADD COLUMN rule_id VARCHAR(10) REFERENCES meta.business_rule (rule_id);

-- Channel attributes the target design needs
ALTER TABLE ref.channel_master ADD COLUMN fulfilment_model VARCHAR(15) NOT NULL DEFAULT 'NONE'
    CHECK (fulfilment_model IN ('AMAZON_FBA','SELF_SHIP','SELLER_FLEX','MARKETPLACE','STORE','PARTNER','NONE'));
ALTER TABLE ref.channel_master ADD COLUMN is_sale_or_return BOOLEAN NOT NULL DEFAULT FALSE;

-- Locations: partner consignment stock and stock held by employees are locations too
ALTER TABLE ref.location_master DROP CONSTRAINT location_master_location_type_check;
ALTER TABLE ref.location_master ADD CONSTRAINT location_master_location_type_check CHECK (location_type IN (
    'CENTRAL_WAREHOUSE','REGIONAL_WAREHOUSE','OFFLINE_WAREHOUSE','OWN_STORE','POPUP_STORE','FRANCHISE_STORE',
    'AMAZON_FBA','QC_FEEDER_WAREHOUSE','QC_PLATFORM_FACILITY','REPAIR_DAMAGE','HEAD_OFFICE',
    'PARTNER_CONSIGNMENT','EMPLOYEE_HOLDING','OTHER'));
ALTER TABLE ref.location_master ADD COLUMN opening_date DATE;
ALTER TABLE ref.location_master ADD COLUMN closing_date DATE;
ALTER TABLE ref.location_master ADD CONSTRAINT ck_location_dates CHECK (closing_date IS NULL OR opening_date IS NULL OR closing_date >= opening_date);

-- A sale-or-return partner holds Ellementry stock at its own (virtual) location
ALTER TABLE ref.partner_list ADD COLUMN consignment_location_code VARCHAR(40) REFERENCES ref.location_master (location_code);

-- ---------------------------------------------------------------------------
-- Data dictionary  [PG-ONLY view over the catalogue; on a cloud warehouse use
-- its information_schema column comments the same way]
-- ---------------------------------------------------------------------------
CREATE VIEW meta.column_dictionary AS
SELECT c.table_schema, c.table_name, c.column_name, c.data_type, c.is_nullable,
       col_description(format('%I.%I', c.table_schema, c.table_name)::regclass, c.ordinal_position) AS business_definition,
       (SELECT string_agg(l.source_name || ': ' || coalesce(l.source_header || ' -> ', '') || l.derivation, ' | ' ORDER BY l.source_name)
          FROM meta.column_lineage l
         WHERE l.table_schema = c.table_schema AND l.table_name = c.table_name AND l.column_name = c.column_name) AS lineage,
       (SELECT string_agg(r.rule_id, ', ' ORDER BY r.rule_id)
          FROM meta.column_rule r
         WHERE r.table_schema = c.table_schema AND r.table_name = c.table_name AND r.column_name = c.column_name) AS rules
  FROM information_schema.columns c
 WHERE c.table_schema IN ('core','insight','mart');

COMMENT ON VIEW meta.column_dictionary IS 'Every warehouse column with its business definition, lineage and the business rules behind it';
