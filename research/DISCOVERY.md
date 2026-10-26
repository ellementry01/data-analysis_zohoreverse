# Ellementry Analytics — Product Discovery (reference: Zoho Analytics public docs)

Ellementry Analytics is an independent, local-first AI analytics app. This document records what we learned
from **public** Zoho Analytics marketing and help pages, written up in our own words, and turns it into
implementation ideas of our own. We do not copy text, UI or branding. Quotes are limited to a few words.

## Evidence labels

| Label | Meaning |
|---|---|
| **(A)** | Seen on public marketing or features pages captured with REA. This shows the feature is advertised, not how it behaves. |
| **(B)** | Taken from the documentation: behaviour as the public help articles describe it. We have not checked it in the product. |
| **(C)** | Our own implementation idea, inferred for Ellementry Analytics. It is not a claim about Zoho. |

> **No live product observation was made.** We used no authenticated Zoho Analytics account or trial.
> Nothing below is marked "confirmed in-product". Where the docs are vague, we say so.

---

## 1. Method & evidence

- **Tool:** REA MCP `capture_browser_scenario` (Playwright provider, headless Chrome, launch mode,
  1440x900 viewport). It saved an accessibility-tree text snapshot of each page. Evidence metadata is in
  `research/rea_scenario_1.json`, `rea_help_*.json`.
- **Date:** 2026-10-17.
- **Pages captured:**
  - `zoho_page_1.txt`: marketing home page (`/analytics/`).
  - `zoho_page_3.txt`: features overview page.
  - `help_links.txt`: 438 help-centre URLs from the docs table of contents. We used it to size areas:
    about 111 connector pages, 92 import-data pages, 25 chart pages, 20 cloud-database pages and 12 Zia pages.
  - `help_pages/p01..p21`: 21 help articles (import Excel, relational modeling, joining tables, query
    tables, formula columns, aggregate formulas, chart creation, drill actions, dashboard creation,
    dashboard filters, KPI widgets, Ask Zia (p12), conversation mode, training Ask Zia, Zia Insights,
    unified metrics, user roles, sync schedules, pivot tables, anomaly detection, data bucketing).
- **Limitations:**
  1. **No trial login.** We have no in-product screenshots, network traces or UI state, and nothing was
     verified live.
  2. **p12 (`zia/using-ask-zia.html`) is effectively empty.** The capture returned a "page not found"
     shell (about 700 bytes). The main guide to using Ask Zia, and the separate `zia/construct-questions.html`
     page in the TOC, were **not** captured. As a result, how NL questions are built and how ambiguity is
     resolved comes only from the conversation-mode (p13) and training (p14) articles.
  3. **The docs are rendered with JavaScript.** Many articles show steps through images, animations,
     iframes or embedded "presentations". The accessibility tree only captured alt text or empty headings
     for these. Examples: the per-type user-filter subsections in p10, the label-widget subsections in
     p11, the "create a query table" steps in p04, and the string, number and date function screenshots
     in p07.
  4. Linked sub-pages were not followed: the general import landing page (First Row, Date Format,
     On Import Error), the CSV page, sharing, export, the drill-down page and the forecasting page.
     Statements about those areas are labelled (C), or (B) where the captured page mentions them only
     by name.
  5. Plan-tier statements, such as which plan includes which feature, are recorded as documented but
     may change.

---

## 2. Workspaces

- **What it does (B):** A workspace is the container for tables, query tables, reports, dashboards and
  formulas, and it sits inside an *Organization*. An organization can hold any number of workspaces
  (p17). The TOC lists further workspace topics, which we did not capture: create, settings, user and
  group settings, **variables**, linked workspaces and "classified views".
- **Interaction flow (B/C):** The user creates a workspace and imports data into it. A side navigation
  gives access to Data, Reports, Dashboards, Ask Zia and Data Sources (side-panel names are mentioned in
  p07, p16 and p18).
- **Inputs/outputs:** A name and description go in. The workspace holds the model, views and folders.
  Reports are saved into **folders** with an optional description and **tags** (p07).
- **Edge cases (B):** Workspace admins cannot rename, delete or back up the workspace. Those actions are
  reserved for higher admins (p17). Aggregate formulas can reference workspace **variables** (p06).
- **Our independent implementation (C):**
  - Each workspace is one local DuckDB/SQLite file plus a JSON/SQLite metadata catalog (tables,
    relationships, formulas, views, folders, tags).
  - Folders and tags are part of the MVP. Workspace variables (named constants usable in formulas) come later.
  - Export and import a workspace as a single archive for backup and portability.

## 3. File import (Excel/CSV)

- **What it does (B):** An import wizard brings in files. For Excel it supports `.xls` and `.xlsx` from a
  local drive, pasted data or FTP (p01). The TOC also lists CSV, HTML, JSON, XML, statistical, spatial,
  MS Access and PDF imports.
- **User interaction flow (B):** Choose a source → pick the file type → upload → set the Excel options
  (sheets, hidden rows and columns) → Next → wizard settings (**Table Name, First Row, Date Format**) →
  **Preview** → set the **On Import Error** behaviour → Create (p01). The details of the shared settings
  page were not captured.
- **Excel-specific options (B):**
  - **Sheet selection:** you can pick more than one sheet, and *each sheet becomes its own table*.
  - **Hidden rows and hidden columns:** these are left out unless you opt in to each one separately.
  - **Multi-sheet mapping:** a two-column view maps each source sheet to its target table name, and you
    can rename a target inline.
- **Documented limits and behaviour (B):** 100 MB per file and 1M rows per import, with larger files
  routed to a separate bridge tool. Formula cells come in as their computed values. Charts and images are
  ignored. Cell formatting is dropped. **Merged cells:** only the first row of the merged range gets the
  value and the rows below are empty.
- **Lookups at import (B, p03):** When importing into an existing workspace, the wizard can propose
  lookups ("Join tables" in the data preview) by matching column names and data types.
- **Not captured, so (C):** header-row detection, type inference rules, error-handling modes
  (skip row / set null / abort) and append/replace/upsert modes for re-imports. The docs refer to
  "First Row" and "On Import Error" options, but the captured pages do not describe them.
- **Our independent implementation (C):**
  - Use SheetJS (or calamine) for xls/xlsx, and use the DuckDB CSV sniffer (delimiter, quote, header,
    types) for CSV.
  - Wizard steps: file → sheets (multi-select, include-hidden toggles) → header row index (auto-detect,
    with override) → per-column type override with a 1,000-row sample preview → error policy
    (`skip_row` | `null_cell` | `abort`), shown with a per-column error count → mode for an existing
    table (`append` | `replace` | `upsert on key`).
  - Date format detection: try ISO, then D/M/Y vs M/D/Y using value ranges (>12 rules out the other
    order), and let the user override.
  - Merged cells: offer an optional "fill down merged values" toggle, defaulting to the documented
    behaviour (empty).
  - Keep an import log (rows read, imported, rejected, with sample rejected rows) and support rollback
    of the last import. The TOC lists an "import rollback" page.

## 4. DB connectors

- **What it does (A/B):** Marketing claims 500+ sources (A). The TOC lists more than 60 database
  targets: local MySQL, PostgreSQL, SQL Server, Oracle, SQLite, DB2, SAP HANA, Hive, Vertica and others;
  cloud Snowflake, BigQuery, Redshift, Azure SQL, Aurora and others; ODBC/JDBC generic; and NoSQL
  MongoDB and Cassandra (A, from the URL list). There are two modes: **import with scheduled sync**
  (p18) and **live connect** (TOC `datasources/live-connect.html`, home page mentions live connect).
- **Flow (B, p18):** Create → Import Data → choose a connection → pick tables → choose the data-fetch
  method → set the schedule. Existing connections are reused.
- **Edge cases (B):** Data synonyms are not available on live-connect tables (p14), which suggests live
  tables do not keep a local value index.
- **Our independent implementation (C):**
  - MVP: PostgreSQL, MySQL and SQLite connectors with a "query or pick tables → import snapshot" flow
    into the local DuckDB.
  - Later: a live-query mode that pushes SQL down through DuckDB `postgres_scanner`/`mysql_scanner`.
    Features that need a local value index (data synonyms, value autocomplete) are disabled for live tables.
  - Store credentials in the OS keychain, never in the workspace file.

## 5. Data prep / transforms

- **What it does (A):** The features page advertises a visual ETL pipeline builder (join, append,
  transforms), a "data preparation studio" with 250+ no-code transforms, and an AI agent for data
  engineering. None of these were covered by the captured help articles, so the evidence is level A only.
- **Related documented features (B):** Bucket columns (section 17), formula columns (section 8), and
  query tables for union, pivot and unpivot (section 7).
- **Our independent implementation (C):**
  - Transforms as an ordered, replayable recipe of steps (rename, cast, trim, split, fill-down,
    dedupe, filter, derive, pivot/unpivot, join, append), compiled to DuckDB SQL views.
  - Show a step preview over a sample, with full materialization on save or on sync.
  - The NL "data prep agent" turns a request into recipe steps that the user approves.

## 6. Tables & relationships (lookup columns, auto-join)

- **What it does (B, p02/p03):** Tables are related by turning a child column into a **lookup column**
  that points at a parent column, much like a foreign key. A relationship has a **cardinality**:
  one-to-one, one-to-many/many-to-one, or many-to-many. **Cardinality is not checked against the data**
  when a lookup is set up by hand. This lets users build star and snowflake models.
- **Ways to define a lookup (B):**
  1. **Import wizard:** "Join tables" lists suggested lookups for the user to confirm.
  2. **Table view:** right-click a column → *Change to Lookup* → choose the cardinality and the
     target column. *Get Suggestion* lists candidates.
  3. **Edit Design → Lookup section:** add lookups by hand (any number), or use *Get Suggestions* and
     accept them all or a selection.
  4. **Report editor:** add another table's data while building a report.
  - Suggestions come from **metadata, meaning column names and data types**.
- **Auto-join (B):** When a report is built on a table, the column list also shows columns from every
  table reachable through lookups. Dragging columns from several tables joins them automatically.
  Columns from related tables can also be used as **filters**.
  - **Default join is LEFT**: all child rows plus matching parent rows. **RIGHT** can be chosen in a
    "relationships used" dialog. Inner joins are documented for query tables only.
  - **Lookup column choice:** when two tables are linked by more than one lookup (for example Bugs→Users
    through Assignee and Reporter), the user can choose which lookup to use, or **pick several**. Picking
    several means all the join conditions must hold.
  - **Path choice:** when there is both a direct and an indirect path (Bugs→Users vs
    Bugs→Projects→Users), the system uses the direct one by default. The user can change the path.
  - **Constraint:** there is only one path per pair of tables in a report. Two columns from the same
    table cannot use different paths.
- **Other (B):** Query tables can act as lookup endpoints too (p04 Q10). Renaming a column carries
  through to dependent views (p04).
- **Our independent implementation (C):**
  - `relationships` table: `{id, child_table, child_cols[], parent_table, parent_cols[], cardinality,
    created_by: manual|suggested, validated_at, violations}`.
  - **Suggester:** score candidate pairs on name similarity (exact or normalised `*_id` matches),
    type compatibility, parent uniqueness (sampled distinct ratio) and child-in-parent containment
    (sampled). Unlike the documented behaviour, we *do* profile the data and warn when the declared
    cardinality is violated.
  - **Join planner:** treat relationships as a graph and use the shortest path by default. For
    ambiguous edges (several lookups between the same pair) prompt the user once and remember the
    choice per report. Default to LEFT from the fact (child) side, with a per-report override for
    RIGHT, INNER or FULL. Detect fan-out, which is many-to-many or measures on the parent side, and warn
    about double counting.
  - The UI shows the "relationships used in this report" panel with the path and the join type.

## 7. Query tables (SQL)

- **What it does (B, p04):** A saved SQL `SELECT` over workspace tables that behaves like a table. It
  supports reports, sharing, export, formatting, conditional formatting, lookups, aggregate formulas
  and nesting.
- **Supported SQL (B):** Dialects include ANSI (recommended), Oracle, SQL Server, DB2, MySQL, Sybase,
  Informix and PostgreSQL. Joins are LEFT, RIGHT and INNER. UNION is supported. **PIVOT and UNPIVOT**
  clauses are supported. **Non-recursive CTEs** are supported, up to 3, and cannot be combined with
  subqueries or with PIVOT/UNPIVOT. **Correlated subqueries in WHERE are not supported.** Query tables
  can be nested up to **3 levels**.
- **Flow (B):** Write the query (with a SQL-function helper tab) → Execute → Save with a name and
  folder. Edit later, or Clear and rewrite. Columns are renamed through `AS` aliases.
- **Edge cases (B):** Long or complex queries load slowly or time out. Deleting a column that dependent
  views use is **blocked by a dependency check**, which lists those dependents. Aliases cannot be used
  in HAVING. Best-practice guidance: avoid `SELECT *` and cartesian joins, filter early, prefer
  UNION ALL, and prefer auto-join or formulas over query tables where possible.
- **Our independent implementation (C):**
  - Use DuckDB SQL as the single dialect (it already supports PIVOT/UNPIVOT, recursive CTEs and
    correlated subqueries). Optionally use sqlglot to transpile other dialects.
  - Query tables are stored as views, with optional materialization and refresh after the upstream sync.
  - Keep a dependency graph (`view_deps`) for every derived object and block destructive changes with a
    list of dependents. Cap nesting depth (configurable, default 5) and set a statement timeout.
  - Let the NL agent draft a query table from a prompt (section 13), with the user approving it in an editor.

## 8. Formula columns & aggregate formulas

- **Formula column (B, p05):** A row-level computed column added to a table. Flow: Add → Formula Column
  → name, optional description, expression, then Save. A side panel lists columns and built-in
  functions. "Quick add": select a column and pick from common functions for its type. The new column
  is named after the function and the source column.
  - **Syntax (B):** column names in double quotes, text in single quotes, numbers bare; the usual
    arithmetic precedence; `if(cond, a, b)` (which can be nested); `CASE <col> WHEN … THEN … ELSE … END`
    and `CASE WHEN <cond> THEN …`; and the operators AND, OR, IN, NOT IN, BETWEEN, NOT BETWEEN, LIKE,
    NOT LIKE, IS NULL and IS NOT NULL.
  - **Function categories seen in examples (B):** math (`round`, `ceil`, `floor`), date (`hour`,
    `currentdate`, `dateandtimediff(YEAR, a, b)`), conditional (`if`, `case`). The full built-in
    function list is on an uncaptured page.
  - Formulas can reference other formulas. The docs recommend splitting complex logic into steps.
  - Formulas can be viewed, edited, formatted and deleted in an Edit Formulas dialog. Shared users with
    write access cannot edit or add formulas.
- **Aggregate formula (B, p06):** A group-level metric that **must include at least one aggregate**
  (SUM, AVG, …). It is not stored as a column. It appears in the report designer and is evaluated per
  group of the report's dimensions. Example of a time-intelligence helper:
  `mtd(sum("Sales"."Sales"), "Sales"."Date")`.
  - **Options:** a result data type (auto-detected or chosen: number, positive number, decimal,
    currency, percentage, duration, text or date), a description, **synonyms** and a **metric priority**
    (used by NL Q&A), and an AI "formula suggester".
  - **Insertable elements:** columns from the base table **and from parent tables reachable through
    lookups**, functions by category, workspace variables and existing formulas (shown in a different
    colour so they can be reused, for example Won Amount → Win Rate).
- **Our independent implementation (C):**
  - Write our own expression grammar (PEG or Lark) that compiles to DuckDB SQL. It covers a typed AST,
    type inference, and validation errors that show the position.
  - Function categories: Math, Text, Date/Time, Logical/Conditional, Null-handling, Type conversion,
    Aggregate (sum, avg, min, max, count, countdistinct, median, percentile, stddev, variance) and
    Time-intelligence (mtd, qtd, ytd, prior-period, rolling-N).
  - Compile aggregate formulas into the GROUP BY query at render time. When they reference parent-table
    columns, go through the join planner.
  - The AI formula helper drafts an expression from text. The draft is always validated by the parser
    before it can be saved.

## 9. Charts

- **What it does (B, p07):** A drag-and-drop chart designer. It opens from Create → Chart View (pick the
  base table) or from a table's menu. The column list is on the left and includes lookup-joined tables.
- **Shelves (B):** **X-axis**, **Y-axis** (several columns give multiple Y series or axes),
  **Color** (splits into series), **Text** (data labels) and **Tooltip** (extra tooltip fields).
  **Size** appears as a target for dependent fields and implies bubble charts.
- **Per-column functions (B):** Numeric fields default to **Sum** and also offer Max, Min, Avg, StdDev,
  Median, Mode, Percentile (default 50th), Variance, Count, Distinct Count, *Measure* / *Dimension*
  (treat values as discrete) and *Range* (auto bins, or a custom bin size). Dates default to **Year**,
  with actual-value grains (Year, Quarter & Year, Month & Year, Week & Year, Full Date, Date & Time),
  seasonal grains (Quarter, Month, Week, Weekday, Day of Month, Hour of Day) and Count / Distinct Count.
  Strings offer Actual Values, Count and Distinct Count.
- **Advanced summaries ("show value as") (B):** Normal, % of Total, Running Total, Difference From,
  % of Previous Value, % Difference From, 100% Group and Moving Average (sum/avg/min/max over N). These
  need a **base field**. The base field can be moved to another shelf but cannot be removed while the
  summary depends on it.
- **Chart types (A/B):** pie, ring, funnel, bar, stacked, scatter, line (plain, with points, step,
  smooth), combo (bar+line, stacked+line, smooth variants), area (plain, stacked, smooth, with points),
  bubble, packed bubble, web/filled web, and maps (scatter, pie, bubble, bubble-pie, filled). The TOC
  adds butterfly, conversion bar, Gantt, histogram, racing, Sankey, sparkline, sunburst, treemap and word
  cloud. Marketing says "50+". **3D charts were removed.**
- **Chart-type switching (B):** You can switch type without re-plotting. Types that do not fit the
  current shelves are **disabled**. A **Zia Suggestions** panel ranks suitable chart types for the
  dropped fields and lets you preview them.
- **Other (B):** undo/redo, and Save As (name, folder, description, tags).
- **Drill-down (A only):** marketing mentions drill-down. The drill-down help page was not captured.
- **Drill Actions (B, p08):** Configurable per chart, pivot or summary. Clicking a data point lists
  named actions that call a URL with **`${Column}` placeholders**, using GET, POST, PUT, PATCH or DELETE
  with params, body and headers. POST shows a success or failure notification. GET opens in an
  in-app iframe unless "open in new tab" is set.
- **Our independent implementation (C):**
  - Store the chart spec as JSON: `{base_table, encodings:{x,y[],color,size,text,tooltip[]},
    agg per field, grain per date field, show_value_as, filters[], sort, limit, type}`. It compiles to
    one SQL query, and Vega-Lite or ECharts renders it.
  - A "chart-type validity matrix" (cardinality of dimensions and measures per type) drives both the
    disabled states and the suggestion ranking.
  - Drill-down: a click on a dimension value goes to a finer date grain or to the next dimension in a
    hierarchy, with breadcrumbs. Drill-through goes to a linked report with the clicked values as filters.
  - Drill actions: in the local-first version only GET (open URL) is enabled by default. Write-back
    methods sit behind an explicit per-workspace opt-in.

## 10. Pivot & summary tables

- **Pivot (B, p19):** Create → Pivot View → base table (lookup-joined columns are available) → drop
  fields onto **Row**, **Column**, **Data** (and **Filters**) → Generate. A checkbox next to each column
  auto-places it on a shelf.
  - Several fields on Row or Column make nested groups in shelf order. Several Data fields show as
    **Data as column** (default) or **Data as row** (unpivoted, with editable headers).
  - Subtotal and grand-total rows and columns are added automatically.
  - Functions and defaults are the same as for charts. The advanced summaries add % of Row, % of Row in
    Group, % of Column, % of Column in Group, % of Total and Running Total.
  - Design-time filters include ranges, values, date ranges and **Top/Bottom N**. **User filters** can
    be exposed in view mode as dropdowns, sliders or date-range pickers.
  - The TOC also shows solution articles: Top N per category, trend arrows, expand/collapse and a
    "magic number" ratio.
- **Summary view and tabular view (A):** These exist in the TOC (`summary/`, `tabular/`) but were not
  captured. Drill actions also apply to summary views (p08).
- **Our independent implementation (C):**
  - The pivot engine uses DuckDB `GROUP BY GROUPING SETS/ROLLUP` for subtotals, then reshapes in the
    client. Rows are virtualized for large grids.
  - Percent-of-row, column, group and total are computed as window functions over the grouped result.
  - Expand/collapse is supported per row group. Conditional formatting and trend arrows come later.

## 11. Dashboards

- **Layout (B, p09):** a flexible "m x n" grid with drag to place, drag to resize (several at once),
  **copy/paste dimensions**, **fit to width**, **fill space**, multi-select move and remove, and
  copy/paste of views between tabs. There can be up to **10 tabs** per dashboard, and tabs can be
  renamed, duplicated or removed.
- **Width modes (B):** Web (fit to width), fixed paper sizes (A3 1123px, A4 797px, Letter 816px,
  Tabloid 1056px), or a custom width of 797 to 4000px. The width is kept for embed and export.
- **Elements (B):** reports, **KPI widgets**, **text** (title, paragraph, rich text), **images** (upload
  or URL, with colour, crop-to-shape, stroke, shadow, rotate and scale modes), and **embeds** (iframe
  URL). Themes are available.
- **Deleted views (B):** a placeholder lets the user restore or remove a view that was deleted.
- **KPI widgets (B, p11):**
  - *Label widgets* (6 single-number variants): single value, value plus secondary value, value plus
    comparison indicator.
  - *Chart widgets*: **Bullet** (bar with min/max and qualitative bands), **Dial**
    (simple / speedometer with red-yellow-green bands / conditional colour by threshold %) and
    **Full Dial** (ring; the plot can sit overlapping, outside or inside).
  - Options: a data column with an aggregation, an optional group-by, targets and ranges,
    **forecast** (KPI plus projection to target), a **descriptive tooltip** (info icon, at most 250
    characters), **drill-through** to up to 20 linked reports or dashboards (passing date and dimension
    criteria; with no dimension no criteria are passed; deleted targets are pruned automatically), and
    **static or dynamic images** (an image-URL column, images up to 200 KB, column display type "Image").
  - **Dynamic labels:** `${Col}.LABEL`, `${Col}.VALUE`, `${OPERATION}`, plus `${PERCENTAGE}` and
    `${MAXVALUE}` for the full dial.
- **User filters (B, p10):** Filters exposed in view mode can be added in four ways: from columns of
  the embedded reports, auto-added from the reports' own filters, per report only ("report-specific"),
  or as **global** filters across tabs. Global mode has two options: *common filters* (sync only the
  columns tabs share) or *current tab's filters* (copy them to every tab, removing tab-specific ones).
  - **Timeline filter**, not tied to one column. It has two components: a **Date Range** picker with
    relative periods (Today, This Week, Month, Quarter, Year by default, one of which can be starred as
    the default), or a **Time Slicer** (Year/Quarter/Month/Week/Date/Hour slider over any or a specified
    range). The time slicer can also **change the date grain of every view**, with per-view opt-out.
    Column mapping picks one date column per table. Resolution order: date columns in the report →
    in the base table → in related tables. Each report can override the mapping.
  - **Merging filters:** drop one filter onto another to merge them, or let them auto-merge when the
    columns come from different tables and have the same name, type, subtype and operation. You cannot
    merge two columns from the same table or columns of different types. Values are taken from the
    primary column. Each report can be mapped to a different column.
  - **Reports as filters:** clicking a data point filters the other views, by include or exclude value.
    It is enabled per dashboard and per report.
  - **Preset filters:** a named combination of filter values, which can be shared.
  - **Per-report opt-out** from dashboard filters. **Invalid filters**, meaning filters whose column is
    used by no report, block saving until removed.
- **Our independent implementation (C):**
  - Dashboard JSON: `{tabs[≤10]: {grid: 12-col react-grid-layout items}, filters:{global[], tab[]},
    presets[], width_mode}`.
  - Filter model: `{id, label, component: dropdown|multiselect|slider|date_range|time_slicer,
    bindings: [{view_id|table, column}], default, scope: tab|global}`. Bindings are resolved through
    the join planner, and views without a binding are skipped.
  - The timeline filter resolves the date column per view in this order: explicit mapping → date
    column used in the view → the base table's single date column → a reachable related-table date
    column → none, shown with an "unfiltered" badge.
  - Cross-filtering: clicking a mark sends the `{column, value, include|exclude}` predicate to
    subscribed views.
  - KPI widget spec: `{measure, agg, compare: previous_period|target|custom, target, ranges[],
    style: label|label_secondary|label_indicator|bullet|dial|full_dial, format, label_template,
    drill_targets[]}`.

## 12. Ask Zia — natural-language Q&A

- **Evidence caveat:** the main usage article (p12) and the question-construction page were **not
  captured**. What follows comes from p13 (conversation mode), p14 (training), p06 (synonyms and metric
  priority on formulas) and marketing (A).
- **How questions are handled (B):**
  - Chat-style **conversation mode**. It can be opened from the Ask Zia tab (toggle), from workspace
    search ("continue conversation") or from a dashboard, where only conversation mode is available.
  - It **tells chit-chat apart from analytical questions** and answers each kind accordingly.
  - **Follow-ups refine the query in progress**: each extra detail is added to the existing query.
    A new conversation is started with a double Enter or by sending "Clear".
  - **Auto-suggest** offers sample questions based on the data, and **column suggestions while typing**.
  - The answer is a report that can be saved, or dragged onto a dashboard (it goes into the most recent
    folder; changing the chart type and dragging again creates a new report).
  - **Feedback:** thumbs up or down. Thumbs down asks for a reason.
  - **Generative helpers** (needs the OpenAI integration, which an admin enables): "create a formula"
    gives an editable formula that can be saved as a formula column or an aggregate formula; "create a
    query" gives SQL that can be edited and saved as a query table; "insights" gives a Zia Insights
    narrative for the current report; product-help questions link to the docs.
  - Language: Spanish is not supported in conversation mode, so the account language must be changed.
- **How ambiguity is resolved (B, p14):** through a **training layer**, not through clarifying
  questions. The captured pages do not describe any clarifying-question behaviour.
  - **Table synonyms** (comma-separated), **Table Priority**, and a **blacklist** that excludes a table
    from NL Q&A.
  - **Column synonyms** and **Column Priority**. When several columns match, the higher column priority
    wins, and **ties fall back to table priority**.
  - **Default function per column**, for example averaging a rate rather than summing it.
  - **Data (value) synonyms** for text columns, for example mapping a nickname to a stored value. These
    are not available for columns marked personal or for live-connect tables.
  - **AI synonym suggestions** for columns (needs OpenAI).
  - Aggregate formulas carry **synonyms** and a **metric priority** (p06).
  - These settings can be edited from Ask Zia settings, from the table's Edit Design, or from
    right-click → Ask Zia Settings on a column.
- **Marketing (A):** agents for data engineering and data analysis, an embeddable agent, an MCP server,
  and Alexa and Teams bots (TOC).
- **Our independent implementation (C):**
  - **Semantic layer first:** NL resolves to a structured query spec (the same JSON as the chart spec),
    never straight to free SQL. Steps: tokenize → entity linking against
    {metric names and synonyms, column names and synonyms, value index and value synonyms, date
    phrases} → intent (measure, breakdowns, filters, time window, sort/top-N, chart hint) → validate
    against the relationship graph → render.
  - **Ranking for ambiguity:** match score × column priority × table priority × usage frequency. If the
    top two are within a margin, show **clarification chips** ("Did you mean Sales.Amount or
    Orders.Total?") instead of guessing silently. Remember the choice as a learned synonym.
  - **Conversation state:** keep the last spec. A follow-up yields a *diff* (add filter, change grain,
    swap measure). "Clear" or "new question" resets it.
  - Use a local LLM (Ollama) or a user-supplied API key as an *optional* parser and fallback. The
    deterministic linker runs offline. Only schema metadata and synonyms are sent to the model, never
    row data, unless the user opts in.
  - Always show the interpreted query as editable chips (measure / by / filter / time) next to the
    answer, for transparency.

## 13. Zia Insights, anomaly detection, forecasting

- **Zia Insights (B, p15):** auto-generated **textual and visual narratives** for a report, opened from
  a report or a dashboard tile. Available in EN, ES and FR.
  - **Verbosity**: Low covers totals, min/max and top contributors from report metadata only. Medium
    (the default) adds a suitable date dimension even when the report has none and adds time-series
    analysis (trend, period-over-period, seasonality, forecast, anomalies). There is also a higher level.
  - **Column selection:** the user's choice ("Explain by column"), otherwise automatic. The date column
    is chosen by priority, then by how often other reports use it, then by **hop distance** in the
    relationship graph. Dimensions are chosen by hop distance to the measure.
  - **Categories:** Contribution analysis (total, extremes, top contributors; needs 1 measure and
    1 dimension), Time series (trend, seasonality, forecast, anomalies; needs a date), Comparison between
    dimensions (needs 1 measure and 2 or more dimensions) and Analysis of measures (correlations; needs 2
    or more measures).
  - **Key Driver Analysis (diagnostic):** runs automatically on time-series insights. Up to **5
    dimensions and 3 measures** are used as factors. It reports top contributors and offsetters with
    impact %, possible reasons, **missing drivers** (factors that had no impact before and now matter),
    extreme values (expected vs observed, deviation %), occurrences, and trends and correlations. The
    model is explained with causal-path identification plus linear-regression effect estimation, and
    evaluation metrics (ATE, edge weight, p-value, confidence interval). *Prescriptive recommendations*
    use an external LLM, which receives column metadata.
  - **Explain Data:** click a data point to get insights about it (trend, seasonality, surge or
    decline, outlier) and comparisons with the overall value and with peers.
- **Anomaly detection (B, p20):** turned on per chart (Settings tab or analysis toolbar), for numeric
  measures on **line and bar charts**, with multiple Y measures allowed.
  - Models: **RPCA** (deviation %, 0–95, default 70; needs at least 6 points; suits seasonal time
    series) or **statistical**: IQR (scale 1.5, adjusted for skewed data), Z-score (±3; uses a modified
    MAD-based score for skewed data), Percentile (5th and 95th by default) or Custom bounds (needs at
    least 7 points).
  - Direction: Above, Below or Both (the default). Marker shape, size and colour are configurable, with
    separate colours for upper and lower outliers.
  - With a colour dimension, the scope can be: overall, each X value, each colour series, or each
    X×colour combination.
  - Clicking an outlier shows the expected value, the difference and the deviation %.
- **Forecasting / what-if / clustering / data alerts (A):** advertised on the features page. The KPI
  forecast is documented in name only (p11). The TOC has `chart/forecasting.html` and
  `what-if-analysis.html`, which were not captured.
- **Our independent implementation (C):**
  - Write insight generators as pure functions over the result DataFrame: totals and extremes, Pareto
    top-N contributors, trend (Mann-Kendall or linear slope with significance), seasonality (STL /
    autocorrelation), period-over-period change, and correlations. Each returns
    `{type, score, text_template_vars, highlight_marks}`, and these are ranked by score.
  - Narratives use deterministic templates. An optional LLM can rephrase them but never invent numbers;
    every number comes from the template variables.
  - Anomalies: IQR, robust z (MAD), percentile and custom bounds in the MVP. STL-residual or seasonal
    robust decomposition replaces RPCA. The UI and minimum point counts follow the same idea.
  - Forecast: ETS / seasonal-naive / Prophet-like (statsforecast) with prediction intervals, drawn as
    a dashed continuation.
  - Key drivers (later): decompose period-over-period change by dimension members (mix and rate), and
    rank features with Shapley values or regression. Label the output as correlational, not causal.

## 14. Metrics layer (Unified Metrics)

- **What it does (B, p16):** a **catalog of every aggregate formula** in the workspace, giving a single
  definition per metric. It is reached from Data → Unified Metrics. Each entry has a description, which
  is all shared users see; admins also see the definition. It offers edit and delete (for admins and
  permitted roles), info (creator and time), and **dependencies** (a model diagram of the tables used
  plus the child views and dashboards that use the metric).
- **Marketing (A):** consistency, reuse and access control. Metrics are said to be usable by ML and by
  third-party tools.
- **Our independent implementation (C):**
  - `metrics` registry: `{id, name, expression, result_type, format, description, synonyms[],
    priority, owner, created_at, certified: bool, grain_constraints?}`. Aggregate formulas *are* metrics.
  - A dependency graph shared with query tables and views powers impact analysis and safe rename.
  - Metrics feed NL Q&A (synonyms and priority), KPI widgets and insights, so there is one source of
    truth everywhere.

## 15. Sharing, roles, export

- **Roles (B, p17):** Account Admin (exactly one, can do everything), Organization Admin (several;
  everything except managing other org admins), Workspace Admin (everything in a workspace except
  rename, delete or backup), User (shared user who can do what they are granted on shared views),
  Viewer (read-only on shared views) and **Custom Role** (account-level, fine-grained, inherited on the
  workspaces shared with that user).
- **Permissions seen across the docs (B):** whether a user can create reports (p07), configure drill
  actions (p08), access Zia Insights (p15) or edit formulas (shared write users cannot, p05). Preset
  filters can be shared, with an option to let recipients create their own (p10). A "share filter
  criteria" feature gives row-level filtering per user and is recommended over making query tables per
  user (p04).
- **Export (B, p04 + TOC):** CSV, PDF, XLS and HTML for tables. The TOC lists report and dashboard
  export, email scheduling, export as template and export to another workspace.
- **Publishing (A/B):** public URLs and embeds (workspace admins only, p04), slideshows, portals and
  white-label. Marketing adds comments, groups, row-level security, SSO, audit logs and masking.
- **Our independent implementation (C):**
  - Local-first means single-user by default, so roles only matter once sync or a team server exists.
    Design the permission model early (`principal → role → permission on resource`, with an optional
    row-filter predicate per principal) and enforce it in the query compiler.
  - Export: CSV, XLSX and Parquet for data; PNG, SVG and PDF for charts and dashboards (headless
    render); a portable `.ellementry` workspace bundle. A "Static HTML snapshot" covers offline sharing.

## 16. Sync / refresh schedules

- **What it does (B, p18):** Each connection has a sync schedule: every N hours (top plan), daily,
  weekly, monthly, or *Not Scheduled* (import once). Options cover the time of day, day of week and day
  of month. A connection can have **up to 5 sync schedules**, and **tables are grouped by schedule**
  and can be moved between schedules (Move table / Add tables). A new table imported from an existing
  connection takes on the existing schedule by default and can be edited or given a new interval.
  **Failure notifications** go out after N consecutive failures, to the chosen roles or users.
- **Our independent implementation (C):**
  - Local scheduler (in-process, cron expressions) runs while the app or tray agent is running. When
    the app starts it catches up any missed runs, following a policy (run once / skip).
  - `sync_groups: {connection_id, cron, tables[], mode: full|incremental(key, watermark), on_fail:
    notify_after_n}`. Each run writes a run log, and failures appear in the notifications centre.
  - After a sync, downstream materializations (query tables, cached KPIs) are refreshed in dependency
    order.

## 17. Data bucketing

- **What it does (B, p21):** "Bucket Column" adds a categorical column derived from a numeric or text
  column. It can be added from the toolbar or by right-clicking a column (Add Buckets).
- **Inputs (B):** title, description, source column, then one or more **bucket labels**, each with one
  or more conditions. The conditions depend on type: numeric uses less than, between and so on; text
  uses in and so on. There is an optional **label for unmatched values**, an optional **case-sensitive**
  flag for text, and the user can add conditions and labels as needed.
- **Related (B, p07):** a chart-level **Range** function auto-bins numerics, with a custom bin size.
- **Guidance (B):** use it for high-cardinality columns, pick the number of bins carefully, and give
  buckets clear labels.
- **Edge cases (C, inferred):** overlapping ranges (does the first match win?), boundary inclusivity
  (the doc's example uses `<500` then `501–1000`, which leaves gaps for decimals), and nulls.
- **Our independent implementation (C):**
  - Compile to an ordered `CASE WHEN` where the first match wins. The editor validates **overlaps and
    gaps** for numeric ranges and shows `[a, b)` intervals explicitly. Nulls get their own bucket.
  - Offer quick presets: equal-width N, quantile N and custom breaks. The bucket column is stored as a
    formula column of kind `bucket`, so it can be edited later.

---

## 18. Cross-cutting implementation notes (C)

- **A single query compiler** (spec JSON → SQL) serves charts, pivots, KPI widgets, NL answers,
  insights and exports. Every feature above becomes a spec producer.
- **A dependency graph** across tables → relationships → formulas/metrics → query tables → views →
  dashboards. It drives delete protection, rename propagation, refresh order and the "used by" panels.
- **Local-first AI:** deterministic paths come first (synonym linker, template narratives, statistical
  anomalies). LLMs are optional and get metadata only by default.
- **Capture gaps to fill later (research backlog):** the import landing page settings, CSV options,
  Ask Zia usage and question construction, chart drill-down, forecasting, sharing and row-level
  filters, export, and summary and tabular views.
