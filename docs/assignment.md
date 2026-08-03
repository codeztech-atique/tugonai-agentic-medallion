# TugonAI Take-Home: Agentic Medallion Pipeline

## Scenario

You receive a messy, real-world dataset (`data/raw_tickets.csv` — ~10k rows of operational support tickets).

**Your task:** design and implement a medallion architecture (bronze → silver → gold) where AI agents assist in making the pipeline construction smarter and more efficient.

> **Important:** Do not modify `data/raw_tickets.csv`. Your bronze layer should ingest it as-is.

---

## Part 1 — Medallion Pipeline (50%)

Build a working **bronze → silver → gold** pipeline.

| Layer | Expectation |
| --- | --- |
| **Bronze** | Raw ingestion, schema-on-read, no data loss. Include lineage metadata: source file, `ingested_at` timestamp, row hash for dedup tracking. |
| **Silver** | Cleansed, deduplicated, typed, validated. Document your cleaning rules and why you chose them. |
| **Gold** | Business-ready aggregations or models. Pick 2–3 that would be useful given the dataset and justify your choices in the README. |

You can use PostgreSQL to keep it simple, or any other data storage solution. Show clear separation between layers — schemas, naming conventions, or whatever approach you prefer. Be intentional and explain your choice.

### Pipeline requirements

- Idempotent and re-runnable
- Clear logging of what happened at each stage
- Handle the provided data’s messiness without manual intervention

---

## Part 2 — Agentic Acceleration (50%)

Build one or more AI agents that make the bronze → silver → gold process faster, smarter, or more adaptive.

**Pick at least two** of the following:

### a) Schema Inference & Evolution Agent

- Given a raw bronze table, the agent inspects sample rows, proposes a typed silver schema, and generates the DDL + transformation SQL
- **Bonus:** detects schema drift when new data arrives and proposes migrations

### b) Data Quality Agent

- Profiles the bronze layer — distributions, null rates, outliers, cardinality
- Proposes cleaning/validation rules in natural language, then generates the SQL or Python to implement them
- Should explain **why** a rule matters, not just flag anomalies

### c) Semantic Classification Agent

- Takes free-text or ambiguous columns and enriches them — categorization, entity extraction, normalization
- Output lands in silver as new structured, queryable columns
- Show how you’d handle this at scale (batching, caching, cost awareness)

### d) Gold Layer Design Agent

- Given the silver schema + a plain-English description of the business domain, proposes gold layer aggregations and models
- Generates the SQL for the materialized views or tables
- You should be able to explain when you’d trust the agent’s output vs. override it

---

## Evaluation Criteria

| Area | What we’re looking for |
| --- | --- |
| **Medallion design** | Clean layer separation, lineage tracking, idempotency |
| **Agent usefulness** | Does the agent actually save time vs. doing it manually? We value honesty over impressiveness. |
| **Prompt engineering** | Quality of instructions to the LLM — context provided, output format constraints, guardrails |
| **Cost and scale thinking** | How would this work on 10M rows? What would you batch, cache, or skip? |
| **Tradeoff awareness** | Where agents added real value, where they didn’t, and what changes at production scale |
| **Code quality** | Clean, readable, minimal. No over-engineering. |

---

## Required in Your README

Your project README must include:

1. **Architecture diagram** — a simple box diagram is fine
2. **Agent assessment** — for each agent you built:
   - what it does
   - a sample input/output
   - your honest take: “this saved me X” or “this was more trouble than it was worth because Y”
3. **What changes at 100× scale** — brief section on what you’d redesign if this were 1M+ rows with daily incremental loads
4. **How to run** — single command to get everything up (e.g. `docker-compose up`, then run a script)

---

## Good to Have

These are **not required**, but thoughtful touches are welcome:

| Idea | Description |
| --- | --- |
| **Data lineage** | End-to-end traceability from source through bronze, silver, and gold (who/what/when for each transformation) |
| **Metadata auto-tagging at landing** | Automatic classification or tagging of datasets and columns as they land in bronze (e.g. sensitivity, domain, PII hints) |
| **Cross-source reconciliation & dimensional model recommendation** | Checks across inputs for consistency, plus suggested star/snowflake-style models or conformed dimensions aligned to the business |
| **Agent evaluation harness** | A small, repeatable test set and scoring rubric to compare agent outputs (accuracy, format compliance, latency, cost) before promoting prompt/tool changes |
| **Human-in-the-loop approval gates** | Explicit checkpoints where high-risk agent suggestions (schema changes, destructive transforms, major recategorizations) require review before execution |
| **Incremental + backfill strategy** | Clear handling for late-arriving records, replay windows, and deterministic reprocessing without double counting |
| **Observability and SLA thinking** | Pipeline + agent metrics (row counts, null deltas, failure rates, token/cost usage) with basic alerting thresholds |

---

## Tech Flexibility

| Concern | Guidance |
| --- | --- |
| Language | Any (Python preferred) |
| AI provider | OpenAI, Anthropic, local models — your call |
| Orchestration | LangGraph, CrewAI, raw tool-use loop, or none |

**Dataset path:** `data/raw_tickets.csv`
