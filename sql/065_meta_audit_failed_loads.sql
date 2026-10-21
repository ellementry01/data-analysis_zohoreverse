-- =============================================================================
-- 065_meta_audit_failed_loads.sql  |  Migration (schema v1.3)
-- A file rejected before any date could be read (wrong columns, wrong sheet)
-- must still be recorded as a FAILED batch. The "must have a period or as-of
-- date" rule therefore applies to successful loads only.
-- =============================================================================
ALTER TABLE meta.load_batch DROP CONSTRAINT ck_load_batch_dated;
ALTER TABLE meta.load_batch ADD CONSTRAINT ck_load_batch_dated
    CHECK (status IN ('FAILED','STARTED') OR period_start IS NOT NULL OR as_of_date IS NOT NULL);
