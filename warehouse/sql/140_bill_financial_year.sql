-- =============================================================================
-- 140  Schema 2.6: a sales bill is its number WITHIN a financial year.
-- The ERP restarts bill series every April (IN-1 exists in FY 25-26 and FY 26-27). The bill's financial year
-- (start year, e.g. 2025 for FY 25-26) becomes part of the sales line's identity, so both bills are kept.
-- =============================================================================

ALTER TABLE core.fact_sales_line ADD COLUMN IF NOT EXISTS bill_fy_start SMALLINT NOT NULL DEFAULT 0;
COMMENT ON COLUMN core.fact_sales_line.bill_fy_start IS 'Start year of the financial year of the bill date (2025 = FY 25-26); bill numbers restart every April';
ALTER TABLE core.fact_sales_line DROP CONSTRAINT IF EXISTS uq_fact_sales_line;
ALTER TABLE core.fact_sales_line ADD CONSTRAINT uq_fact_sales_line
    UNIQUE (source_name, bill_number, bill_fy_start, source_sku_code, line_occurrence);

INSERT INTO meta.schema_version (version, migration_file, description)
VALUES ('2.6', '140_bill_financial_year.sql', 'Sales bill identity includes the financial year (bill numbers restart every April)');
