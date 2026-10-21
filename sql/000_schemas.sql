-- =============================================================================
-- Ellementry Data Warehouse  |  000_schemas.sql
-- Creates the layered schemas. Safe to re-run.
--
-- Layer contract (data only ever flows left -> right):
--   meta  : load audit, source registry, data-quality results, pipeline settings
--   ref   : human-maintained reference/mapping data (version-controlled seed CSVs)
--   raw   : files exactly as received (all TEXT), one table per source, append-only
--   stg   : typed, trimmed, de-duplicated, one-to-one with source; no business logic
--   core  : conformed star schema (dimensions + facts) = single source of truth
--   mart  : BI/agent-facing views; ALL business definitions (e.g. "revenue") live here
--
-- Portability: standard SQL types only (VARCHAR, NUMERIC, DATE, TIMESTAMP,
-- BOOLEAN, IDENTITY). Postgres-specific statements are marked [PG-ONLY].
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS meta;
CREATE SCHEMA IF NOT EXISTS ref;
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS stg;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS mart;

COMMENT ON SCHEMA meta IS 'Load audit, source registry, data-quality results, pipeline settings';
COMMENT ON SCHEMA ref  IS 'Human-maintained reference and mapping tables (seeded from reviewed CSVs in git)';
COMMENT ON SCHEMA raw  IS 'Source files as received, all TEXT, append-only. Contains PII: restricted access';
COMMENT ON SCHEMA stg  IS 'Typed and cleaned copies of raw, one-to-one with source, no business logic';
COMMENT ON SCHEMA core IS 'Conformed star schema: dimensions and facts. Single source of truth';
COMMENT ON SCHEMA mart IS 'BI- and agent-facing views. All business metric definitions live here';
