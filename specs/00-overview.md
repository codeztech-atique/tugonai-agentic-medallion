# Spec 00 — Overview

## Goal

Build an **agentic medallion pipeline** (bronze → silver → gold) for messy facility support tickets (`data/raw_tickets.csv`, ~10k rows), where:

1. A working medallion data pipeline lands, cleans, and aggregates tickets in PostgreSQL.
2. AWS Bedrock **AgentCore** agents accelerate schema design and data-quality rule creation.
3. Agents never talk to the database directly — they use **AgentCore Gateway → MCP → Postgres**.

## Scoring map

| Part | Weight | Deliverable |
| --- | --- | --- |
| Medallion pipeline | 50% | Idempotent bronze/silver/gold with lineage, logging, documented cleaning rules |
| Agentic acceleration | 50% | Schema Inference Agent + Data Quality Agent via Gateway/MCP |

## Locked decisions

| Decision | Choice |
| --- | --- |
| Database | Neon PostgreSQL (primary); Docker Postgres for local `docker compose up` |
| Region | `ap-south-1` |
| Agent framework | Strands + BedrockAgentCoreApp |
| Agents | (a) Schema Inference & Evolution, (b) Data Quality |
| Gold models | Deterministic SQL: ticket volume cube, SLA performance, cost by assignee |
| Data access | Gateway → Medallion DB MCP only |

## Non-goals

- Semantic Classification agent and Gold Design agent (unless extended later)
- Full HITL UI / agent evaluation harness
- Production observability beyond `meta.pipeline_runs` + structured logs
- Mutating `data/raw_tickets.csv`

## Delivery phases

0. Specs (this folder)  
1. Database bootstrap SQL  
2. Medallion DB MCP server  
3. Deterministic pipeline  
4. Gateway setup + MCP target  
5. Schema + Quality agents  
6. Submission README + compose

## Success criteria

- `docker compose up` (or equivalent script) boots Postgres, applies schema, runs bronze→silver→gold.
- Agents can list/sample/profile tables and propose DDL/rules only through MCP tools.
- README covers architecture, agent assessment, 100× scale, and how to run.
