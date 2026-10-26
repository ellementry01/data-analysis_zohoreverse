-- =============================================================================
-- 010_meta.sql  |  Source registry, load audit, data-quality log, settings
-- =============================================================================

-- Every source file type the pipeline accepts. Nothing loads unless registered.
-- date_format is stated explicitly per source and NEVER inferred: the WMS
-- dispatch export uses M/D/YYYY while ERP text dates use DD/MM/YYYY, so
-- guessing would silently swap day and month for any date with day <= 12.
CREATE TABLE meta.source_registry (
    source_name     VARCHAR(60)  PRIMARY KEY,
    source_system   VARCHAR(30)  NOT NULL
        CHECK (source_system IN ('ERP','WMS','BLINKIT','INSTAMART','PRODUCT_MASTER')),
    description     VARCHAR(500) NOT NULL,
    grain           VARCHAR(300) NOT NULL,
    load_type       VARCHAR(25)  NOT NULL
        CHECK (load_type IN ('TRANSACTIONAL','POINT_IN_TIME_SNAPSHOT','STATE_SNAPSHOT','MASTER')),
    natural_key     VARCHAR(300) NOT NULL,
    date_format     VARCHAR(60)  NOT NULL,
    known_issues    VARCHAR(1000),
    is_active       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- One row per file loaded. Every raw/stg/core row carries the batch_id it came from.
CREATE TABLE meta.load_batch (
    batch_id        BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_name     VARCHAR(60)  NOT NULL REFERENCES meta.source_registry (source_name),
    file_name       VARCHAR(300) NOT NULL,
    file_sha256     CHAR(64)     NOT NULL,
    period_start    DATE,                 -- transactional files: first business date covered
    period_end      DATE,                 -- transactional files: last business date kept (cut-off applied)
    as_of_date      DATE,                 -- snapshot / state / master files: the "as of" date
    rows_read       INTEGER      CHECK (rows_read     >= 0),
    rows_loaded     INTEGER      CHECK (rows_loaded   >= 0),
    rows_rejected   INTEGER      CHECK (rows_rejected >= 0),
    status          VARCHAR(12)  NOT NULL DEFAULT 'STARTED'
        CHECK (status IN ('STARTED','LOADED','FAILED','SUPERSEDED')),
    loaded_by       VARCHAR(100) NOT NULL,
    started_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at     TIMESTAMP,
    notes           VARCHAR(1000),
    CONSTRAINT ck_load_batch_period CHECK (period_start IS NULL OR period_end IS NULL OR period_end >= period_start),
    CONSTRAINT ck_load_batch_dated  CHECK (period_start IS NOT NULL OR as_of_date IS NOT NULL),
    CONSTRAINT ck_load_batch_finish CHECK (finished_at IS NULL OR finished_at >= started_at)
);

-- The same file (same bytes) can never be loaded twice while a live load of it exists.
-- A FAILED load can be retried.  [PG-ONLY: partial unique index. On Snowflake /
-- BigQuery enforce this check inside the loader instead.]
CREATE UNIQUE INDEX uq_load_batch_live_file
    ON meta.load_batch (source_name, file_sha256)
    WHERE status IN ('STARTED','LOADED');

CREATE INDEX ix_load_batch_source ON meta.load_batch (source_name, status);

-- Results of every automated data-quality check, per batch.
CREATE TABLE meta.dq_check_result (
    dq_result_id     BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    batch_id         BIGINT        REFERENCES meta.load_batch (batch_id),
    check_name       VARCHAR(100)  NOT NULL,
    target_table     VARCHAR(100)  NOT NULL,
    severity         VARCHAR(5)    NOT NULL CHECK (severity IN ('ERROR','WARN')),
    outcome          VARCHAR(4)    NOT NULL CHECK (outcome  IN ('PASS','FAIL')),
    failed_row_count INTEGER       NOT NULL DEFAULT 0 CHECK (failed_row_count >= 0),
    details          VARCHAR(4000),
    checked_at       TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX ix_dq_check_result_batch ON meta.dq_check_result (batch_id);

-- Pipeline parameters. The 15-Sep cut-off lives here, never hard-coded in SQL.
CREATE TABLE meta.pipeline_setting (
    setting_key    VARCHAR(60)  PRIMARY KEY,
    setting_value  VARCHAR(200) NOT NULL,
    description    VARCHAR(500) NOT NULL,
    updated_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);
