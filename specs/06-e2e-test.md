# Spec 06 — End-to-End Test Plan

## Goal

Prove the live stack works as designed:

```
Agent (Schema / Quality)
  → AgentCore Gateway (OAuth + semantic tool search)
    → Medallion DB MCP
      → Supabase Postgres (bronze / silver / gold / meta)
```

Plus: **short-term session** + **long-term SEMANTIC memory**.

## Prerequisites

- `.env` with `DATABASE_URL` (Supabase)
- `src/gateway/setup/deploy_state.json` present (from deploy)
- AWS credentials for account `485947658225`, region `ap-south-1`
- Python 3.11: `/opt/homebrew/bin/python3.11`

```bash
cd /Users/atique1201gmail.com/Desktop/Development/TugonAI
set -a && source .env && set +a
/opt/homebrew/bin/python3.11 scripts/test_e2e.py
```

Or run cases one at a time (see script flags below).

---

## Deployed IDs (reference)

| Resource | ID |
| --- | --- |
| Memory | `TugonAIMedallionSemanticMemory-QUGvAEC1vO` |
| MCP runtime | `medallion_db_mcp-w54pKjFtvN` |
| Gateway | `tugonai-medallion-gateway-nazoctrccm` |
| Schema agent | `schema_agent-q1mZSw8tgk` |
| Quality agent | `quality_agent-mDMYgOGduC` |

(Authoritative copy: `src/gateway/setup/deploy_state.json`)

---

## Test cases

### T1 — Supabase data plane

| | |
| --- | --- |
| **What** | Bronze/silver/gold tables exist and are populated |
| **How** | Script queries Postgres via `DATABASE_URL` |
| **Pass** | `bronze.raw_tickets` ≥ 10000; `silver.tickets` ≥ 10000; gold tables > 0 rows |

### T2 — MCP runtime (direct)

| | |
| --- | --- |
| **What** | MCP container answers MCP protocol |
| **How** | SigV4 `initialize` + `tools/list` against MCP runtime invocations URL |
| **Pass** | `initialize` returns `serverInfo.name == medallion-db`; `tools/list` includes `list_schemas_tables`, `sample_rows`, `profile_table` |

### T3 — Gateway → MCP

| | |
| --- | --- |
| **What** | Gateway discovers MCP tools via semantic search / OAuth |
| **How** | Cognito token → Gateway MCP `list_tools` |
| **Pass** | At least 5 tools returned; names include medallion DB tools |

### T4 — Schema agent (HTTP runtime)

| | |
| --- | --- |
| **What** | Schema agent uses Gateway tools and can see lakehouse tables |
| **How** | Invoke `schema_agent` with session/actor IDs |
| **Prompt** | `Using tools, list schemas and tables in bronze/silver/gold/meta. Reply with table names only.` |
| **Pass** | Response mentions `raw_tickets` and `tickets` (or equivalent); no model/auth hard errors; `memory_id` present in payload |

### T5 — Quality agent (HTTP runtime)

| | |
| --- | --- |
| **What** | Quality agent profiles bronze via MCP |
| **How** | Invoke `quality_agent` |
| **Prompt** | `Profile bronze.raw_tickets null rates for priority and status. Return a short JSON profile_summary.` |
| **Pass** | Response references null/priority/status (or JSON rules); `memory_id` present |

### T6 — Session + semantic memory

| | |
| --- | --- |
| **What** | Same `session_id` + `actor_id` keeps short-term context; memory resource is wired |
| **How** | Two turns on schema agent with the same session/actor |
| **Turn 1** | `Remember this project codeword: MEDALLION-ALPHA. Reply OK.` |
| **Turn 2** | `What project codeword did I just give you?` |
| **Pass** | Turn 2 recalls `MEDALLION-ALPHA` (STM). Response includes same `memory_id` as deploy state. |

---

## Manual console checks (optional)

1. **Supabase** → Table Editor → schemas `bronze` / `silver` / `gold` / `meta`
2. **AWS Console** → Bedrock → AgentCore → Runtimes → status **READY** for MCP + both agents
3. **AWS Console** → AgentCore → Gateways → target `medalliondb` status **READY**
4. **CloudWatch** → `/aws/bedrock-agentcore/runtimes/<runtime-id>-DEFAULT` for errors

---

## Pass / fail summary

| ID | Layer | Critical? |
| --- | --- | --- |
| T1 | Data | Yes |
| T2 | MCP | Yes |
| T3 | Gateway | Yes |
| T4 | Schema agent | Yes |
| T5 | Quality agent | Yes |
| T6 | Memory / session | Yes (STM); LTM semantic extraction may lag async |

If T1–T5 pass, the architecture is working. T6 confirms session wiring; semantic LTM facts can take time after several tool-using turns.
