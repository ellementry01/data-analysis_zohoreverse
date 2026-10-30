-- =============================================================================
-- 190  Schema 2.11: stock history from month-end stock reports (Oct 2026 backfill, 31 Mar 2025 - 31 Aug 2026).
-- No table changes: the transform keeps the stock report of the day before the period as opening stock (BR-033), and
-- builds mart.v_stock_movement_check (transform/sql/45_stock_check.sql) with the quality check stock_movement_unexplained,
-- which replaces implied_negative_opening_stock.
-- =============================================================================

INSERT INTO meta.schema_version (version, migration_file, description)
VALUES ('2.11', '190_stock_history.sql', 'Month-end stock history, opening stock, month-by-month stock movement check');
