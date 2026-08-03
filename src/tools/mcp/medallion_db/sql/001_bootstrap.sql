-- 001_bootstrap.sql — schemas + bronze + meta
-- Safe to re-run.

CREATE SCHEMA IF NOT EXISTS bronze;
CREATE SCHEMA IF NOT EXISTS silver;
CREATE SCHEMA IF NOT EXISTS gold;
CREATE SCHEMA IF NOT EXISTS meta;

CREATE TABLE IF NOT EXISTS meta.pipeline_runs (
    run_id       UUID NOT NULL,
    layer        TEXT NOT NULL CHECK (layer IN ('bronze', 'silver', 'gold')),
    status       TEXT NOT NULL CHECK (status IN ('started', 'succeeded', 'failed')),
    row_count    BIGINT,
    message      TEXT,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at  TIMESTAMPTZ,
    details      JSONB DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_run_id ON meta.pipeline_runs (run_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_layer ON meta.pipeline_runs (layer, started_at DESC);

CREATE TABLE IF NOT EXISTS bronze.raw_tickets (
    ticket_id         TEXT,
    created_at        TEXT,
    resolved_at       TEXT,
    category          TEXT,
    priority          TEXT,
    status            TEXT,
    building          TEXT,
    description       TEXT,
    submitted_by      TEXT,
    assigned_to       TEXT,
    resolution_notes  TEXT,
    cost              TEXT,
    sla_hours         TEXT,
    source_file       TEXT NOT NULL,
    ingested_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    row_hash          TEXT NOT NULL,
    ingest_run_id     UUID NOT NULL,
    PRIMARY KEY (row_hash)
);

CREATE INDEX IF NOT EXISTS idx_bronze_ticket_id ON bronze.raw_tickets (ticket_id);
CREATE INDEX IF NOT EXISTS idx_bronze_ingest_run ON bronze.raw_tickets (ingest_run_id);
