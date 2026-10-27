#!/usr/bin/env bash
# Builds the warehouse schema from scratch, in order, stopping at the first error.
# Usage: ./build_db.sh <database_name>      (uses your normal psql connection env: PGHOST, PGUSER, ...)
set -euo pipefail
DB="${1:?usage: build_db.sh <database_name>}"
DIR="$(cd "$(dirname "$0")/sql" && pwd)"
for f in 000_schemas.sql 010_meta.sql 015_meta_seed.sql 020_ref.sql \
         030_core_dimensions.sql 040_core_facts.sql 050_seed_dim_date.sql \
         060_ref_partner_channel.sql 065_meta_audit_failed_loads.sql 070_raw_tables.sql \
         080_context_registers.sql 085_core_v2.sql 090_insight.sql 095_column_definitions.sql \
         100_staging_infra.sql 105_goods_receipt_grain.sql 110_po_document_type.sql \
         120_supply_dashboard_fixes.sql 130_shipment_sales_link.sql 140_bill_financial_year.sql 150_shipment_sku_quantity_rules.sql 160_cost_and_category.sql 990_column_definitions.sql; do
  echo ">> $f"
  psql -d "$DB" -v ON_ERROR_STOP=1 -q --single-transaction -f "$DIR/$f"
done
echo "Build complete."
