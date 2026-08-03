# Spec 04 — Agents

## Shared pattern

Both agents:

1. Load `gateway_config.json` via `GatewaySession`
2. Obtain Cognito JWT
3. Open MCP client to Gateway (semantic search ON)
4. Use only Medallion DB MCP tools for data access
5. Return structured JSON in the final answer when proposing DDL/rules

Framework: Strands + `BedrockAgentCoreApp`  
Region: `ap-south-1`  
Model default: `apac.anthropic.claude-3-haiku-20240307-v1:0` (cost-safe; override via `MODEL_ID` only when needed)

---

## A) Schema Inference Agent

**Path:** `src/agents/http/strands/schema_agent/`

### Job

Inspect bronze samples → propose typed silver DDL + transform SQL → optionally `execute_sql` into a staging name (`silver.tickets_proposed`) when asked.

### System prompt constraints

- Do not invent columns absent from bronze samples / describe_table.
- Prefer idempotent `CREATE TABLE IF NOT EXISTS` + `INSERT … SELECT`.
- Explain type choices (e.g. why TIMESTAMPTZ vs TEXT).
- Final answer MUST include a JSON block:

```json
{
  "ddl": ["..."],
  "transform_sql": "...",
  "rationale": ["..."],
  "trust": "review_required|safe_to_apply"
}
```

### When to trust vs override

| Trust | Override |
| --- | --- |
| Simple TEXT→typed casts with clear formats | Aggressive DROP/REPLACE of production silver |
| Additive columns with evidence | Columns inferred from a single weird sample |
| Staging table writes | Direct overwrite of gold without review |

### Sample I/O

- **Input:** “Propose a silver schema for bronze.raw_tickets”
- **Output:** DDL for `silver.tickets` + INSERT SELECT with casts + rationale

---

## B) Data Quality Agent

**Path:** `src/agents/http/strands/quality_agent/`

### Job

Profile bronze → propose cleaning/validation rules in natural language **and** SQL/Python → explain **why** each rule matters.

### Output JSON

```json
{
  "profile_summary": {...},
  "rules": [
    {"name": "...", "why": "...", "sql_or_python": "...", "severity": "high|medium|low"}
  ]
}
```

### When to trust vs override

| Trust | Override |
| --- | --- |
| Null-rate flags, alias normalization maps | Dropping >5% of rows without business OK |
| Documented priority/status maps | “Fixing” descriptions with LLM hallucination |

---

## Honesty notes (for README assessment)

Document after first real runs: time saved vs prompt/debug overhead.
