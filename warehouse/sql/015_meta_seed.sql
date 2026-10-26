-- =============================================================================
-- 015_meta_seed.sql  |  Registered sources and pipeline settings
-- Facts in known_issues were observed in the sample files (Apr-Sep 2026).
-- =============================================================================

INSERT INTO meta.pipeline_setting (setting_key, setting_value, description) VALUES
 ('prototype_period_start', '2025-04-01',   'First business date loaded for the prototype'),
 ('prototype_period_end',   '2026-09-15',   'Last business date kept. Rows after this are excluded at staging'),
 ('reporting_currency',     'INR',          'All amounts stored in INR'),
 ('reporting_timezone',     'Asia/Kolkata', 'All source timestamps are IST, stored without time zone');

INSERT INTO meta.source_registry
 (source_name, source_system, description, grain, load_type, natural_key, date_format, known_issues) VALUES
('ERP_RETAIL_SALES','ERP','ERP Retail Sales register: D2C website, marketplaces, own stores, Amazon FBA',
 'One row per invoice line','TRANSACTIONAL','BILLNUM + PRODNUM + occurrence','Excel datetime cells',
 'CHANNELNAME is the billing LOCATION, not the sales channel. Channel comes from CONTACTNAME (business-confirmed); 08 Jaipur Branch = Bagru warehouse. Headline value = PRODDOCVALUE (excl. GST); PRODASSESSABLEVALUE INCLUDES GST. Non-product lines present: SHIPPING R (shipping charge), COCB04-06 (carry bags), Gifting. 144 Jaipur Branch rows have blank payment mode. Contains customer PII.'),
('ERP_DOMESTIC_SALES','ERP','ERP Domestic Sales register: B2B / wholesale / franchise, group companies, employees',
 'One row per invoice line','TRANSACTIONAL','BILLNUM + PRODNUM + occurrence','Excel datetime cells',
 'Only true B2B invoices are final. Franchise, SIS and quick-commerce invoices are sale-or-return (names to be supplied). Dileep group names = exports billed cost-to-cost. Unlisted person names = employees (exhibition stock). Headline value = Taxable (excl. GST); Net Amount includes GST. 209 lines have blank Taxable. 2 SINGAPORE rows.'),
('ERP_RETAIL_RETURN','ERP','ERP Retail Sales Return register (customer returns incl. returns received at Amazon FBA)',
 'One row per return line','TRANSACTIONAL','RETURNNUM + PRODNUM + occurrence','Excel datetime cells',
 'Received file runs to 22-Sep; cut-off must be applied. BILLNUM links to original sale (93% matched in sample). SHIPPING R reversal lines present.'),
('ERP_DOMESTIC_RETURN','ERP','ERP Domestic Sale Return register (B2B returns, Blinkit unsold stock, employee exhibition returns)',
 'One row per credit-note line','TRANSACTIONAL','BILLNUM (credit note) + PRODNUM + occurrence','Text DD/MM/YYYY in RTNFROMCUSTDT',
 'RTNFROMCUSTDT ~10% malformed, e.g. "08/04/2026;08/04/2026" (same date repeated). Return date column name differs from retail return file.'),
('ERP_STOCK_TRANSFER_OUT','ERP','ERP Stock Transfer (outward) register',
 'One row per transfer document line','TRANSACTIONAL','DOCNUM + PRODNUM + occurrence','Excel datetime cells',
 'Quantities are negative. Sending location is NOT a column; only encoded in DOCNUM prefix (JPR/, THA/, HYD, BAG/, ...). CONTACTNAME is the receiving location in long form.'),
('ERP_STOCK_TRANSFER_IN','ERP','ERP Stock Transfer Inward register',
 'One row per receipt document line','TRANSACTIONAL','DOCNUM + PRODNUM + occurrence','Excel datetime cells',
 'REFDOCNUM1 links to outward DOCNUM (100% matched in sample). Receiving location only in DOCNUM prefix. 2 duplicate DOCNUM+PRODNUM pairs, so line occurrence is required.'),
('ERP_PURCHASE_ORDER','ERP','ERP Pending Purchase Order report (full FY state incl. received/closed)',
 'One row per PO line','STATE_SNAPSHOT','PO No. + SKU No.','Excel datetime cells',
 'Contains return-inward documents from B2B customers and own stores, not only factory purchases. Classified via ref.partner_list (factory list pending).'),
('ERP_INVENTORY_SNAPSHOT','ERP','ERP Channelwise Stock report (all ERP locations)',
 'One row per SKU x location (after unpivot)','POINT_IN_TIME_SNAPSHOT','snapshot date + location + PRODNUM','Report header text M/D/YYYY',
 'Wide pivoted .xls: 38 location blocks of Qty + Active MRP. 19 header rows before data. Includes Packaging / Accessory / Stores items. History cannot be re-pulled: must be captured daily.'),
('PRODUCT_MASTER','PRODUCT_MASTER','Ellementry Final Master (Sheet1): active vs discontinued trading SKUs',
 'One row per SKU','MASTER','Prod Num','n/a',
 'Only Sheet1 is structured. Other sheets are working sheets and are not loaded.'),
('WMS_DISPATCH','WMS','Warehouse dispatch / order fulfilment export',
 'One row per outbound delivery','TRANSACTIONAL','Outbound Delivery No','M/D/YYYY H24:MI (US order)',
 'B2C only; all dispatched from the Bagru warehouse (business-confirmed). Channel is in Site Location. The Customer column is a placeholder (999999). SKU cell can hold several SKUs separated by commas. Long numeric IDs arrive in scientific notation (e.g. 1.60396E+13) = precision already lost at export. Contains customer PII.'),
('BLINKIT_SALES','BLINKIT','Blinkit seller panel sales (consumer sell-out)',
 'One row per order line','TRANSACTIONAL','Order Id + Item Id','YYYY-MM-DD',
 'Uses Ellementry SKU directly (ELLE SKU).'),
('BLINKIT_INVENTORY','BLINKIT','Blinkit Stock On Hand by feeder warehouse',
 'One row per item x feeder warehouse','POINT_IN_TIME_SNAPSHOT','snapshot date + Warehouse Facility ID + Item ID','n/a',
 'Net scheduled inventory can be negative. Meaning NOT yet confirmed with Blinkit; field is stored but excluded from stock metrics until confirmed.'),
('INSTAMART_SALES','INSTAMART','Instamart sales report (consumer sell-out)',
 'One row per date x store x item','TRANSACTIONAL','ORDERED_DATE + STORE_ID + ITEM_CODE','YYYY-MM-DD',
 'Brand Metrics sheet is city-level marketing data, not loaded in this phase.'),
('INSTAMART_INVENTORY','INSTAMART','Instamart item inventory by facility',
 'One row per item x facility','POINT_IN_TIME_SNAPSHOT','snapshot date + FacilityName + SkuCode','n/a',
 NULL);
