-- ============================================================================
-- 240_agents.sql — schema 2.16: the agent runner's first rules (AI assistants plan, Phase 7; PRD-001)
-- ----------------------------------------------------------------------------
-- `python -m agents run all <db>` (or `python dw.py agents run all`) runs after a successful build and writes
-- alerts to insight.alert_event. Only three rules are switched on, chosen by the owner on 2026-11-10:
--   STK-A01 stock-out with demand, STK-A02 low cover, OPS-A02 purchase order overdue.
-- Thresholds are PRD-001's PROPOSED values, held in meta.pipeline_setting so every run records what it used.
-- One open event per condition (identity_key); a later run that no longer finds the condition resolves it.
-- People's decisions on alerts are recorded in the app, not here: the app reads the warehouse read-only.
-- ============================================================================

ALTER TABLE insight.alert_rule ADD COLUMN rule_name VARCHAR(80);
ALTER TABLE insight.alert_rule ADD COLUMN process_name VARCHAR(100);
ALTER TABLE insight.alert_rule ADD COLUMN setting_keys VARCHAR(400);

ALTER TABLE insight.alert_event ADD COLUMN severity VARCHAR(8) CHECK (severity IN ('CRITICAL','WARNING','INFO'));
ALTER TABLE insight.alert_event ADD COLUMN identity_key VARCHAR(300);
ALTER TABLE insight.alert_event ADD COLUMN document_ref VARCHAR(100);
ALTER TABLE insight.alert_event ADD COLUMN details VARCHAR(4000);
ALTER TABLE insight.alert_event ADD COLUMN last_seen_run_id BIGINT REFERENCES insight.model_run (run_id);
ALTER TABLE insight.alert_event ADD COLUMN last_seen_at TIMESTAMP;
COMMENT ON COLUMN insight.alert_rule.rule_name IS 'Short name of the rule shown in the app';
COMMENT ON COLUMN insight.alert_rule.process_name IS 'Business process whose data the rule needs; the rule is skipped while it has none (meta.business_process)';
COMMENT ON COLUMN insight.alert_rule.setting_keys IS 'Settings in meta.pipeline_setting the rule''s thresholds come from, comma-separated';
COMMENT ON COLUMN insight.alert_event.severity IS 'Critical, warning or info for this event (a rule may raise either, e.g. an overdue PO turns critical)';
COMMENT ON COLUMN insight.alert_event.identity_key IS 'What the alert is about (rule + product + location, or rule + document); at most one open event per key';
COMMENT ON COLUMN insight.alert_event.document_ref IS 'Document the alert is about, e.g. the purchase order number';
COMMENT ON COLUMN insight.alert_event.details IS 'The inputs behind the alert, as JSON text';
COMMENT ON COLUMN insight.alert_event.last_seen_run_id IS 'Latest agent run that still found the condition';
COMMENT ON COLUMN insight.alert_event.last_seen_at IS 'When a run last found the condition';
CREATE UNIQUE INDEX ux_alert_event_one_open ON insight.alert_event (identity_key)
    WHERE status IN ('OPEN', 'ACKNOWLEDGED');

INSERT INTO insight.alert_rule (alert_code, rule_name, description, agent, metric, threshold, severity, owner, is_active,
                                process_name, setting_keys) VALUES
('STK-A01', 'Stock-out with demand',
 'A continued product has no sellable stock at a location where it sold or was sent out in the last 30 days',
 'STOCK', 'sellable units; units sold and sent in 30 days', 'sellable = 0 with demand in 30 days', 'CRITICAL', 'Owner', TRUE,
 'Stock position', ''),
('STK-A02', 'Low cover',
 'A continued product''s sellable stock at a location lasts fewer days than the threshold at its 30-day rate',
 'STOCK', 'days of cover', 'days of cover < stock.low_cover_days', 'WARNING', 'Owner', TRUE,
 'Stock position', 'stock.low_cover_days'),
('OPS-A02', 'Purchase order overdue',
 'A purchase order (document remark Purchase, BR-031) has units still pending after its due date',
 'OPERATIONS', 'days past due', 'past due with pending units; CRITICAL above ops.po_overdue_critical_days', 'WARNING',
 'Owner', TRUE, 'Purchasing', 'ops.po_overdue_critical_days');

INSERT INTO meta.pipeline_setting (setting_key, setting_value, description) VALUES
('agent.stock.enabled', 'true', 'Master switch for the Stock agent (PRD-001 6.4)'),
('agent.operations.enabled', 'true', 'Master switch for the Operations agent (PRD-001 6.4)'),
('stock.low_cover_days', '7', 'STK-A02: alert when sellable stock covers fewer days than this (PRD-001 PROPOSED 7; owner to confirm after review)'),
('ops.po_overdue_critical_days', '14', 'OPS-A02: an overdue PO becomes CRITICAL after this many days (PRD-001 PROPOSED 14; owner to confirm after review)');

-- What the app reads (mart is the only schema the app's login may see)
CREATE OR REPLACE VIEW mart.v_agent_alerts AS
SELECT e.alert_id, e.alert_code, r.rule_name, r.agent, coalesce(e.severity, r.severity) AS severity, e.status,
       p.sku_code, p.product_name, l.location_code, l.location_name, e.document_ref,
       e.metric_value, e.threshold_value, e.message, e.details,
       e.raised_at, e.raised_at::DATE AS raised_date, e.last_seen_at, e.handled_by, e.handled_at,
       mr.data_as_of_date AS raised_as_of_date, ls.data_as_of_date AS last_seen_as_of_date
FROM insight.alert_event e
JOIN insight.alert_rule r ON r.alert_code = e.alert_code
LEFT JOIN core.dim_product p ON p.product_key = e.product_key
LEFT JOIN core.dim_location l ON l.location_key = e.location_key
LEFT JOIN insight.model_run mr ON mr.run_id = e.run_id
LEFT JOIN insight.model_run ls ON ls.run_id = e.last_seen_run_id;

CREATE OR REPLACE VIEW mart.v_agent_rules AS
SELECT r.alert_code, r.rule_name, r.description, r.agent, r.metric, r.threshold, r.severity, r.is_active, r.process_name,
       r.setting_keys,
       (SELECT string_agg(s.setting_key || ' = ' || s.setting_value, '; ' ORDER BY s.setting_key)
        FROM meta.pipeline_setting s
        WHERE s.setting_key = ANY (string_to_array(nullif(r.setting_keys, ''), ','))) AS current_settings
FROM insight.alert_rule r;

CREATE OR REPLACE VIEW mart.v_agent_runs AS
SELECT run_id, agent, run_type, model_name, model_version, data_as_of_date, status, started_at, finished_at, notes,
       parameters
FROM insight.model_run;

INSERT INTO meta.schema_version (version, migration_file, description)
VALUES ('2.16', '240_agents.sql', 'Agent runner: first alert rules (STK-A01, STK-A02, OPS-A02), one open event per condition');
