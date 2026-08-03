#!/usr/bin/env python3.11
"""
Local UI to invoke Schema / Quality agents on AgentCore (SSE streaming + traces).

  set -a && source .env && set +a
  /opt/homebrew/bin/python3.11 harness/ui/app.py
  # open http://127.0.0.1:8765
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
QUESTIONS_PATH = ROOT / "harness" / "questions.json"
STATE_PATH = ROOT / "src" / "gateway" / "setup" / "deploy_state.json"
STATIC_DIR = Path(__file__).resolve().parent / "static"

env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

app = FastAPI(title="TugonAI Agent Console", version="1.1.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def load_questions() -> dict:
    return json.loads(QUESTIONS_PATH.read_text())


def load_state() -> dict:
    if not STATE_PATH.exists():
        raise HTTPException(500, f"Missing deploy state: {STATE_PATH}")
    return json.loads(STATE_PATH.read_text())


def agent_runtime_id(state: dict, agent: str) -> str:
    key = {
        "schema": "schema_agent_runtime_id",
        "quality": "quality_agent_runtime_id",
    }.get(agent)
    if not key or key not in state:
        raise HTTPException(400, f"Unknown agent: {agent}")
    return state[key]


def runtime_arn(runtime_id: str) -> str:
    region = os.environ.get("AWS_REGION", "ap-south-1")
    account = "485947658225"
    return f"arn:aws:bedrock-agentcore:{region}:{account}:runtime/{runtime_id}"


def _parse_sse_chunk(raw: str) -> Any | None:
    raw = raw.strip()
    if not raw:
        return None
    if raw.startswith("data:"):
        raw = raw[5:].strip()
    if raw in ("[DONE]", ""):
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # AgentCore may wrap as {"event": "..."} or plain text
        return {"type": "text", "content": raw}


def iter_agent_stream(
    runtime_id: str,
    prompt: str,
    session_id: str,
    actor_id: str,
) -> Iterator[dict[str, Any]]:
    import boto3

    region = os.environ.get("AWS_REGION", "ap-south-1")
    client = boto3.client("bedrock-agentcore", region_name=region)
    payload = json.dumps(
        {"prompt": prompt, "session_id": session_id, "actor_id": actor_id}
    ).encode()

    kwargs: dict[str, Any] = {
        "agentRuntimeArn": runtime_arn(runtime_id),
        "qualifier": "DEFAULT",
        "payload": payload,
        "runtimeSessionId": session_id[:100] if len(session_id) >= 33 else f"{session_id}-{uuid.uuid4().hex}"[:64],
    }
    # runtimeSessionId must be 33+ chars for AgentCore
    if len(kwargs["runtimeSessionId"]) < 33:
        kwargs["runtimeSessionId"] = (kwargs["runtimeSessionId"] + uuid.uuid4().hex)[:64]

    resp = client.invoke_agent_runtime(**kwargs)
    content_type = (resp.get("contentType") or "").lower()
    body = resp.get("response")

    if body is None:
        yield {"type": "error", "content": "Empty AgentCore response"}
        return

    if "text/event-stream" in content_type or "event-stream" in content_type:
        buffer = ""
        for chunk in body.iter_lines(chunk_size=1):
            if not chunk:
                continue
            line = chunk.decode("utf-8", errors="replace") if isinstance(chunk, bytes) else str(chunk)
            if not line.startswith("data:"):
                # accumulate multi-line SSE
                buffer += line + "\n"
                continue
            data = _parse_sse_chunk(line)
            if data is not None:
                if isinstance(data, dict):
                    yield data
                else:
                    yield {"type": "text", "content": str(data)}
        return

    # Non-streaming JSON fallback (older agents)
    raw = body.read() if hasattr(body, "read") else body
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        yield {"type": "error", "content": raw[:800]}
        return
    if data.get("error"):
        yield {"type": "error", "content": data["error"], "session_id": session_id}
    else:
        yield {
            "type": "done",
            "response": data.get("response") or "",
            "session_id": data.get("session_id") or session_id,
            "actor_id": data.get("actor_id") or actor_id,
            "memory_id": data.get("memory_id"),
        }


class ChatRequest(BaseModel):
    agent: str = Field(description="schema | quality")
    prompt: str
    session_id: str | None = None
    actor_id: str | None = None


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health():
    state_ok = STATE_PATH.exists()
    db = bool(os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_URL_POOLER"))
    return {
        "ok": state_ok and db,
        "deploy_state": state_ok,
        "database_url_set": db,
        "connected": state_ok and db,
    }


@app.get("/api/meta")
def meta():
    state = load_state()
    return {
        "agents": {
            "schema": {
                "label": "Schema Inference",
                "runtime_id": state.get("schema_agent_runtime_id"),
                "blurb": "Bronze → silver DDL via Gateway → MCP",
            },
            "quality": {
                "label": "Data Quality",
                "runtime_id": state.get("quality_agent_runtime_id"),
                "blurb": "Profile bronze and propose cleaning rules with why",
            },
        },
        "gateway_id": state.get("gateway", {}).get("gateway_id"),
        "memory_id": state.get("memory_id"),
        "mcp_runtime_id": state.get("mcp_runtime_id"),
    }


@app.get("/api/questions")
def questions():
    data = load_questions()
    return {
        "schema": data.get("schema_agent", []),
        "quality": data.get("quality_agent", []),
        "memory": data.get("memory_session", []),
    }


@app.post("/api/chat/stream")
def chat_stream(body: ChatRequest):
    prompt = (body.prompt or "").strip()
    if not prompt:
        raise HTTPException(400, "prompt is required")
    agent = body.agent.strip().lower()
    if agent not in {"schema", "quality"}:
        raise HTTPException(400, "agent must be schema or quality")

    state = load_state()
    rid = agent_runtime_id(state, agent)
    session_id = body.session_id or f"ui-{uuid.uuid4().hex}"
    if len(session_id) < 33:
        session_id = f"{session_id}-{uuid.uuid4().hex}"
    actor_id = body.actor_id or "ui-user"
    started = time.time()

    def gen():
        yield f"data: {json.dumps({'type': 'status', 'content': 'connected', 'agent': agent, 'session_id': session_id})}\n\n"
        final_response = ""
        memory_id = state.get("memory_id")
        try:
            for ev in iter_agent_stream(rid, prompt, session_id, actor_id):
                if not isinstance(ev, dict):
                    continue
                # unwrap nested event payloads
                if "event" in ev and len(ev) == 1:
                    inner = _parse_sse_chunk(str(ev["event"]))
                    if isinstance(inner, dict):
                        ev = inner
                if ev.get("type") == "result":
                    final_response = ev.get("content") or final_response
                if ev.get("type") == "done":
                    final_response = ev.get("response") or final_response
                    memory_id = ev.get("memory_id") or memory_id
                if ev.get("type") == "meta":
                    memory_id = ev.get("memory_id") or memory_id
                if ev.get("memory_id"):
                    memory_id = ev["memory_id"]
                yield f"data: {json.dumps(ev, default=str)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
        elapsed_ms = int((time.time() - started) * 1000)
        yield f"data: {json.dumps({'type': 'done', 'response': final_response, 'session_id': session_id, 'actor_id': actor_id, 'memory_id': memory_id, 'elapsed_ms': elapsed_ms, 'agent': agent})}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def main():
    import uvicorn

    host = os.environ.get("UI_HOST", "127.0.0.1")
    port = int(os.environ.get("UI_PORT", "8765"))
    print(f"TugonAI Agent Console → http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
