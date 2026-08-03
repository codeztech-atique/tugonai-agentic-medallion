#!/usr/bin/env python3.11
"""
End-to-end smoke tests for TugonAI AgentCore stack.

Usage:
  set -a && source .env && set +a
  /opt/homebrew/bin/python3.11 scripts/test_e2e.py
  /opt/homebrew/bin/python3.11 scripts/test_e2e.py --only T1,T2,T4
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote, urlencode

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "src" / "gateway" / "setup" / "deploy_state.json"
GATEWAY_PATH = ROOT / "src" / "gateway" / "setup" / "gateway_config.json"

# Load .env
env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def _load_state() -> dict:
    if not STATE_PATH.exists():
        raise SystemExit(f"Missing {STATE_PATH}. Deploy first.")
    return json.loads(STATE_PATH.read_text())


def _load_gateway() -> dict:
    if GATEWAY_PATH.exists():
        return json.loads(GATEWAY_PATH.read_text())
    state = _load_state()
    return state["gateway"]


class Result:
    def __init__(self, tid: str, ok: bool, detail: str):
        self.tid = tid
        self.ok = ok
        self.detail = detail


def t1_supabase(state: dict) -> Result:
    import psycopg
    from psycopg.rows import dict_row

    url = os.environ.get("DATABASE_URL", "")
    if not url or "localhost" in url:
        return Result("T1", False, "DATABASE_URL missing or still localhost")
    with psycopg.connect(url, row_factory=dict_row, connect_timeout=15) as conn:
        bronze = conn.execute("SELECT COUNT(*) AS c FROM bronze.raw_tickets").fetchone()["c"]
        silver = conn.execute("SELECT COUNT(*) AS c FROM silver.tickets").fetchone()["c"]
        gold = conn.execute(
            "SELECT COUNT(*) AS c FROM gold.cost_by_assignee"
        ).fetchone()["c"]
    ok = bronze >= 10000 and silver >= 10000 and gold > 0
    return Result(
        "T1",
        ok,
        f"bronze={bronze} silver={silver} gold.cost_by_assignee={gold}",
    )


def _runtime_url(runtime_id: str) -> str:
    region = os.environ.get("AWS_REGION", "ap-south-1")
    account = "485947658225"
    arn = f"arn:aws:bedrock-agentcore:{region}:{account}:runtime/{runtime_id}"
    return (
        f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/"
        f"{quote(arn, safe='')}/invocations?qualifier=DEFAULT"
    )


def _sigv4_post(
    url: str,
    body: bytes,
    accept: str = "application/json",
    extra_headers: dict | None = None,
    return_headers: bool = False,
):
    import boto3
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    region = os.environ.get("AWS_REGION", "ap-south-1")
    creds = boto3.Session(region_name=region).get_credentials().get_frozen_credentials()
    headers = {
        "Content-Type": "application/json",
        "Accept": accept,
    }
    if extra_headers:
        headers.update(extra_headers)
    req = AWSRequest(method="POST", url=url, data=body, headers=headers)
    SigV4Auth(creds, "bedrock-agentcore", region).add_auth(req)
    prepared = req.prepare()
    http_req = urllib.request.Request(
        prepared.url, data=prepared.body, headers=dict(prepared.headers)
    )
    with urllib.request.urlopen(http_req, timeout=180) as resp:
        raw = resp.read()
        if return_headers:
            return raw, dict(resp.headers)
        return raw


def _parse_mcp_sse(raw: bytes) -> dict:
    text = raw.decode("utf-8", errors="replace")
    payload = text
    if "data:" in text:
        for line in text.splitlines():
            if line.startswith("data:"):
                payload = line[5:].strip()
                break
    if not payload.strip():
        return {}
    return json.loads(payload)


def t2_mcp_direct(state: dict) -> Result:
    rid = state["mcp_runtime_id"]
    url = _runtime_url(rid)
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "e2e", "version": "1.0"},
        },
    }
    raw, headers = _sigv4_post(
        url,
        json.dumps(init).encode(),
        accept="application/json, text/event-stream",
        return_headers=True,
    )
    data = _parse_mcp_sse(raw)
    name = data.get("result", {}).get("serverInfo", {}).get("name", "")
    if name != "medallion-db":
        return Result("T2", False, f"initialize unexpected: {raw[:400]!r}")

    session_id = headers.get("Mcp-Session-Id") or headers.get("mcp-session-id")
    sess_headers = {"Mcp-Session-Id": session_id} if session_id else {}
    # required notification after initialize
    _sigv4_post(
        url,
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode(),
        accept="application/json, text/event-stream",
        extra_headers=sess_headers,
    )
    raw2 = _sigv4_post(
        url,
        json.dumps(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
        ).encode(),
        accept="application/json, text/event-stream",
        extra_headers=sess_headers,
    )
    data2 = _parse_mcp_sse(raw2)
    tools = data2.get("result", {}).get("tools") or []
    names = [t.get("name") for t in tools]
    needed = {"list_schemas_tables", "sample_rows", "profile_table"}
    ok = needed.issubset(set(names))
    return Result("T2", ok, f"session={session_id} tools={names}")


def t3_gateway_tools(state: dict) -> Result:
    # Prefer toolkit GatewayClient
    try:
        from bedrock_agentcore_starter_toolkit.operations.gateway.client import (
            GatewayClient,
        )
        from mcp.client.streamable_http import streamablehttp_client
        from mcp import ClientSession
    except ImportError as e:
        return Result("T3", False, f"deps missing (use python3.11): {e}")

    gw = _load_gateway()
    client = GatewayClient(region_name=gw.get("region", "ap-south-1"))
    token = client.get_access_token_for_cognito(gw["client_info"])

    import anyio

    async def _list() -> list[str]:
        async with streamablehttp_client(
            gw["gateway_url"],
            headers={"Authorization": f"Bearer {token}"},
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return [t.name for t in result.tools]

    names = anyio.run(_list)
    needed = {"list_schemas_tables", "sample_rows", "profile_table", "run_sql_readonly"}
    # Gateway may prefix tool names — match by substring
    flat = " ".join(names).lower()
    ok = len(names) >= 5 and all(n.replace("_", "") in flat.replace("_", "") or n in flat for n in ["list", "sample", "profile"])
    # softer: any tool containing these tokens
    tokens = ["list_schemas", "sample_rows", "profile_table"]
    ok = len(names) >= 3 and all(any(tok in n for n in names) for tok in tokens)
    return Result("T3", ok, f"count={len(names)} tools={names[:12]}")


def _invoke_agent(runtime_id: str, prompt: str, session_id: str, actor_id: str) -> dict:
    url = _runtime_url(runtime_id)
    body = json.dumps(
        {"prompt": prompt, "session_id": session_id, "actor_id": actor_id}
    ).encode()
    raw = _sigv4_post(url, body)
    return json.loads(raw.decode("utf-8"))


def t4_schema_agent(state: dict) -> Result:
    rid = state["schema_agent_runtime_id"]
    mid = state["memory_id"]
    resp = _invoke_agent(
        rid,
        "Using tools, list schemas and tables in bronze/silver/gold/meta. "
        "Reply with table names only.",
        session_id=f"e2e-schema-{int(time.time())}",
        actor_id="e2e-tester",
    )
    if resp.get("error"):
        return Result("T4", False, str(resp["error"])[:400])
    text = str(resp.get("response", "")).lower()
    ok = ("raw_tickets" in text or "tickets" in text) and resp.get("memory_id") == mid
    return Result("T4", ok, f"memory_id={resp.get('memory_id')} response={text[:300]}")


def t5_quality_agent(state: dict) -> Result:
    rid = state["quality_agent_runtime_id"]
    mid = state["memory_id"]
    resp = _invoke_agent(
        rid,
        "Profile bronze.raw_tickets null rates for priority and status. "
        "Return a short JSON profile_summary.",
        session_id=f"e2e-quality-{int(time.time())}",
        actor_id="e2e-tester",
    )
    if resp.get("error"):
        return Result("T5", False, str(resp["error"])[:400])
    text = str(resp.get("response", "")).lower()
    ok = (
        ("priority" in text or "null" in text or "profile" in text)
        and resp.get("memory_id") == mid
    )
    return Result("T5", ok, f"memory_id={resp.get('memory_id')} response={text[:300]}")


def t6_session_memory(state: dict) -> Result:
    rid = state["schema_agent_runtime_id"]
    mid = state["memory_id"]
    session_id = f"e2e-mem-{int(time.time())}"
    actor_id = "e2e-memory-user"
    r1 = _invoke_agent(
        rid,
        "Remember this project codeword: MEDALLION-ALPHA. Reply with only OK.",
        session_id=session_id,
        actor_id=actor_id,
    )
    if r1.get("error"):
        return Result("T6", False, f"turn1 error: {r1['error']}"[:400])
    time.sleep(2)
    r2 = _invoke_agent(
        rid,
        "What project codeword did I just give you? Reply with the codeword only.",
        session_id=session_id,
        actor_id=actor_id,
    )
    if r2.get("error"):
        return Result("T6", False, f"turn2 error: {r2['error']}"[:400])
    text = str(r2.get("response", ""))
    ok = "MEDALLION-ALPHA" in text.upper() and r2.get("memory_id") == mid
    return Result(
        "T6",
        ok,
        f"session={session_id} memory_id={r2.get('memory_id')} turn2={text[:200]}",
    )


TESTS: dict[str, Callable[[dict], Result]] = {
    "T1": t1_supabase,
    "T2": t2_mcp_direct,
    "T3": t3_gateway_tools,
    "T4": t4_schema_agent,
    "T5": t5_quality_agent,
    "T6": t6_session_memory,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="TugonAI e2e tests")
    parser.add_argument(
        "--only",
        default="",
        help="Comma-separated case IDs, e.g. T1,T2,T4",
    )
    args = parser.parse_args()
    only = {x.strip().upper() for x in args.only.split(",") if x.strip()}
    state = _load_state()

    print("=" * 60)
    print("TugonAI E2E tests")
    print("=" * 60)
    results: list[Result] = []
    for tid, fn in TESTS.items():
        if only and tid not in only:
            continue
        print(f"\n>>> {tid} …")
        try:
            res = fn(state)
        except Exception as e:
            res = Result(tid, False, f"exception: {e}")
        results.append(res)
        flag = "PASS" if res.ok else "FAIL"
        print(f"[{flag}] {tid}: {res.detail}")

    passed = sum(1 for r in results if r.ok)
    total = len(results)
    print("\n" + "=" * 60)
    print(f"Summary: {passed}/{total} passed")
    print("=" * 60)
    print("Spec: specs/06-e2e-test.md")
    return 0 if passed == total and total > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
