-- =============================================================================
-- 090_insight.sql  |  Migration (schema v2.0, part 3 of 3)
-- What the agents produce: forecasts, recommendations (with the human decision
-- taken on each) and alerts. Stored so every piece of advice is auditable and
-- its accuracy can be measured (rule BR-028).
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS insight;
COMMENT ON SCHEMA insight IS 'Agent outputs: model runs, forecasts, recommendations with human decisions, alerts';

CREATE TABLE insight.model_run (
    run_id           BIGINT       GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    agent            VARCHAR(30)  NOT NULL CHECK (agent IN ('STOCK','OPERATIONS','EXECUTIVE','MARKETING','COMMERCE',
                                                         'PRODUCT','FINANCE','CUSTOMER','DESIGN')),
    run_type         VARCHAR(30)  NOT NULL,                  -- e.g. DEMAND_FORECAST, REPLENISHMENT, ALERT_SCAN
    model_name       VARCHAR(100) NOT NULL,
    model_version    VARCHAR(40)  NOT NULL,
    parameters       VARCHAR(4000),                          -- JSON text, kept as text for portability
    data_as_of_date  DATE         NOT NULL,
    status           VARCHAR(10)  NOT NULL DEFAULT 'RUNNING' CHECK (status IN ('RUNNING','SUCCEEDED','FAILED')),
    started_at       TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at      TIMESTAMP,
    notes            VARCHAR(1000),
    CONSTRAINT ck_model_run_finished CHECK ((status = 'RUNNING') = (finished_at IS NULL))
);

CREATE TABLE insight.demand_forecast (
    run_id             BIGINT        NOT NULL REFERENCES insight.model_run (run_id),
    product_key        INTEGER       NOT NULL REFERENCES core.dim_product (product_key),
    location_key       SMALLINT      NOT NULL REFERENCES core.dim_location (location_key),
    channel_key        SMALLINT      NOT NULL REFERENCES core.dim_channel (channel_key),
    period_grain       VARCHAR(5)    NOT NULL CHECK (period_grain IN ('DAY','WEEK','MONTH')),
    period_start_date  DATE          NOT NULL,
    forecast_qty       NUMERIC(14,3) NOT NULL CHECK (forecast_qty >= 0),
    lower_qty          NUMERIC(14,3) CHECK (lower_qty >= 0),
    upper_qty          NUMERIC(14,3) CHECK (upper_qty >= 0),
    PRIMARY KEY (run_id, product_key, location_key, channel_key, period_grain, period_start_date),
    CONSTRAINT ck_forecast_band CHECK (lower_qty IS NULL OR upper_qty IS NULL OR (lower_qty <= forecast_qty AND forecast_qty <= upper_qty))
);

CREATE TABLE insight.recommendation (
    recommendation_id   BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id              BIGINT        NOT NULL REFERENCES insight.model_run (run_id),
    recommendation_type VARCHAR(20)   NOT NULL CHECK (recommendation_type IN
                            ('REORDER','TRANSFER','EXPEDITE','LIQUIDATE','RECALL_FROM_PARTNER','OTHER')),
    product_key         INTEGER       NOT NULL REFERENCES core.dim_product (product_key),
    from_location_key   SMALLINT      REFERENCES core.dim_location (location_key),
    to_location_key     SMALLINT      REFERENCES core.dim_location (location_key),
    supplier_partner_key INTEGER      REFERENCES core.dim_partner (partner_key),
    quantity            NUMERIC(14,3) CHECK (quantity > 0),
    reason              VARCHAR(2000) NOT NULL,
    rule_ids            VARCHAR(200),                         -- business rules the reasoning relied on, e.g. 'BR-022, BR-025'
    priority            VARCHAR(6)    NOT NULL CHECK (priority IN ('HIGH','MEDIUM','LOW')),
    status              VARCHAR(10)   NOT NULL DEFAULT 'PROPOSED' CHECK (status IN ('PROPOSED','ACCEPTED','REJECTED','EXPIRED')),
    decided_by          VARCHAR(100),
    decided_at          TIMESTAMP,
    decision_note       VARCHAR(1000),
    created_at          TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_recommendation_decided CHECK ((status IN ('ACCEPTED','REJECTED')) = (decided_by IS NOT NULL AND decided_at IS NOT NULL)),
    CONSTRAINT ck_recommendation_transfer CHECK (recommendation_type <> 'TRANSFER' OR (from_location_key IS NOT NULL AND to_location_key IS NOT NULL))
);

CREATE TABLE insight.alert_rule (
    alert_code      VARCHAR(40)   PRIMARY KEY,
    description     VARCHAR(500)  NOT NULL,
    agent           VARCHAR(30)   NOT NULL,
    metric          VARCHAR(200)  NOT NULL,
    threshold       VARCHAR(200)  NOT NULL,
    severity        VARCHAR(8)    NOT NULL CHECK (severity IN ('CRITICAL','WARNING','INFO')),
    owner           VARCHAR(100)  NOT NULL,
    is_active       BOOLEAN       NOT NULL DEFAULT TRUE
);

CREATE TABLE insight.alert_event (
    alert_id         BIGINT        GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    alert_code       VARCHAR(40)   NOT NULL REFERENCES insight.alert_rule (alert_code),
    run_id           BIGINT        REFERENCES insight.model_run (run_id),
    product_key      INTEGER       REFERENCES core.dim_product (product_key),
    location_key     SMALLINT      REFERENCES core.dim_location (location_key),
    channel_key      SMALLINT      REFERENCES core.dim_channel (channel_key),
    metric_value     NUMERIC(18,4),
    threshold_value  NUMERIC(18,4),
    message          VARCHAR(1000) NOT NULL,
    raised_at        TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status           VARCHAR(12)   NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','ACKNOWLEDGED','RESOLVED','DISMISSED')),
    handled_by       VARCHAR(100),
    handled_at       TIMESTAMP,
    CONSTRAINT ck_alert_handled CHECK ((status = 'OPEN') = (handled_at IS NULL))
);

INSERT INTO meta.schema_version (version, migration_file, description) VALUES ('2.0','090_insight.sql','Insight schema for agent outputs');
