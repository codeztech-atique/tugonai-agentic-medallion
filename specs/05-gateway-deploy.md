# Spec 05 — Gateway & Deploy Order

## Architecture reminder

```
Agent (Strands) → AgentCore Gateway (OAuth2 + semantic search) → Medallion DB MCP → Neon/Postgres
```

## Prerequisites

- AWS credentials with AgentCore permissions in `ap-south-1`
- `DATABASE_URL` set for MCP runtime
- `pip install bedrock-agentcore-starter-toolkit boto3 strands-agents mcp`

## Ordered steps

### 1. Bootstrap database

```bash
psql "$DATABASE_URL" -f sql/001_bootstrap.sql
psql "$DATABASE_URL" -f sql/002_silver_gold.sql
```

### 2. Deploy MCP tool server

```bash
cd src/tools/mcp/medallion_db
# set DATABASE_URL in runtime env / .env
agentcore deploy --region ap-south-1
# Note Runtime endpoint from console
```

### 3. Create Gateway + Cognito

```bash
cd src/gateway/setup
python setup_gateway.py
# writes gateway_config.json
```

### 4. Attach MCP target

```bash
cd src/gateway/targets/mcp
python attach_mcp_target.py --name medallion-db --endpoint <RUNTIME_ENDPOINT>/mcp
```

### 5. Test Gateway tools

```bash
cd src/gateway/test
python test_gateway_agent.py
# Ask: "List schemas and tables, then profile bronze.raw_tickets"
```

### 6. Deploy agents

```bash
cd src/agents/http/strands/schema_agent && agentcore deploy --region ap-south-1
cd src/agents/http/strands/quality_agent && agentcore deploy --region ap-south-1
```

### 7. Local pipeline (no AgentCore required)

```bash
docker compose up --build
# or
python -m src.pipeline.run_all
```

## Config artifacts (gitignored)

- `src/gateway/setup/gateway_config.json`
- `src/gateway/targets/mcp/target_*.json`
- `.env`
