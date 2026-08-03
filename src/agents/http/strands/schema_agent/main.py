"""Medallion Schema Agent — Gateway + STM/LTM + streaming traces."""

from __future__ import annotations

import os
from typing import Any, AsyncIterator

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from botocore.exceptions import ClientError
from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient

try:
    from gateway_client import GatewaySession, list_gateway_tools
except ImportError:
    from shared.gateway_client import GatewaySession, list_gateway_tools  # type: ignore

try:
    from stream_sanitize import dedupe_tool_events, sanitize_event
except ImportError:
    from stream_sanitize import dedupe_tool_events, sanitize_event  # type: ignore

try:
    from bedrock_agentcore.memory.integrations.strands.config import (
        AgentCoreMemoryConfig,
        RetrievalConfig,
    )
    from bedrock_agentcore.memory.integrations.strands.session_manager import (
        AgentCoreMemorySessionManager,
    )

    _MEMORY_AVAILABLE = True
except ImportError:
    _MEMORY_AVAILABLE = False

app = BedrockAgentCoreApp()
_agents: dict = {}
_mcp = None

REGION = os.environ.get("AWS_REGION", "ap-south-1")
MODEL_ID = os.environ.get(
    "MODEL_ID", "apac.anthropic.claude-3-haiku-20240307-v1:0"
)
MEMORY_ID = os.environ.get("BEDROCK_AGENTCORE_MEMORY_ID") or os.environ.get(
    "MEMORY_ID"
)

SYSTEM_PROMPT = """You are a Schema Inference & Evolution agent for a medallion lakehouse of facility support tickets.

Data access rules:
- You MUST use Gateway MCP tools only (list_schemas_tables, describe_table, sample_rows, profile_table, run_sql_readonly, execute_sql).
- Never invent columns that are not evidenced in bronze samples or describe_table.

Your job:
1. Inspect bronze.raw_tickets (sample + profile).
2. Propose a typed silver schema (prefer silver.tickets or silver.tickets_proposed for staging).
3. Generate CREATE TABLE IF NOT EXISTS DDL and INSERT…SELECT transform SQL.
4. Explain type choices and casting strategy for messy dates/priorities/status/cost.

Guardrails:
- Prefer additive / staging writes. Mark trust=review_required before overwriting production silver/gold.
- No DROP DATABASE / DROP SCHEMA.
- Final answer MUST include a JSON block:
{
  "ddl": ["..."],
  "transform_sql": "...",
  "rationale": ["..."],
  "trust": "review_required|safe_to_apply"
}

Use short-term session context and long-term semantic memory when available.
"""


def _memory_session_manager(session_id: str, actor_id: str):
    if not (_MEMORY_AVAILABLE and MEMORY_ID):
        return None
    retrieval_config = {
        f"/users/{actor_id}/facts": RetrievalConfig(top_k=5, relevance_score=0.4),
    }
    return AgentCoreMemorySessionManager(
        AgentCoreMemoryConfig(
            memory_id=MEMORY_ID,
            session_id=session_id,
            actor_id=actor_id,
            retrieval_config=retrieval_config,
        ),
        REGION,
    )


def _get_mcp():
    global _mcp
    if _mcp is None:
        gw = GatewaySession()
        _mcp = MCPClient(gw.transport_factory())
        _mcp.__enter__()
    return _mcp


def _get_or_create_agent(session_id: str, actor_id: str) -> Agent:
    key = f"{session_id}:{actor_id}"
    if key in _agents:
        return _agents[key]

    mcp = _get_mcp()
    tools = list_gateway_tools(mcp)
    print(f"[schema_agent] tools={ [t.tool_name for t in tools] } memory={MEMORY_ID}")
    model = BedrockModel(model_id=MODEL_ID, region_name=REGION, streaming=True)
    kwargs = {
        "model": model,
        "tools": tools,
        "system_prompt": SYSTEM_PROMPT,
    }
    sm = _memory_session_manager(session_id, actor_id)
    if sm is not None:
        kwargs["session_manager"] = sm
    agent = Agent(**kwargs)
    _agents[key] = agent
    return agent


def _ids(payload: Any, context: Any) -> tuple[str, str, str]:
    prompt = payload.get("prompt") if isinstance(payload, dict) else str(payload)
    session_id = getattr(context, "session_id", None) or (
        payload.get("session_id") if isinstance(payload, dict) else None
    ) or "default-session"
    actor_id = getattr(context, "user_id", None) or (
        payload.get("actor_id") if isinstance(payload, dict) else None
    ) or "default-user"
    return prompt, session_id, actor_id


@app.entrypoint
async def invoke(payload, context) -> AsyncIterator[dict]:
    prompt, session_id, actor_id = _ids(payload, context)
    yield {
        "type": "meta",
        "session_id": session_id,
        "actor_id": actor_id,
        "memory_id": MEMORY_ID,
        "agent": "schema",
    }
    try:
        agent = _get_or_create_agent(session_id, actor_id)
        final_text = ""
        async for event in agent.stream_async(prompt):
            for ui_ev in dedupe_tool_events(sanitize_event(event)):
                if ui_ev.get("type") == "result":
                    final_text = ui_ev.get("content") or final_text
                yield ui_ev
        yield {
            "type": "done",
            "response": final_text,
            "session_id": session_id,
            "actor_id": actor_id,
            "memory_id": MEMORY_ID,
        }
    except (ClientError, Exception) as e:
        yield {"type": "error", "content": str(e), "session_id": session_id}


if __name__ == "__main__":
    app.run()
