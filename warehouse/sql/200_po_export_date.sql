-- =============================================================================
-- 200  Schema 2.12: real export date of the two Pending PO files (issues D-083 / D-094).
-- Both files were saved on 26 Sep 2026 (file metadata, ~12:00 IST; the '12.22' / '12.09' in their names are times),
-- and the FY 25-26 file contains goods receipts dated up to 24 Sep 2026, so it was not exported on 31 Mar 2026 as
-- assumed. One-time correction of the two batches already loaded; MANIFEST.tsv carries the same date for new loads.
-- =============================================================================

UPDATE meta.load_batch SET as_of_date = DATE '2026-09-26', as_of_is_assumed = FALSE,
       notes = concat_ws('; ', nullif(notes, ''), 'as-of corrected to 2026-09-26 by 200_po_export_date.sql (file metadata)')
WHERE source_name = 'ERP_PURCHASE_ORDER' AND status = 'LOADED'
  AND file_name IN ('ERP_PURCHASE_ORDER__FY2025-26.xlsx', 'ERP_PURCHASE_ORDER__FY2026-27.xlsx');

INSERT INTO meta.schema_version (version, migration_file, description)
VALUES ('2.12', '200_po_export_date.sql', 'Pending PO exports dated 26 Sep 2026 (file metadata), not assumed');
