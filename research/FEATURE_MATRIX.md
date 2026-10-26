# Ellementry Analytics — Feature Matrix

The source for each row is `research/DISCOVERY.md`.

**Evidence level** says how we know the reference product has the feature:
- **A**: seen on public marketing pages, the features page, or the help table of contents (REA capture).
- **B**: behaviour described in a captured help article.

No live product observation was made. How Ellementry Analytics implements each feature is our own design.

**Category:** Essential MVP / Advanced analytics / NL AI / Data engineering / Dashboard-reporting / Admin / Future
**Complexity:** S (≤ 3 days) / M (1–2 weeks) / L (> 2 weeks), for one engineer.
**Planned status:** every row starts as `planned`. The build team updates this column.

## Data ingestion & modeling

| # | Feature | Category | Evidence | Complexity | Dependencies | Status (built) |
|---|---|---|---|---|---|---|
| 1 | Workspace container (local DB file + metadata catalog) | Essential MVP | B | M | none | **done** |
| 2 | Folders, descriptions & tags for views | Essential MVP | B | S | 1 | partial — descriptions only (no folders/tags) |
| 3 | CSV import wizard (delimiter/header/type sniffing, preview) | Essential MVP | A | M | 1 | **done** |
| 4 | Excel import (.xls/.xlsx), multi-sheet → one table per sheet | Essential MVP | B | M | 1, 3 | **done** |
| 5 | Include hidden rows / hidden columns toggles | Essential MVP | B | S | 4 | not implemented |
| 6 | Target table rename per sheet (multi-sheet mapping) | Essential MVP | B | S | 4 | not implemented |
| 7 | Header row / first-row setting & date-format selection | Essential MVP | B | S | 3 | partial — header row auto+override; dates auto-detected (no format picker) |
| 8 | Per-column type override in preview | Essential MVP | A | S | 3 | **done** |
| 9 | On-import-error policy (skip row / null cell / abort) + error report | Essential MVP | B | M | 3 | partial — unparseable cells imported empty + reported; no skip/abort policy |
| 10 | Re-import into existing table: append / replace / upsert | Essential MVP | A | M | 3, 9 | **done** |
| 11 | Import limits & merged-cell handling (fill-down option) | Essential MVP | B | S | 4 | partial — blank rows/title rows/footers handled; no fill-down |
| 12 | Import rollback (undo last import) | Data engineering | A | M | 10 | not implemented |
| 13 | Other file formats (JSON, XML, HTML tables, Parquet) | Data engineering | A | M | 3 | not implemented |
| 14 | DB connectors: PostgreSQL / MySQL / SQLite snapshot import | Data engineering | A | M | 1 | **done** |
| 15 | Generic ODBC/JDBC & cloud warehouses (Snowflake, BigQuery…) | Future | A | L | 14 | not implemented |
| 16 | Live-connect (query pushdown, no local copy) | Future | A | L | 14, 28 | not implemented |
| 17 | Credential storage in OS keychain | Data engineering | C-design / A | S | 14 | partial — Fernet-encrypted or env-var/pgpass, not OS keychain |
| 18 | Lookup column relationships (child→parent, cardinality) | Essential MVP | B | M | 1 | **done** |
| 19 | Relationship suggestions (name + type + data profiling) | Essential MVP | B | M | 18 | **done** |
| 20 | Lookup suggestions inside import wizard | Essential MVP | B | S | 19, 4 | partial — suggestions on Relationships page, not inside wizard |
| 21 | Cardinality validation & violation warnings | Advanced analytics | B (noted as *not* done by ref) | S | 18 | partial — lookup key must be unique (enforced); match rate reported |
| 22 | Auto-join in report builder (columns from related tables) | Essential MVP | B | L | 18, 28 | **done** |
| 23 | Join type override per report (Left default / Right / Inner) | Essential MVP | B | S | 22 | partial — LEFT join only |
| 24 | Choose lookup column(s) when multiple links exist | Advanced analytics | B | M | 22 | partial — one lookup per table pair |
| 25 | Choose join path (direct vs indirect) per report | Advanced analytics | B | M | 22 | partial — shortest (direct) path chosen automatically |
| 26 | Fan-out / double-count detection warning | Advanced analytics | A | M | 22 | partial — prevented by design (child→parent joins only) |
| 27 | Visual model diagram (tables + relationships) | Dashboard-reporting | B | M | 18 | **done** |
| 28 | Core query compiler (spec JSON → SQL; built on PostgreSQL) | Essential MVP | B | L | 1 | **done** |
| 29 | Dependency graph (delete protection, rename propagation) | Essential MVP | B | M | 28 | **done** |

## Transforms, SQL & formulas

| # | Feature | Category | Evidence | Complexity | Dependencies | Status (built) |
|---|---|---|---|---|---|---|
| 30 | Query tables (saved SQL SELECT views) | Essential MVP | B | M | 28, 29 | **done** |
| 31 | SQL editor: execute, function helper, save to folder | Essential MVP | B | M | 30 | **done** |
| 32 | PIVOT / UNPIVOT, UNION, CTE support in query tables | Advanced analytics | B | S | 30 | **done** |
| 33 | Nested query tables with depth cap + timeouts | Data engineering | B | S | 30 | **done** |
| 34 | Query tables usable as lookup endpoints | Advanced analytics | B | S | 18, 30 | partial — query tables can be lookup targets (same as datasets) |
| 35 | Formula column (row-level expression) with own grammar | Essential MVP | B | L | 28 | **done** |
| 36 | Formula function library (math, text, date, logical, null, conversion) | Essential MVP | B | M | 35 | **done** |
| 37 | Quick-add formula from column (type-aware presets) | Essential MVP | B | S | 35 | partial — column-name chips in metric editor |
| 38 | Formula-over-formula & edit/format/delete formulas dialog | Essential MVP | B | S | 35, 29 | partial — edit/delete; formulas reference physical columns only |
| 39 | Aggregate formulas (group-level metrics, typed result) | Essential MVP | B | M | 35, 28 | **done** |
| 40 | Aggregate formulas referencing parent-table columns | Advanced analytics | B | M | 39, 22 | partial — composite metrics combine facts; parent columns via dims |
| 41 | Time-intelligence functions (mtd/qtd/ytd, prior period, rolling) | Advanced analytics | B | M | 39 | partial — previous period / previous year comparison; no MTD/rolling functions |
| 42 | Workspace variables usable in formulas | Future | B | S | 35 | not implemented |
| 43 | Bucket columns (numeric ranges / text IN lists, unmatched label, case-sensitive) | Essential MVP | B | M | 35 | partial — CASE WHEN in calculated columns; no bucket UI |
| 44 | Bucket overlap/gap validation & quick presets (equal-width, quantile) | Advanced analytics | C-design / B | S | 43 | not implemented |
| 45 | Transform recipe steps (rename, cast, split, dedupe, fill-down…) | Data engineering | A | L | 28 | **done** |
| 46 | Visual ETL pipeline builder (join/append/transform graph) | Future | A | L | 45 | not implemented |

## Visualization & reporting

| # | Feature | Category | Evidence | Complexity | Dependencies | Status (built) |
|---|---|---|---|---|---|---|
| 47 | Chart designer with shelves X / Y (multi) / Color / Size / Text / Tooltip | Essential MVP | B | L | 28 | **done** |
| 48 | Per-field functions + type defaults (Sum, Year, Actual Values; date grains, seasonal grains) | Essential MVP | B | M | 47 | **done** |
| 49 | Core chart types: bar, stacked, line, area, pie/ring, scatter, table | Essential MVP | B | M | 47 | **done** |
| 50 | Extended chart types: combo, bubble, funnel, web/radar, packed bubble | Dashboard-reporting | B | M | 49 | partial — combo (bar+line, dual axis) and heatmap; no funnel/radar/bubble |
| 51 | Advanced types: treemap, sunburst, Sankey, histogram, Gantt, word cloud, maps | Future | A | L | 49 | not implemented |
| 52 | Chart-type switching with validity rules (disable unsupported) | Essential MVP | B | S | 49 | **done** |
| 53 | Chart recommendations ("suggested visualizations") | NL AI | B | M | 52 | **done** |
| 54 | Show-value-as: % of total, running total, difference, % prev, 100% group, moving avg | Advanced analytics | B | M | 47 | partial — change % vs previous period only |
| 55 | Report filters (design-time: values, ranges, date ranges, Top/Bottom N) | Essential MVP | B | M | 28 | **done** |
| 56 | Report user filters (view-mode dropdown / slider / date picker) | Essential MVP | B | M | 55 | partial — dashboard-level filters; not per report |
| 57 | Drill-down (date grain / hierarchy) with breadcrumbs | Dashboard-reporting | A | M | 47 | **done** |
| 58 | Drill actions (URL with ${Column} placeholders; GET default, write-back opt-in) | Future | B | M | 47 | not implemented |
| 59 | Pivot table (Row / Column / Data / Filter shelves, nested groups) | Essential MVP | B | L | 28 | **done** |
| 60 | Pivot subtotals/grand totals, data-as-row/column, % of row/column/group | Advanced analytics | B | M | 59 | partial — row/column grand totals for additive measures |
| 61 | Summary & tabular views | Dashboard-reporting | A | M | 28 | partial — table + pivot views |
| 62 | Undo/redo in designers | Essential MVP | B | S | 47 | not implemented |
| 63 | Conditional formatting (tables, query tables, pivots) | Dashboard-reporting | B | M | 59 | partial — change-% colouring only |

## Dashboards

| # | Feature | Category | Evidence | Complexity | Dependencies | Status (built) |
|---|---|---|---|---|---|---|
| 64 | Dashboard grid layout (drag/resize, multi-select, fit-width, fill space, copy dims) | Essential MVP | B | L | 47 | **done** |
| 65 | Dashboard tabs (≤10; rename/duplicate/remove; move views between tabs) | Dashboard-reporting | B | M | 64 | not implemented |
| 66 | Width modes (fit / A3 / A4 / Letter / Tabloid / custom 797–4000px) | Dashboard-reporting | B | S | 64 | not implemented |
| 67 | Text, image, embed elements; themes | Dashboard-reporting | B | M | 64 | partial — no text/image elements |
| 68 | KPI label widgets (single, secondary value, comparison indicator) | Essential MVP | B | M | 39, 64 | **done** |
| 69 | KPI chart widgets (bullet, dial / speedometer / conditional, full dial) | Dashboard-reporting | B | M | 68 | not implemented |
| 70 | KPI targets, qualitative ranges, dynamic label templates, info tooltip | Dashboard-reporting | B | S | 68 | partial — KPI change vs previous period; no targets |
| 71 | KPI drill-through to ≤20 linked views with criteria pass-through | Dashboard-reporting | B | M | 68 | not implemented |
| 72 | Dashboard user filters (from report columns, auto-add, report-specific) | Essential MVP | B | M | 56, 64 | **done** |
| 73 | Global filters across tabs (common-only vs copy-current-tab) | Dashboard-reporting | B | M | 72, 65 | partial — single-tab dashboards; filters are global |
| 74 | Timeline filter: date range + relative periods (default star) | Essential MVP | B | M | 72 | **done** |
| 75 | Time slicer with dashboard-wide date-grain change (per-view opt-out) | Dashboard-reporting | B | M | 74 | partial — drill changes grain per widget |
| 76 | Date column mapping & resolution order (report → base → related) | Essential MVP | B | M | 74, 22 | **done** |
| 77 | Filter merge (manual + auto by same name/type across tables) | Dashboard-reporting | B | M | 72 | not implemented |
| 78 | Reports as filters (click-to-cross-filter, include/exclude) | Dashboard-reporting | B | M | 72 | partial — click-to-drill per widget, not cross-filtering |
| 79 | Preset (saved) filter combinations | Dashboard-reporting | B | S | 72 | partial — 'Save as default view' stores one preset |
| 80 | Per-report exclude from dashboard filters; invalid-filter guard | Dashboard-reporting | B | S | 72 | not implemented |
| 81 | Deleted-view placeholder (restore / remove) | Dashboard-reporting | B | S | 29, 64 | not implemented |

## NL AI & insights

| # | Feature | Category | Evidence | Complexity | Dependencies | Status (built) |
|---|---|---|---|---|---|---|
| 82 | NL question → structured query spec (offline entity linker) | NL AI | B (partial; p12 not captured) | L | 28, 84 | **done** |
| 83 | Conversation mode: follow-ups refine current spec; "clear" resets | NL AI | B | M | 82 | **done** |
| 84 | Synonyms: table, column, data-value; metric synonyms | NL AI | B | M | 1, 39 | **done** |
| 85 | Table / column / metric priority + table blacklist for NL ranking | NL AI | B | S | 84 | partial — glossary weight beats auto-matched terms; no blacklist |
| 86 | Default aggregation per column for NL | NL AI | B | S | 84 | partial — numeric→SUM, text→COUNT DISTINCT defaults |
| 87 | Ambiguity clarification chips + learn-from-choice | NL AI | C-design (no doc evidence) / B-adjacent | M | 82, 85 | partial — clarify response with suggested metrics/questions |
| 88 | Suggested questions & column autocomplete while typing | NL AI | B | M | 82 | partial — suggested questions; no autocomplete |
| 89 | Chit-chat vs analytic intent routing | NL AI | B | S | 82 | **done** |
| 90 | Save NL answer as report / drop onto dashboard | NL AI | B | S | 82, 64 | **done** |
| 91 | Answer feedback (thumbs + reason) stored locally | NL AI | B | S | 82 | not implemented |
| 92 | LLM formula assistant (text → validated formula) | NL AI | B | M | 35, 39 | not implemented |
| 93 | LLM query assistant (text → editable query table SQL) | NL AI | B | M | 30 | partial — LLM path generates validated SQL answers (not saved as query tables) |
| 94 | AI synonym suggestions for columns | NL AI | B | S | 84 | not implemented |
| 95 | Automated insights: contribution, extremes, top contributors | Advanced analytics | B | M | 28 | **done** |
| 96 | Time-series insights: trend, seasonality, period-over-period | Advanced analytics | B | M | 95 | **done** |
| 97 | Template narratives + verbosity levels (low / medium / high) | NL AI | B | M | 95 | partial — template narratives (one verbosity) |
| 98 | Explain data point (vs overall, vs peers) | Advanced analytics | B | M | 95 | not implemented |
| 99 | Anomaly detection on line/bar charts (IQR, robust Z, percentile, custom; direction; scope) | Advanced analytics | B | M | 47 | **done** |
| 100 | Seasonal anomaly model (RPCA-equivalent, deviation %) | Advanced analytics | B | L | 99 | not implemented |
| 101 | Forecasting on charts & KPI widgets (with intervals) | Advanced analytics | A / B (named only) | L | 47, 68 | not implemented |
| 102 | Key driver analysis (change decomposition, top contributors/offsetters, missing drivers) | Future | B | L | 96 | not implemented |
| 103 | What-if analysis, clustering, AutoML | Future | A | L | 101 | not implemented |
| 104 | Data alerts (threshold / anomaly notifications) | Future | A | M | 99, 108 | not implemented |

## Metrics, admin, sharing, sync

| # | Feature | Category | Evidence | Complexity | Dependencies | Status (built) |
|---|---|---|---|---|---|---|
| 105 | Metrics catalog (all aggregate formulas: description, owner, dependencies) | Advanced analytics | B | M | 39, 29 | **done** |
| 106 | Metric dependency view (source tables diagram, child views/dashboards) | Advanced analytics | B | S | 105, 27 | partial — lineage graph shows dataset→report/dashboard |
| 107 | Sync schedules per connection (hourly-N / daily / weekly / monthly / none) | Data engineering | B | M | 14 | **done** |
| 108 | Multiple sync groups per connection (≤5), move tables between groups | Data engineering | B | M | 107 | not implemented |
| 109 | Sync failure notification after N consecutive failures; run log | Data engineering | B | S | 107 | partial — last status shown; no notifications |
| 110 | Post-sync dependent refresh (materialized query tables, KPI cache) | Data engineering | A | M | 107, 29 | partial — query tables are views, always current |
| 111 | Export data: CSV / XLSX / Parquet | Essential MVP | B | S | 28 | **done** |
| 112 | Export charts/dashboards: PNG / SVG / PDF | Dashboard-reporting | A | M | 64 | partial — PNG per chart; PDF via browser print |
| 113 | Workspace bundle export/import (backup & portability) | Admin | A | M | 1 | not implemented |
| 114 | Role model (owner / admin / editor / viewer / custom) | Admin | B | M | 1 | **done** |
| 115 | Row-level filter per principal (share filter criteria) | Admin | B | M | 114, 28 | not implemented |
| 116 | Formula/drill-action permission gates for shared users | Admin | B | S | 114 | partial — role-gated (viewer cannot edit) |
| 117 | Publish/embed (static HTML snapshot first; live URL later) | Future | A | M | 112 | not implemented |
| 118 | Comments on reports/dashboards | Future | A | M | 114 | not implemented |
| 119 | Scheduled email/report delivery | Future | A | M | 112, 107 | not implemented |
| 120 | API / MCP server exposing workspace tools to external agents | Future | A | L | 28, 82 | not implemented |

---

### Notes for the build team

- **Rows marked "C-design"** (17, 44, 87) are design ideas of ours that go beyond what the docs describe.
  The A/B after the slash gives the nearest evidence level. Row 87 has no documentary basis for
  clarifying questions; the reference product appears to resolve ambiguity through priorities.
- **MVP critical path:** 1 → 28 → (3, 4) → 18 → 22 → 35/39 → 47 → 59 → 64 → 68 → 72/74 → 82–86.
- Rows 82 and 87 are higher-risk because p12 (Ask Zia usage) was not captured. Plan a spike.
