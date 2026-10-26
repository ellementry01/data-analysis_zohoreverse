# Ellementry Data Warehouse — v2.4

Target: PostgreSQL 16+ (local; runs on the PostgreSQL 18 service on this PC), portable to a cloud warehouse later.
Status: v2.4 = v2.3 plus the supply / fulfilment / stock dashboard fixes (below). v2.3 = v2.2 (business-first model,
loaders, full transform) plus purchase-order document type, shipments from
the WMS dispatch export, platform sell-out from the monthly Blinkit / Instamart workbooks, and mart views for executive
dashboards. Loaded and reconciled on the full 1.5-year exports (Apr 2025 - Sep 2026). It feeds Ellementry Analytics
(`../ellementry`), which reads the `mart` views through the read-only `ellementry_metrics` role.

## Day-to-day commands (Windows, from this folder)

The admin login lives in `.env` (git-ignored) as `ADMIN_DATABASE_URL`; `dw.py` reads it and never prints it.
`DW_DATABASE=<name>` points any command at another database (e.g. a trial copy).

```bash
python dw.py backup                                   # pg_dump to ../../ellementry_backups, verified
python load_manifest.py ../exports                    # load every new file listed in ../exports/MANIFEST.tsv
python dw.py transform run                            # rebuild stg -> core -> marts (all or nothing)
python reconcile.py ../exports                        # totals from the files vs the warehouse
python -m loader.normalise_platform_sales <workbook> BLINKIT_SALES|INSTAMART_SALES ../exports/sellout --log ../exports/sellout/NORMALISE_LOG.tsv
DW_DATABASE=dw_test python dw.py pytest -q            # tests, never against ellementry_dw
```

Exports live in `../exports` (outside git: they hold customer data), one canonical copy per source and period,
listed in `MANIFEST.tsv` with sha256, rows, period and as-of date. A new export: copy it there, add its manifest line,
then `load_manifest.py` (already loaded files are skipped by the loader), `transform run`, `reconcile.py`.

Mart views added in 2.3 for dashboards: `v_sales_orders_daily` (bills, orders, average bill), `v_fulfilment`
(order-to-ship, delivery, SLA, RTO), `v_partner_sellout_daily` (quick-commerce demand, never revenue),
`v_stock_position_daily` (every saved stock day), `v_return_to_sale` (days from sale to return).

2.4 (`sql/120_supply_dashboard_fixes.sql`), all additive:
- **ERP item master** (`ERP_ITEM_MASTER`, the "Product Master List" export) is a source. It only fills product
  attributes no better source holds: it gave a category to 2,218 products that had none, and an MRP to 2 trading SKUs.
- **`v_stock_position_latest`** gains `category_label` (never blank), `mrp_status` and `stock_value_mrp`
  (NULL, not 0, when no source holds an MRP).
- **`v_days_of_cover`** counts transfers out as well as sales, so Bagru's cover is no longer overstated.
- **`v_fulfilment`** gains `courier_group` (ref.code_mapping COURIER: 39 WMS spellings, about 10 companies),
  `is_delivery_tracked` and `is_rto_tracked` (per channel, from the data), and drops weights over 100 kg.
- **`v_transfer_in_transit`** gains `destination_group` (Amazon FBA vs own locations), `transit_status` and `receipt_note`.
- **`v_open_purchase_orders`** gains `as_of_is_assumed`, `has_due_date`, `due_status`. New **`v_purchase_order_lines`**:
  every PO line with `is_open`, `is_over_received`, `over_received_qty`.
- **`meta.load_batch.as_of_is_assumed`**, set by `loader load --as-of-assumed` (load_manifest passes it when the
  manifest note says the as-of date is assumed).
- New WARN checks: `courier_unmapped`, `shipment_weight_suspect`.

## Layout

```
build_db.sh                   builds everything in order, stops at first error
sql/000_schemas.sql           meta, ref, raw, stg, core, mart
sql/010_meta.sql              source registry, load audit, DQ results, settings
sql/015_meta_seed.sql         the 14 registered sources + cut-off settings
sql/020_ref.sql               mapping tables (locations, channels, partners, codes)
sql/030_core_dimensions.sql   dim_date, dim_product (+history), dim_location, dim_channel, dim_partner
sql/040_core_facts.sql        7 facts + shipment SKU bridge
sql/050_seed_dim_date.sql     calendar FY2024-25 .. FY2030-31   [Postgres-only]
sql/060_ref_partner_channel.sql  migration: partner-type -> channel link, extra GST states
sql/065_meta_audit_failed_loads.sql  migration: failed loads are audited even before a date is read
sql/070_raw_tables.sql        GENERATED raw landing tables (one per source, all TEXT)
sql/080_context_registers.sql business rules, process map, gaps, coverage, source notes, lineage, data dictionary
sql/085_core_v2.sql           core v2 (replaces 030/040): stock ledger, consignment, orders, receipts, returns bridge
sql/090_insight.sql           agent outputs: runs, forecasts, recommendations (+ human decision), alerts
sql/095_column_definitions.sql (historical) first column definitions
sql/100_staging_infra.sql     transform run log, parsing helpers, unclassified movement types
sql/105_goods_receipt_grain.sql receipts as the PO report states them (one row per PO line + receipt numbers)
sql/110_po_document_type.sql  schema 2.3: PO 'Document Remark' (Purchase / Return) -> document_type + confirmation switch
sql/120_supply_dashboard_fixes.sql schema 2.4: ERP item master source, as-of-assumed flag, courier groups
sql/990_column_definitions.sql GENERATED, always last: a definition on every core / insight column
transform/                    the build: python -m transform run <db>; transform/sql/*.sql run in order
tests/test_transform.py       8 transform tests (rerun stability, quality gate rollback, safety switch, ledger rules)
seeds/ref_code_mapping.csv    fixed translations: PO statuses, product types, charge codes, placeholders
loader/seeds.py               seed loader: registers are upserted and never deleted; mappings replaced
tests/test_seeds.py           6 seed-loader tests
loader/                       file loader (python -m loader ...), contracts/*.json = expected file layouts
tests/test_loader.py          49 loader tests (rejections, atomicity, retries, stock-report checks)
tests/sample_manifest.tsv     the sample files and the as-of dates used for them
load_seeds.sh                 loads seeds/*.csv into ref (one transaction, repeatable)
seeds/build_ref_seeds.py      single definition of all location / channel mappings -> CSVs
seeds/meta_*.csv              rules, processes, gaps, source notes, lineage (reviewed, in git)
seeds/ref_partner_*.csv       partner types, default rules, partner list (maintained directly)
seeds/coverage_check.py       fails if any location / channel value in the source files is unmapped
seeds/build_review_workbook.py  builds the business review workbook from the same definition
tests/test_schema.sql         78 accept/reject tests (need the seeds loaded), runs in a rolled-back transaction
```

## Build on your laptop

```bash
createdb ellementry_dw
bash build_db.sh ellementry_dw
bash load_seeds.sh ellementry_dw                                          # reference mappings
psql -d ellementry_dw -v ON_ERROR_STOP=1 -f tests/test_schema.sql    # expect: 78 of 78 tests passed
python3 seeds/coverage_check.py                                        # expect: MISSING = 0
```

`build_db.sh` runs each file in a single transaction, so a failure never leaves half a file applied.
It is meant for a fresh database. Once real data is loaded, schema changes must go through
numbered migration files (e.g. `060_add_x.sql`), never by editing an applied file.

## Rules that keep this safe in production

1. Data flows one way only: raw -> stg -> core -> mart. Nothing writes backwards.
2. Nothing loads unless its source is registered in `meta.source_registry`, with an explicit date format.
3. Every row carries `batch_id`; the same file can't be loaded twice.
4. Unmatched SKUs / locations / channels / partners map to key `-1`, never dropped, always counted by a DQ check.
5. Business definitions (what counts as revenue, sellable stock, in-transit) live only in `mart` views.
6. Mappings live in `ref`, edited as CSV in git, reviewed before loading.
7. No customer PII in `core` or `mart`.

## Loading files (raw layer)

```bash
pip install -r requirements.txt
export PGDATABASE=ellementry_dw          # plus PGHOST / PGUSER / PGPASSWORD if needed

python -m loader sources                                        # what can be loaded, and which need --as-of
python -m loader load ERP_RETAIL_SALES  Retail_Sales_....xlsx --dry-run   # check only, writes nothing
python -m loader load ERP_RETAIL_SALES  Retail_Sales_....xlsx
python -m loader load ERP_INVENTORY_SNAPSHOT Inventory_report.xls --as-of 2026-09-15
python -m loader batches                                        # what has been loaded
```

What the loader guarantees:

- **Nothing changes on the way in.** Every cell lands as text exactly as in the file: no trimming,
  no rounding, IDs never become `1.2E+11` or `124118580.0`, typed text dates stay as typed.
- **A file must match its contract** (`loader/contracts/<SOURCE>.json`): right sheet, every expected
  column, no unexpected columns, no data on other sheets, no values beyond the last header.
  Column order may change; names may not.
- **The stock report must add up**: every row to its Total, every location column to the report's
  grand-total row, one single day, and every location in the report filter is compared with the
  columns present. Otherwise nothing is loaded.
- **All-or-nothing.** Rows, audit record and checks commit together. A rejected or failed attempt is
  still recorded as FAILED with the reason (`python -m loader batches`) and can be retried.
- **No double loads.** The same file cannot be loaded twice (exit code 3).
- **Snapshot / state / master files need `--as-of`** (the date the export represents). The loader
  rejects the file if the report states a different date, or if it contains dates after it.

Exit codes: 0 ok · 1 file rejected · 2 refused (usage) · 3 already loaded · 4 unexpected error.

### When the ERP changes an export
The loader will reject the new file and list exactly which columns differ. Then, deliberately:
1. update `loader/build_contracts.py` (or the contract JSON) for that source,
2. `python -m loader.generate_raw_ddl`, and write a migration for the raw table change,
3. review both in git, re-run `pytest`, then load.

### Running the tests
```bash
createdb dw_test && bash build_db.sh dw_test                        # disposable database
DW_TEST_DATABASE=dw_test DW_SAMPLE_DIR=/path/to/samples pytest -q # expect: 49 passed
```
Without `DW_TEST_DATABASE` only the pure tests run (the database tests are skipped, not failed).

### Raw layer is restricted
Raw tables hold customer PII exactly as exported. Give dashboards and agents access to `mart`
(and `core` if needed) only, never to `raw`.

## Context registers (v2.0)

The knowledge that used to live only in people's heads is data:

| Table | Holds |
| --- | --- |
| `meta.business_rule` | Numbered rules (BR-001...), who confirmed each and how (business, data evidence, design, design approval) |
| `meta.source_note` | What only the person handling a file knows: column meanings, traps, export quirks |
| `meta.business_process` | The process map: every process the agents need, its table, build phase and coverage |
| `meta.data_gap` | Every gap between the target design and today's data, with owner and how to fill it |
| `meta.process_coverage` | Coverage per process per month, so dashboards say "no data" instead of 0 |
| `meta.column_dictionary` | View: every warehouse column with definition, lineage and rules |

Rules, processes, gaps and notes are **never deleted**: retire, close or supersede them in the CSV.
The seed loader refuses a CSV that drops one.

**Safety switch:** `meta.pipeline_setting.partner_list_complete` stays `false` until the business
confirms the partner list holds every B2B, franchise, SIS, quick-commerce, group and factory name.
While false, unlisted names stay UNCLASSIFIED instead of being classified by elimination.

**PO document type (2.3):** the Pending PO export's `Document Remark` says Purchase or Return on every
line. It is stored (`core.fact_purchase_order_line.document_type`, shown in `v_open_purchase_orders` and
`v_supplier_lead_time`) but decides nothing until the business confirms rule BR-031 and
`meta.pipeline_setting.po_document_remark_confirmed` is set to `true`. Then Return lines are treated as
return-inwards (BR-013): left out of open POs and lead times, and placed in the ledger as RETURN_INWARD.
PO exports are per financial year: per PO number the latest export holding it is current, so loading
FY 25-26 and FY 26-27 keeps both. Exports without the column (37 columns) are refused: re-export them.
Existing database: apply `sql/110_po_document_type.sql`, then the regenerated `sql/990_column_definitions.sql`.

### Adding a column to core or insight
Add its definition to `seeds/column_definitions.tsv`, then regenerate `sql/095_column_definitions.sql`
(`python seeds/generate_column_definitions.py <db built with every migration except 990>`, writes `sql/990_column_definitions.sql`); the schema tests fail on any
column without a definition.

## Building the warehouse (transform)

```bash
python -m transform run ellementry_dw          # after loading files; ~10 s on the samples
```

One run rebuilds staging, core facts, the stock ledger, quality checks, coverage and mart views
**in a single transaction**:

- Dimensions keep their keys between runs (upserted by natural key); facts are rebuilt.
- **Quality gate:** checks marked ERROR (rows and values reconcile exactly to source; ledger signs
  match movement types; stock totals match) must pass, or the whole run is rolled back and the
  previous build stays in place. Exit code 1. The failed attempt is logged in `meta.transform_run`.
- WARN checks (unmatched values, unclassified partners, cut-off exclusions, ledger rows that could
  not be placed...) are listed after the run and in `mart.v_data_quality_latest`.
- The period comes from `meta.pipeline_setting` (`prototype_period_start` / `_end`); moving the
  cut-off is a setting change, not a code change.

What the build never does: guess. A movement whose location is unknown is not placed; a quantity
the source does not state per item stays empty; an unlisted partner stays UNCLASSIFIED until the
partner list is confirmed complete. Each of these is counted and reported.

Views for dashboards and agents (`mart` schema): `v_net_sales_daily`, `v_stock_position_latest`,
`v_days_of_cover`, `v_transfer_in_transit`, `v_open_purchase_orders`, `v_supplier_lead_time`,
`v_returns_daily`, `v_partner_review`, `v_data_coverage`, `v_data_quality_latest`.

Transform tests need a disposable, loaded database:
```bash
DW_TRANSFORM_DB=<db> pytest -q tests/test_transform.py          # expect: 8 passed (~3 min)
```
