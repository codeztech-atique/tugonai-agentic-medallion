-- 002_silver_gold.sql — typed silver + gold aggregations
-- Safe to re-run (IF NOT EXISTS / recreate views via tables).

CREATE TABLE IF NOT EXISTS silver.tickets (
    ticket_id           TEXT PRIMARY KEY,
    created_at          TIMESTAMPTZ,
    resolved_at         TIMESTAMPTZ,
    category            TEXT,
    category_raw        TEXT,
    priority            TEXT,
    priority_raw        TEXT,
    status              TEXT,
    status_raw          TEXT,
    building            TEXT,
    description         TEXT,
    submitted_by        TEXT,
    assigned_to         TEXT,
    resolution_notes    TEXT,
    cost                NUMERIC(12, 2),
    sla_hours           NUMERIC(10, 2),
    resolution_hours    NUMERIC(12, 2),
    sla_breached        BOOLEAN,
    date_anomaly        BOOLEAN DEFAULT FALSE,
    source_row_hash     TEXT,
    bronze_ingested_at  TIMESTAMPTZ,
    silver_run_id       UUID NOT NULL,
    cleaning_flags      JSONB DEFAULT '[]'::jsonb,
    transformed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_silver_building ON silver.tickets (building);
CREATE INDEX IF NOT EXISTS idx_silver_category ON silver.tickets (category);
CREATE INDEX IF NOT EXISTS idx_silver_priority ON silver.tickets (priority);
CREATE INDEX IF NOT EXISTS idx_silver_status ON silver.tickets (status);
CREATE INDEX IF NOT EXISTS idx_silver_assignee ON silver.tickets (assigned_to);

CREATE TABLE IF NOT EXISTS gold.ticket_volume_by_building_category (
    building        TEXT,
    category        TEXT,
    status          TEXT,
    ticket_count    BIGINT NOT NULL,
    gold_run_id     UUID NOT NULL,
    built_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (building, category, status)
);

CREATE TABLE IF NOT EXISTS gold.sla_performance (
    priority            TEXT,
    status              TEXT,
    ticket_count        BIGINT NOT NULL,
    avg_resolution_hours NUMERIC(12, 2),
    median_resolution_hours NUMERIC(12, 2),
    breach_count        BIGINT NOT NULL,
    breach_rate         NUMERIC(8, 4),
    gold_run_id         UUID NOT NULL,
    built_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (priority, status)
);

CREATE TABLE IF NOT EXISTS gold.cost_by_assignee (
    assigned_to         TEXT,
    ticket_count        BIGINT NOT NULL,
    tickets_with_cost   BIGINT NOT NULL,
    total_cost          NUMERIC(14, 2),
    avg_cost            NUMERIC(12, 2),
    gold_run_id         UUID NOT NULL,
    built_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (assigned_to)
);
