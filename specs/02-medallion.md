# Spec 02 — Medallion Pipeline

## Bronze

**Expectation:** raw ingestion, schema-on-read, no data loss, lineage metadata.

### Rules

1. Read `data/raw_tickets.csv` as-is (do not edit the file).
2. Insert every row into `bronze.raw_tickets` with all source columns as TEXT.
3. Set `source_file = 'data/raw_tickets.csv'`, `ingested_at = now()`, `row_hash = sha256(concat of raw fields)`.
4. **Idempotency:** `ON CONFLICT (row_hash) DO NOTHING` (or truncate-by-run + reload with same hashes).
5. Log to `meta.pipeline_runs` with layer=`bronze`.

## Silver

**Expectation:** cleansed, deduplicated, typed, validated. Rules must be documented with rationale.

### Cleaning rules (v1)

| Rule | Why |
| --- | --- |
| Drop rows with empty/`NULL`/`???` ticket_id | Cannot key or dedupe without an ID |
| Parse `created_at` / `resolved_at` with multi-format parsers (ISO, `DD-Mon-YYYY`, space-separated) | Source uses mixed date formats |
| If `resolved_at` < `created_at`, set `resolved_at` NULL and flag `date_anomaly` | Impossible chronology in source |
| Normalize `priority` → `{critical, high, medium, low, unknown}` via alias map (`hi`→high, `crit`→critical, `urgent!!!`→critical, empty/`???`/`null`→unknown) | 22+ messy labels |
| Normalize `status` → `{open, in_progress, pending_vendor, escalated, resolved, closed, unknown}` | Mixed case + junk (`NULL`, `???`) |
| Canonicalize `category` via synonym map (e.g. `power issue`→`electrical`, `pest`/`exterminator`→`pest_control`, `fire/safety`→`fire_safety`) | 115 near-duplicate categories |
| Trim whitespace; empty strings → NULL for optional fields | CSV empties are not typed nulls |
| Cast `cost` / `sla_hours` to numeric; invalid → NULL | Non-numeric noise |
| Deduplicate on `ticket_id` keeping latest `created_at` then highest `row_hash` | Duplicate ticket_ids in bronze |

### Lineage on silver

Keep `source_row_hash`, `bronze_ingested_at`, `silver_run_id`, `cleaning_flags` (TEXT[] / JSONB).

## Gold

**Expectation:** 2–3 business-ready models with justification.

| Model | Justification |
| --- | --- |
| `gold.ticket_volume_by_building_category` | Facilities ops need volume by site and failure mode for staffing |
| `gold.sla_performance` | SLA hours vs actual resolution latency; breach rate by priority/status |
| `gold.cost_by_assignee` | Vendor / in-house spend control |

Rebuild is **idempotent**: `TRUNCATE` gold table then `INSERT … SELECT` from silver for the run.

## Logging

Every stage writes `meta.pipeline_runs` (`started` → `succeeded`/`failed`) with row counts and message.

## Orchestration

```bash
python -m src.pipeline.run_all
# or
docker compose up --build
```
