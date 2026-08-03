# Sample agent I/O

## Schema Inference Agent

**Input**

```text
Propose a typed silver schema for bronze.raw_tickets.
Sample rows, then return DDL + transform SQL as JSON.
Do not overwrite silver.tickets — use silver.tickets_proposed if applying.
```

**Example output shape**

```json
{
  "ddl": [
    "CREATE TABLE IF NOT EXISTS silver.tickets_proposed (ticket_id TEXT PRIMARY KEY, created_at TIMESTAMPTZ, priority TEXT, status TEXT, category TEXT, cost NUMERIC(12,2), sla_hours NUMERIC(10,2), source_row_hash TEXT);"
  ],
  "transform_sql": "INSERT INTO silver.tickets_proposed (...) SELECT ... FROM bronze.raw_tickets WHERE ticket_id IS NOT NULL ON CONFLICT DO NOTHING;",
  "rationale": [
    "created_at/resolved_at use mixed formats → TIMESTAMPTZ with tolerant casts",
    "priority/status are free-text aliases → normalized TEXT enums",
    "cost/sla_hours should be numeric for gold aggregations"
  ],
  "trust": "review_required"
}
```

## Data Quality Agent

**Input**

```text
Profile bronze.raw_tickets. Propose high-severity cleaning rules with why + SQL.
```

**Example output shape**

```json
{
  "profile_summary": {
    "row_count": 10280,
    "notable_issues": [
      "priority has 20+ aliases and ~10% null/junk",
      "resolved_at often empty or earlier than created_at",
      "category has 100+ near-duplicates"
    ]
  },
  "rules": [
    {
      "name": "normalize_priority",
      "why": "Without normalization, gold SLA by priority fragments across hi/HIGH/crit",
      "sql_or_python": "CASE lower(trim(priority)) WHEN 'hi' THEN 'high' ... ELSE 'unknown' END",
      "severity": "high"
    },
    {
      "name": "drop_invalid_ticket_id",
      "why": "Cannot dedupe or join facts without a stable ticket key",
      "sql_or_python": "WHERE ticket_id IS NOT NULL AND trim(ticket_id) NOT IN ('', 'NULL', '???')",
      "severity": "high"
    }
  ]
}
```
