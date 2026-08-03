# TugonAI Agentic Medallion Pipeline

Bronze → silver → gold for messy facility support tickets, with **AWS Bedrock AgentCore** agents that only touch data through **Gateway → MCP → Postgres (Supabase)**.

Assignment brief: [docs/assignment.md](docs/assignment.md) · Specs: [specs/](specs/) · E2E: [specs/06-e2e-test.md](specs/06-e2e-test.md) · Question harness: [specs/07-question-harness.md](specs/07-question-harness.md)

---

## What we built

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        LOCAL (laptop)                                    │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │  Agent Console  ·  http://127.0.0.1:8765                           │  │
│  │  curated prompts · SSE streaming · tool traces · Markdown          │  │
│  └──────────────────────────────┬─────────────────────────────────────┘  │
└─────────────────────────────────┼────────────────────────────────────────┘
                                  │  SigV4 invoke (SSE)
                                  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                     AWS Bedrock AgentCore  (ap-south-1)                  │
│                                                                          │
│   ┌─────────────────────┐         ┌─────────────────────┐                │
│   │  Schema Agent       │         │  Quality Agent      │                │
│   │  Strands + Haiku    │         │  Strands + Haiku    │                │
│   │  STM / LTM memory   │         │  STM / LTM memory   │                │
│   └──────────┬──────────┘         └──────────┬──────────┘                │
│              │                               │                           │
│              └───────────────┬───────────────┘                           │
│                              │  OAuth JWT + MCP tools                    │
│                              ▼                                           │
│              ┌───────────────────────────────┐                           │
│              │  AgentCore Gateway            │                           │
│              │  Cognito OAuth                │                           │
│              │  semantic tool search         │                           │
│              └───────────────┬───────────────┘                           │
│                              │  IAM invoke                               │
│                              ▼                                           │
│              ┌───────────────────────────────┐                           │
│              │  Medallion DB MCP             │                           │
│              │  list / sample / profile / SQL│                           │
│              └───────────────┬───────────────┘                           │
└──────────────────────────────┼───────────────────────────────────────────┘
                               │  Postgres (IPv4 Session pooler)
                               ▼
               ┌───────────────────────────────┐
               │  Supabase Postgres            │
               │  bronze · silver · gold · meta│
               └───────────────────────────────┘
```

**Rule:** agents never open a DB connection. Path is always **Agent → Gateway → MCP → Supabase**.

### Medallion data flow

```
  data/raw_tickets.csv          (immutable, ~10k rows)
            │
            │  python -m src.pipeline.run_all
            ▼
  ┌─────────────────────┐
  │  BRONZE             │  schema-on-read TEXT
  │  bronze.raw_tickets │  + source_file, ingested_at, row_hash
  └──────────┬──────────┘
             │  clean · cast · dedupe
             ▼
  ┌─────────────────────┐
  │  SILVER             │
  │  silver.tickets     │
  └──────────┬──────────┘
             │
     ┌───────┼───────────────────┐
     ▼       ▼                   ▼
 ┌────────┐ ┌──────────┐  ┌─────────────┐
 │ GOLD   │ │ GOLD     │  │ GOLD        │
 │ volume │ │ sla_     │  │ cost_by_    │
 │ by     │ │ performance│ │ assignee   │
 │ bldg×  │ │          │  │             │
 │ cat    │ │          │  │             │
 └────────┘ └──────────┘  └─────────────┘
             │
             ▼
        meta.pipeline_runs
```

### Live agent turn (streaming)

```
  You (Console)          Agent runtime           Gateway + MCP           Supabase
  ─────────────          ─────────────           ─────────────           ────────
       │                      │                       │                     │
       │  prompt + session    │                       │                     │
       │─────────────────────►│                       │                     │
       │                      │  discover / call tool │                     │
       │                      │──────────────────────►│                     │
       │                      │                       │  SQL (pooler)       │
       │                      │                       │────────────────────►│
       │                      │                       │◄────────────────────│
       │                      │◄──────────────────────│  tool result        │
       │  SSE: text / tools   │                       │                     │
       │◄─────────────────────│                       │                     │
       │  final Markdown      │                       │                     │
       │◄─────────────────────│                       │                     │
```

---

## Architecture layers

| Layer | Role |
| --- | --- |
| **Bronze** | Land messy CSV as TEXT + `source_file`, `ingested_at`, `row_hash` (idempotent) |
| **Silver** | Typed/cleaned/deduped `silver.tickets` ([specs/02-medallion.md](specs/02-medallion.md)) |
| **Gold** | Volume by building×category, SLA performance, cost by assignee |
| **MCP** | `src/tools/mcp/medallion_db` — only data plane for agents |
| **Gateway** | Cognito OAuth + semantic search over MCP tools |
| **Agents** | Schema Inference + Data Quality (Strands on AgentCore, STM/LTM) |
| **Console** | Local UI: curated prompts, SSE streaming, tool traces, Markdown |

---

## Prerequisites

- Python 3.11+, AWS credentials for account/region (`ap-south-1`)
- Supabase Postgres project
- **Important for AgentCore:** direct `db.*.supabase.co` is often **IPv6-only**. MCP must use the **Session pooler** URI from Dashboard → Connect (host may be `aws-0/1/2-<region>.pooler.supabase.com` — region can differ from your AWS region).

```bash
cp .env.example .env
# Fill SUPABASE_* + DATABASE_URL (local/pipeline)
# Set DATABASE_URL_POOLER for AgentCore MCP (IPv4)
```

---

## How to run

### 1) Load medallion tables (local → Supabase)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
set -a && source .env && set +a
python -m src.pipeline.run_all
```

**Do not modify** `data/raw_tickets.csv`.

### 2) Deploy AgentCore stack (one-shot)

Deploys MCP → Gateway (semantic search) → Schema/Quality agents with STM + LTM (semantic memory). Uses S3 remote CodeBuild (no local Docker).

```bash
set -a && source .env && set +a
/opt/homebrew/bin/python3.11 scripts/deploy_agentcore.py
```

State (gitignored secrets): `src/gateway/setup/deploy_state.json`.

Default model (cost-safe): `apac.anthropic.claude-3-haiku-20240307-v1:0` via `MODEL_ID`.

### 3) Agent Console (UI)

```bash
set -a && source .env && set +a
pip install fastapi uvicorn boto3
/opt/homebrew/bin/python3.11 harness/ui/app.py
# → http://127.0.0.1:8765
```

Features: pick Schema/Quality in the left rail, curated questions, live SSE tokens, Thinking & tools panel, Markdown answers.

#### Hosting on S3 + CloudFront (static front door)

**Upload this folder to S3 (website / CloudFront origin):**

```text
harness/ui/static/
├── index.html
├── app.js
├── styles.css
└── favicon.svg
```

Example sync:

```bash
aws s3 sync harness/ui/static/ s3://YOUR_BUCKET/ --delete
# then point a CloudFront distribution at that bucket (default root object: index.html)
```

**Do not upload only the static files and expect chat to work.**  
`app.js` calls `/api/health`, `/api/questions`, `/api/meta`, and `/api/chat/stream`. Those live in **`harness/ui/app.py`** (FastAPI + SigV4 → AgentCore). Pure S3 has no Python runtime.

Recommended serverless shape:

```text
Browser
   │
   ▼
CloudFront
   ├── /*        → S3   (harness/ui/static/)
   └── /api/*    → API  (Lambda Function URL / API Gateway + Lambda,
                         or App Runner / ECS running harness/ui/app.py)
```

Until `/api/*` is wired to a backend with AWS credentials, keep using local `harness/ui/app.py`.

### 4) CLI harness / E2E

```bash
/opt/homebrew/bin/python3.11 harness/run_harness.py list
/opt/homebrew/bin/python3.11 harness/run_harness.py ask S1
/opt/homebrew/bin/python3.11 scripts/test_e2e.py
```

Suggested demo order: **S1 → S2 → S3**, then **Q1 → Q2** ([specs/07-question-harness.md](specs/07-question-harness.md)).

---

## Agent assessment

### Schema Inference

| | |
| --- | --- |
| **Does** | Samples/profiles `bronze.raw_tickets`, proposes silver DDL + transform SQL via MCP |
| **Sample input** | Propose a typed silver schema for bronze.raw_tickets; return DDL + INSERT SQL as JSON |
| **Sample output** | JSON `ddl`, `transform_sql`, `rationale`, `trust` ([docs/sample_agent_io.md](docs/sample_agent_io.md)) |
| **Honest take** | Saves ~30–45 min on first-pass typing/casts. Still **review_required** before apply |

### Data Quality

| | |
| --- | --- |
| **Does** | Profiles null rates/cardinality; proposes cleaning rules with **why** + SQL/Python |
| **Sample input** | Profile bronze.raw_tickets and propose high-severity cleaning rules |
| **Sample output** | JSON `profile_summary` + `rules[]` with severity |
| **Honest take** | Strong as a **rule recommender**; final cleaner in `src/pipeline/cleaning.py` stays deterministic |

---

## Scale notes (1M+ rows, daily incremental)

- Incremental silver merge on `ticket_id` + watermark (not full `TRUNCATE`)
- Agents on **samples + stats**, not full scans; heavy transforms in SQL/dbt/Spark
- MCP: statement timeouts, read replicas for profile; writes only for approved DDL
- Cache profiles / schema fingerprints; re-prompt on drift only
- Gold as incremental rollups / MVs

---

## Gold model justification

1. **Volume by building × category × status** — staffing and vendor load  
2. **SLA performance** — breach rate and latency by priority/status  
3. **Cost by assignee** — in-house vs vendor spend  

---

## Repo layout

```
specs/                      # Spec-driven design (00–07)
sql/                        # Bootstrap + silver/gold DDL
data/raw_tickets.csv        # Immutable source
docs/                       # Assignment + sample I/O
harness/
  questions.json            # Curated S*/Q* prompts
  run_harness.py            # CLI list / ask / interactive / batch
  ui/                       # Agent Console (FastAPI + SSE)
src/pipeline/               # Deterministic medallion runner
src/tools/mcp/medallion_db/ # MCP server (AgentCore runtime)
src/gateway/                # Gateway setup + MCP target
src/agents/.../strands/     # Schema + Quality agents (streaming)
scripts/deploy_agentcore.py # One-shot cloud deploy
scripts/test_e2e.py         # Connectivity / smoke tests
```
