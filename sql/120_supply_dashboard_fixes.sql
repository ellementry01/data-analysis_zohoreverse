-- =============================================================================
-- 120  Schema 2.4: supply / fulfilment / stock dashboard fixes. Additive only.
--   * ERP item master (Product Master List) as a source: fills category, sub-category,
--     HSN, EAN and MRP where no better source has them (raw table, registry row).
--   * meta.load_batch.as_of_is_assumed: an as-of date given as an assumption (D-094)
--     is stored as such, so dashboards can say "export date assumed".
--   * core.dim_courier.courier_group: the courier company behind each WMS spelling
--     (ref.code_mapping domain COURIER).
-- IF NOT EXISTS / ON CONFLICT: a fresh build already has the raw table from 070.
-- =============================================================================

INSERT INTO meta.source_registry (source_name, source_system, description, grain, load_type, natural_key, date_format, known_issues)
VALUES ('ERP_ITEM_MASTER', 'ERP', 'ERP item master (Product Master List): every item code with category, MRP, cost, HSN, EAN',
        'One row per item code', 'MASTER', 'SKU No', 'n/a',
        'Used only to fill attributes no better source holds (Final Master, stock report, invoices). Sheet2/Sheet3 empty.')
ON CONFLICT (source_name) DO NOTHING;

-- ERP_ITEM_MASTER
CREATE TABLE IF NOT EXISTS raw.erp_item_master (
    batch_id           BIGINT  NOT NULL REFERENCES meta.load_batch (batch_id),
    source_row_number  INTEGER NOT NULL,
    sku_no                                   TEXT,
    sdfvb                                    TEXT,
    prodname                                 TEXT,
    proddesc                                 TEXT,
    uomname                                  TEXT,
    prodtypename                             TEXT,
    category                                 TEXT,
    subcategory                              TEXT,
    prodgroupname                            TEXT,
    prodbackofficecode                       TEXT,
    prodbrandname                            TEXT,
    prodclassname                            TEXT,
    proddimtypename                          TEXT,
    proddimlength                            TEXT,
    proddimwidth                             TEXT,
    proddimheight                            TEXT,
    lengthuom                                TEXT,
    proddimvolume                            TEXT,
    proddimnetweight                         TEXT,
    weightuom                                TEXT,
    proddimgrossweight                       TEXT,
    prodpropertyname1                        TEXT,
    prodpropertyname2                        TEXT,
    prodpropertyname3                        TEXT,
    prodpropertyname4                        TEXT,
    prodpropertyname5                        TEXT,
    prodpropertyname6                        TEXT,
    innerproddimtypename                     TEXT,
    innerproddimlength                       TEXT,
    innerproddimwidth                        TEXT,
    innerproddimheight                       TEXT,
    innerlengthuom                           TEXT,
    innerproddimvolume                       TEXT,
    innerproddimnetweight                    TEXT,
    innerweightuom                           TEXT,
    innerproddimgrossweight                  TEXT,
    saccode                                  TEXT,
    prodbarcodenum                           TEXT,
    size                                     TEXT,
    prodfitname                              TEXT,
    prodcolorname                            TEXT,
    prodconditionname                        TEXT,
    prodhsncode                              TEXT,
    mrp                                      TEXT,
    retailprice                              TEXT,
    cost                                     TEXT,
    generalpurchase                          TEXT,
    cgstperc                                 TEXT,
    sgstperc                                 TEXT,
    igstperc                                 TEXT,
    productudf1                              TEXT,
    productudf2                              TEXT,
    productudf3                              TEXT,
    productudf4                              TEXT,
    productudf5                              TEXT,
    productudf6                              TEXT,
    productudf7                              TEXT,
    productudf8                              TEXT,
    createdon                                TEXT,
    createdby                                TEXT,
    lastupdatedon                            TEXT,
    productimgfilename                       TEXT,
    updatedby                                TEXT,
    ean13                                    TEXT,
    prodhsnwisetaxapplicable                 TEXT,
    active_inactive                          TEXT,
    PRIMARY KEY (batch_id, source_row_number)
);
COMMENT ON TABLE raw.erp_item_master IS 'As received from ERP_ITEM_MASTER. Contract: loader/contracts/ERP_ITEM_MASTER.json';
COMMENT ON COLUMN raw.erp_item_master.sku_no IS 'Source header: SKU No';
COMMENT ON COLUMN raw.erp_item_master.sdfvb IS 'Source header: sdfvb';
COMMENT ON COLUMN raw.erp_item_master.prodname IS 'Source header: PRODNAME';
COMMENT ON COLUMN raw.erp_item_master.proddesc IS 'Source header: PRODDESC';
COMMENT ON COLUMN raw.erp_item_master.uomname IS 'Source header: UOMNAME';
COMMENT ON COLUMN raw.erp_item_master.prodtypename IS 'Source header: PRODTYPENAME';
COMMENT ON COLUMN raw.erp_item_master.category IS 'Source header: CATEGORY';
COMMENT ON COLUMN raw.erp_item_master.subcategory IS 'Source header: SUBCATEGORY';
COMMENT ON COLUMN raw.erp_item_master.prodgroupname IS 'Source header: PRODGROUPNAME';
COMMENT ON COLUMN raw.erp_item_master.prodbackofficecode IS 'Source header: PRODBACKOFFICECODE';
COMMENT ON COLUMN raw.erp_item_master.prodbrandname IS 'Source header: PRODBRANDNAME';
COMMENT ON COLUMN raw.erp_item_master.prodclassname IS 'Source header: PRODCLASSNAME';
COMMENT ON COLUMN raw.erp_item_master.proddimtypename IS 'Source header: PRODDIMTYPENAME';
COMMENT ON COLUMN raw.erp_item_master.proddimlength IS 'Source header: PRODDIMLENGTH';
COMMENT ON COLUMN raw.erp_item_master.proddimwidth IS 'Source header: PRODDIMWIDTH';
COMMENT ON COLUMN raw.erp_item_master.proddimheight IS 'Source header: PRODDIMHEIGHT';
COMMENT ON COLUMN raw.erp_item_master.lengthuom IS 'Source header: LENGTHUOM';
COMMENT ON COLUMN raw.erp_item_master.proddimvolume IS 'Source header: PRODDIMVOLUME';
COMMENT ON COLUMN raw.erp_item_master.proddimnetweight IS 'Source header: PRODDIMNETWEIGHT';
COMMENT ON COLUMN raw.erp_item_master.weightuom IS 'Source header: WEIGHTUOM';
COMMENT ON COLUMN raw.erp_item_master.proddimgrossweight IS 'Source header: PRODDIMGROSSWEIGHT';
COMMENT ON COLUMN raw.erp_item_master.prodpropertyname1 IS 'Source header: PRODPROPERTYNAME1';
COMMENT ON COLUMN raw.erp_item_master.prodpropertyname2 IS 'Source header: PRODPROPERTYNAME2';
COMMENT ON COLUMN raw.erp_item_master.prodpropertyname3 IS 'Source header: PRODPROPERTYNAME3';
COMMENT ON COLUMN raw.erp_item_master.prodpropertyname4 IS 'Source header: PRODPROPERTYNAME4';
COMMENT ON COLUMN raw.erp_item_master.prodpropertyname5 IS 'Source header: PRODPROPERTYNAME5';
COMMENT ON COLUMN raw.erp_item_master.prodpropertyname6 IS 'Source header: PRODPROPERTYNAME6';
COMMENT ON COLUMN raw.erp_item_master.innerproddimtypename IS 'Source header: INNERPRODDIMTYPENAME';
COMMENT ON COLUMN raw.erp_item_master.innerproddimlength IS 'Source header: INNERPRODDIMLENGTH';
COMMENT ON COLUMN raw.erp_item_master.innerproddimwidth IS 'Source header: INNERPRODDIMWIDTH';
COMMENT ON COLUMN raw.erp_item_master.innerproddimheight IS 'Source header: INNERPRODDIMHEIGHT';
COMMENT ON COLUMN raw.erp_item_master.innerlengthuom IS 'Source header: INNERLENGTHUOM';
COMMENT ON COLUMN raw.erp_item_master.innerproddimvolume IS 'Source header: INNERPRODDIMVOLUME';
COMMENT ON COLUMN raw.erp_item_master.innerproddimnetweight IS 'Source header: INNERPRODDIMNETWEIGHT';
COMMENT ON COLUMN raw.erp_item_master.innerweightuom IS 'Source header: INNERWEIGHTUOM';
COMMENT ON COLUMN raw.erp_item_master.innerproddimgrossweight IS 'Source header: INNERPRODDIMGROSSWEIGHT';
COMMENT ON COLUMN raw.erp_item_master.saccode IS 'Source header: SACCODE';
COMMENT ON COLUMN raw.erp_item_master.prodbarcodenum IS 'Source header: PRODBARCODENUM';
COMMENT ON COLUMN raw.erp_item_master.size IS 'Source header: SIZE';
COMMENT ON COLUMN raw.erp_item_master.prodfitname IS 'Source header: PRODFITNAME';
COMMENT ON COLUMN raw.erp_item_master.prodcolorname IS 'Source header: PRODCOLORNAME';
COMMENT ON COLUMN raw.erp_item_master.prodconditionname IS 'Source header: PRODCONDITIONNAME';
COMMENT ON COLUMN raw.erp_item_master.prodhsncode IS 'Source header: PRODHSNCODE';
COMMENT ON COLUMN raw.erp_item_master.mrp IS 'Source header: MRP';
COMMENT ON COLUMN raw.erp_item_master.retailprice IS 'Source header: RETAILPRICE';
COMMENT ON COLUMN raw.erp_item_master.cost IS 'Source header: COST';
COMMENT ON COLUMN raw.erp_item_master.generalpurchase IS 'Source header: GENERALPURCHASE';
COMMENT ON COLUMN raw.erp_item_master.cgstperc IS 'Source header: CGSTPERC';
COMMENT ON COLUMN raw.erp_item_master.sgstperc IS 'Source header: SGSTPERC';
COMMENT ON COLUMN raw.erp_item_master.igstperc IS 'Source header: IGSTPERC';
COMMENT ON COLUMN raw.erp_item_master.productudf1 IS 'Source header: PRODUCTUDF1';
COMMENT ON COLUMN raw.erp_item_master.productudf2 IS 'Source header: PRODUCTUDF2';
COMMENT ON COLUMN raw.erp_item_master.productudf3 IS 'Source header: PRODUCTUDF3';
COMMENT ON COLUMN raw.erp_item_master.productudf4 IS 'Source header: PRODUCTUDF4';
COMMENT ON COLUMN raw.erp_item_master.productudf5 IS 'Source header: PRODUCTUDF5';
COMMENT ON COLUMN raw.erp_item_master.productudf6 IS 'Source header: PRODUCTUDF6';
COMMENT ON COLUMN raw.erp_item_master.productudf7 IS 'Source header: PRODUCTUDF7';
COMMENT ON COLUMN raw.erp_item_master.productudf8 IS 'Source header: PRODUCTUDF8';
COMMENT ON COLUMN raw.erp_item_master.createdon IS 'Source header: CREATEDON';
COMMENT ON COLUMN raw.erp_item_master.createdby IS 'Source header: CREATEDBY';
COMMENT ON COLUMN raw.erp_item_master.lastupdatedon IS 'Source header: LASTUPDATEDON';
COMMENT ON COLUMN raw.erp_item_master.productimgfilename IS 'Source header: PRODUCTIMGFILENAME';
COMMENT ON COLUMN raw.erp_item_master.updatedby IS 'Source header: UPDATEDBY';
COMMENT ON COLUMN raw.erp_item_master.ean13 IS 'Source header: EAN13';
COMMENT ON COLUMN raw.erp_item_master.prodhsnwisetaxapplicable IS 'Source header: PRODHSNWISETAXAPPLICABLE';
COMMENT ON COLUMN raw.erp_item_master.active_inactive IS 'Source header: ACTIVE/INACTIVE';


ALTER TABLE meta.load_batch ADD COLUMN IF NOT EXISTS as_of_is_assumed BOOLEAN NOT NULL DEFAULT FALSE;
COMMENT ON COLUMN meta.load_batch.as_of_is_assumed IS 'TRUE when the as-of date was given as an assumption (loader --as-of-assumed), not the known export date';
-- One-time backfill of the two files loaded before the flag existed whose MANIFEST note says the as-of date is assumed:
-- the FY25-26 pending-PO export (D-094) and the product master ('september updated').
UPDATE meta.load_batch SET as_of_is_assumed = TRUE
WHERE (source_name, file_name, as_of_date) IN (('ERP_PURCHASE_ORDER', 'ERP_PURCHASE_ORDER__FY2025-26.xlsx', DATE '2026-03-31'),
                                               ('PRODUCT_MASTER', 'PRODUCT_MASTER__2026-09-15.xlsx', DATE '2026-09-15'));

ALTER TABLE core.dim_courier ADD COLUMN IF NOT EXISTS courier_group VARCHAR(60);
COMMENT ON COLUMN core.dim_courier.courier_group IS 'Courier company (Delhivery, Blue Dart, Ekart...): ref.code_mapping domain COURIER; ''Not recorded'' / ''Other (unmapped)'' otherwise';

INSERT INTO meta.schema_version (version, migration_file, description)
VALUES ('2.4', '120_supply_dashboard_fixes.sql', 'ERP item master source, as-of-assumed flag, courier groups');
