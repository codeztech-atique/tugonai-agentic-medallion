# SQL bootstrap

1. `001_bootstrap.sql` — schemas + `bronze.raw_tickets` + `meta.pipeline_runs`
2. `002_silver_gold.sql` — `silver.tickets` + gold aggregation tables

Applied automatically by `python -m src.pipeline.run_all` and by the MCP `ingest_bronze_csv` bootstrap helper.
