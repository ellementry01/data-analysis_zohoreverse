-- ============================================================================
-- 230_store_status.sql — schema 2.15: the business's store status sheet (2 Nov 2026)
-- ----------------------------------------------------------------------------
-- The sheet lists every store with its type (COCO = own store, Franchise, SIS) and status (Running / Closed).
-- The 12 franchise accounts and Shoppers Stop (14 SIS counters, one billing account) become sale-or-return partners
-- (ref.partner_list, BR-035), each with a partner stock location. SIS counters are run by the retailer, so
-- location_master.operated_by gains 'SIS'. Data changes are in the seeds; this migration only widens the check.
-- ============================================================================

ALTER TABLE ref.location_master DROP CONSTRAINT IF EXISTS location_master_operated_by_check;
ALTER TABLE ref.location_master ADD CONSTRAINT location_master_operated_by_check
    CHECK (operated_by IN ('SELF','AMAZON','BLINKIT','INSTAMART','FRANCHISE','SIS','OTHER'));

INSERT INTO meta.schema_version (version, migration_file, description)
VALUES ('2.15', '230_store_status.sql', 'Store status sheet: franchise and SIS partners, store types and status');
