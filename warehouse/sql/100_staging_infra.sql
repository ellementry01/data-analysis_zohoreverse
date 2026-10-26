-- =============================================================================
-- 100_staging_infra.sql  |  Migration (schema v2.1)
-- What the transform (raw -> stg -> core -> mart) needs:
--   * a run log, with data-quality results tied to each run
--   * two movement types for stock going to / coming from a counterparty
--     that is not classified yet (so the ledger never guesses a sale)
--   * parsing helpers that return NULL instead of failing on bad text  [PG-ONLY]
-- =============================================================================

CREATE TABLE meta.transform_run (
    transform_run_id  BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    status            VARCHAR(10)  NOT NULL DEFAULT 'RUNNING' CHECK (status IN ('RUNNING','SUCCEEDED','FAILED')),
    period_start      DATE         NOT NULL,
    period_end        DATE         NOT NULL,
    partner_list_complete BOOLEAN  NOT NULL,
    started_by        VARCHAR(100) NOT NULL,
    started_at        TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at       TIMESTAMP,
    row_counts        VARCHAR(4000),          -- JSON text: rows per core table after the run
    notes             VARCHAR(2000),
    CONSTRAINT ck_transform_run_finished CHECK ((status = 'RUNNING') = (finished_at IS NULL))
);

ALTER TABLE meta.dq_check_result ADD COLUMN transform_run_id BIGINT REFERENCES meta.transform_run (transform_run_id);
CREATE INDEX ix_dq_check_result_run ON meta.dq_check_result (transform_run_id);

INSERT INTO core.dim_movement_type (movement_type_key, movement_code, movement_name, stock_effect, description) VALUES
 (17,'ISSUE_UNCLASSIFIED','Issued to unclassified counterparty',-1,'Stock left the location on an invoice to a counterparty not yet classified (sale, consignment or employee). Re-classified automatically once the partner list is complete'),
 (18,'RECEIPT_UNCLASSIFIED','Received from unclassified counterparty',1,'Stock received back on a credit note from a counterparty not yet classified');

INSERT INTO meta.pipeline_setting (setting_key, setting_value, description) VALUES
 ('employee_holding_location', 'EMPLOYEE_EXHIBITION', 'Location code that holds stock issued to employees for exhibitions (BR-029)');

-- ---------------------------------------------------------------------------
-- Parsing helpers: NULL on anything that is not exactly the expected shape.
-- Every NULL produced from non-empty text is counted by a data-quality check.
-- ---------------------------------------------------------------------------
CREATE FUNCTION stg.num(t TEXT) RETURNS NUMERIC IMMUTABLE LANGUAGE plpgsql AS $$
DECLARE s TEXT := btrim(replace(replace(t, ',', ''), chr(160), ''));
BEGIN
    IF s IS NULL OR s = '' OR s !~ '^[-+]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][-+]?[0-9]+)?$' THEN RETURN NULL; END IF;
    RETURN s::NUMERIC;
EXCEPTION WHEN others THEN RETURN NULL;
END $$;

-- ISO text as written by the loader for real Excel date cells: 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS'
CREATE FUNCTION stg.ts(t TEXT) RETURNS TIMESTAMP IMMUTABLE LANGUAGE plpgsql AS $$
BEGIN
    IF t IS NULL OR btrim(t) !~ '^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2})?$' THEN RETURN NULL; END IF;
    RETURN btrim(t)::TIMESTAMP;
EXCEPTION WHEN others THEN RETURN NULL;          -- e.g. 2026-02-30
END $$;

-- An ISO date (Excel cell) OR typed day/month/year text, e.g. '08/04/2026' (BR-026: ERP text dates are D/M)
CREATE FUNCTION stg.any_date(t TEXT) RETURNS DATE IMMUTABLE LANGUAGE plpgsql AS $$
DECLARE s TEXT := btrim(t); m TEXT[];
BEGIN
    IF s IS NULL OR s = '' THEN RETURN NULL; END IF;
    IF s ~ '^\d{4}-\d{2}-\d{2}' THEN RETURN stg.ts(s)::DATE; END IF;
    m := regexp_match(s, '^(\d{1,2})/(\d{1,2})/(\d{4})$');
    IF m IS NULL THEN RETURN NULL; END IF;
    RETURN make_date(m[3]::INT, m[2]::INT, m[1]::INT);
EXCEPTION WHEN others THEN RETURN NULL;
END $$;

-- SKU as matched against products: trimmed, upper case; blank or an Excel error value (#N/A, #REF! ...) = no SKU.
-- Instamart's 'Elle SKU' column is a lookup that returns #N/A when it fails.
CREATE FUNCTION stg.sku(t TEXT) RETURNS TEXT IMMUTABLE LANGUAGE sql AS $$
    SELECT CASE WHEN nullif(btrim(t), '') IS NULL OR btrim(t) ~ '^#(N/A|REF!|VALUE!|DIV/0!|NAME\?|NULL!|NUM!)$' THEN NULL ELSE upper(btrim(t)) END $$;

CREATE FUNCTION stg.date_key(d DATE) RETURNS INTEGER IMMUTABLE LANGUAGE sql AS $$ SELECT to_char(d, 'YYYYMMDD')::INTEGER $$;

-- Document number up to its first all-digit segment: 'JPR/DC/15/09/26-27' -> 'JPR/DC'
CREATE FUNCTION stg.doc_prefix(t TEXT) RETURNS TEXT IMMUTABLE LANGUAGE sql AS $$ SELECT regexp_replace(btrim(t), '/[0-9]+(/.*)?$', '') $$;

INSERT INTO meta.schema_version (version, migration_file, description) VALUES ('2.1','100_staging_infra.sql','Staging infrastructure');
