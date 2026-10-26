-- =============================================================================
-- 050_seed_dim_date.sql  |  Populate core.dim_date, FY 2024-25 .. FY 2030-31
-- [PG-ONLY] uses generate_series / to_char. On another warehouse, generate
-- the same rows from Python and bulk-load them; column definitions are portable.
-- Safe to re-run (skips existing dates).
-- =============================================================================

INSERT INTO core.dim_date (
    date_key, calendar_date, day_of_month, day_of_week_iso, day_name, is_weekend,
    iso_year, iso_week, week_start_date, calendar_month, month_name, month_start_date,
    is_month_end, calendar_quarter, calendar_year, fiscal_year_start, fiscal_year_label,
    fiscal_quarter, fiscal_month)
SELECT
    CAST(to_char(d, 'YYYYMMDD') AS INTEGER),
    d,
    EXTRACT(DAY FROM d),
    EXTRACT(ISODOW FROM d),
    TRIM(to_char(d, 'Day')),
    EXTRACT(ISODOW FROM d) IN (6, 7),
    EXTRACT(ISOYEAR FROM d),
    EXTRACT(WEEK FROM d),
    CAST(d - CAST(EXTRACT(ISODOW FROM d) - 1 AS INTEGER) AS DATE),
    EXTRACT(MONTH FROM d),
    TRIM(to_char(d, 'Month')),
    CAST(date_trunc('month', d) AS DATE),
    d = CAST(date_trunc('month', d) + INTERVAL '1 month' - INTERVAL '1 day' AS DATE),
    EXTRACT(QUARTER FROM d),
    EXTRACT(YEAR FROM d),
    fy,
    CAST(fy AS VARCHAR(4)) || '-' || LPAD(CAST(MOD(fy + 1, 100) AS VARCHAR(2)), 2, '0'),
    CAST(((EXTRACT(MONTH FROM d) + 8) :: INTEGER % 12) / 3 + 1 AS SMALLINT),
    CAST((EXTRACT(MONTH FROM d) + 8) :: INTEGER % 12 + 1 AS SMALLINT)
FROM (
    SELECT CAST(g AS DATE) AS d,
           CASE WHEN EXTRACT(MONTH FROM g) >= 4 THEN EXTRACT(YEAR FROM g) ELSE EXTRACT(YEAR FROM g) - 1 END AS fy
    FROM generate_series(DATE '2024-04-01', DATE '2031-03-31', INTERVAL '1 day') AS g
) s
WHERE NOT EXISTS (SELECT 1 FROM core.dim_date x WHERE x.calendar_date = s.d);
