-- =============================================================================
-- 060_ref_partner_channel.sql  |  Migration (schema v1.2)
--  1. Domestic invoices have no channel field: their channel comes from the
--     partner type (franchise -> FRANCHISE, ...) or, for partners whose type
--     spans several channels (quick commerce), from the partner itself.
--  2. GST state codes needed by Instamart facility cities.
-- =============================================================================

-- Default channel for partner types that map to exactly one channel.
CREATE TABLE ref.partner_type_channel (
    partner_type   VARCHAR(30) PRIMARY KEY REFERENCES ref.partner_type (partner_type),
    channel_code   VARCHAR(40) NOT NULL   REFERENCES ref.channel_master (channel_code),
    is_confirmed   BOOLEAN     NOT NULL DEFAULT FALSE,
    notes          VARCHAR(500)
);

-- Per-partner channel override (e.g. Kiranakart Technologies -> BLINKIT).
-- Wins over ref.partner_type_channel when set.
ALTER TABLE ref.partner_list
    ADD COLUMN channel_code VARCHAR(40) REFERENCES ref.channel_master (channel_code);

INSERT INTO ref.gst_state (gst_state_code, state_name) VALUES
 ('04','Chandigarh'), ('18','Assam'), ('32','Kerala'), ('37','Andhra Pradesh');
