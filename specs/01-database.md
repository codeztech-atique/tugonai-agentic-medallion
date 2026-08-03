# Spec 01 — Database

## Provider

- **Primary (AgentCore cloud):** [Neon](https://neon.tech) free PostgreSQL — publicly reachable.
- **Local demo:** Postgres 16 via `docker-compose.yml`.

Set `DATABASE_URL` in `.env` (never commit secrets).

```
DATABASE_URL=postgresql://user:pass@host/tugonai?sslmode=require
```

## Schemas

| Schema | Purpose |
| --- | --- |
| `bronze` | Raw land — schema-on-read, no loss |
| `silver` | Typed, cleansed, deduplicated |
| `gold` | Business aggregations |
| `meta` | Pipeline run logs / lineage helpers |

## Tables

### `meta.pipeline_runs`

| Column | Type | Notes |
| --- | --- | --- |
| `run_id` | UUID PK | One id can span layers |
| `layer` | TEXT | `bronze` / `silver` / `gold` |
| `status` | TEXT | `started` / `succeeded` / `failed` |
| `row_count` | BIGINT | Rows written or processed |
| `message` | TEXT | Human-readable summary |
| `started_at` | TIMESTAMPTZ | |
| `finished_at` | TIMESTAMPTZ | nullable until complete |
| `details` | JSONB | Extra metrics |

### `bronze.raw_tickets`

All CSV fields stored as **TEXT** (schema-on-read) plus lineage:

| Column | Type |
| --- | --- |
| `ticket_id` … `sla_hours` | TEXT (13 source columns) |
| `source_file` | TEXT |
| `ingested_at` | TIMESTAMPTZ |
| `row_hash` | TEXT | SHA-256 of raw column payload |
| `ingest_run_id` | UUID |

Unique index on `(row_hash)` for idempotent re-ingest (skip duplicates).

### `silver.tickets`

Typed ticket facts (created by pipeline / schema agent DDL). See `specs/02-medallion.md`.

### Gold tables

- `gold.ticket_volume_by_building_category`
- `gold.sla_performance`
- `gold.cost_by_assignee`

## Bootstrap

Apply `sql/001_bootstrap.sql` then `sql/002_silver_gold.sql` (or let pipeline create silver/gold).

```bash
psql "$DATABASE_URL" -f sql/001_bootstrap.sql
psql "$DATABASE_URL" -f sql/002_silver_gold.sql
```
