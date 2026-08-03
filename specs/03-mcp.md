# Spec 03 — Medallion DB MCP Server

## Role

Single FastMCP server (`medallion-db`) is the **only** data plane for agents. Deployed to AgentCore Runtime and attached to the Gateway as an MCP target.

Path: `src/tools/mcp/medallion_db/`

## Tools

| Tool | Args | Returns | Guardrails |
| --- | --- | --- | --- |
| `list_schemas_tables` | — | JSON list of schema.table | Only `bronze`,`silver`,`gold`,`meta` |
| `describe_table` | `schema`, `table` | columns, types, nullable | Schema allowlist |
| `sample_rows` | `schema`, `table`, `limit` (default 20, max 100) | JSON rows | Schema allowlist |
| `profile_table` | `schema`, `table`, `columns?` | null rates, cardinality, numeric min/max | Schema allowlist |
| `run_sql_readonly` | `sql` | JSON rows (max 500) | Must be single SELECT; block `;` multi-statements |
| `execute_sql` | `sql` | `{ok, rowcount, message}` | DDL/DML only against allowlisted schemas; reject `DROP DATABASE`, `TRUNCATE meta` without care; reject cross-schema attacks |
| `ingest_bronze_csv` | `source_file?`, `run_id?` | counts inserted/skipped | Reads packaged CSV or mounted path |
| `log_pipeline_run` | `run_id`, `layer`, `status`, `row_count?`, `message?`, `details?` | run record | Layers allowlist |

## Environment

| Var | Required | Description |
| --- | --- | --- |
| `DATABASE_URL` | Yes | Postgres connection string |
| `CSV_PATH` | No | Default `data/raw_tickets.csv` or `/app/data/raw_tickets.csv` |

## Deploy

```bash
cd src/tools/mcp/medallion_db
agentcore deploy --region ap-south-1
# Attach: python attach_mcp_target.py --name medallion-db --endpoint <RUNTIME>/mcp
```

## Local

```bash
python main.py   # streamable-http on :8000
```
