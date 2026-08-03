#!/usr/bin/env python3.11
"""
Question harness for Schema + Quality agents on AgentCore.

Modes:
  list     — print curated questions (no AWS calls)
  ask      — ask one question by id (S1, Q2, …)
  interactive — REPL against an agent
  batch    — run a set and save transcripts under harness/results/

Usage:
  set -a && source .env && set +a
  /opt/homebrew/bin/python3.11 harness/run_harness.py list
  /opt/homebrew/bin/python3.11 harness/run_harness.py ask S3
  /opt/homebrew/bin/python3.11 harness/run_harness.py interactive --agent schema
  /opt/homebrew/bin/python3.11 harness/run_harness.py batch --agent quality --ids Q1,Q2,Q3
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS_PATH = ROOT / "harness" / "questions.json"
STATE_PATH = ROOT / "src" / "gateway" / "setup" / "deploy_state.json"
RESULTS_DIR = ROOT / "harness" / "results"

# Load .env
env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def load_questions() -> dict:
    return json.loads(QUESTIONS_PATH.read_text())


def load_state() -> dict:
    if not STATE_PATH.exists():
        raise SystemExit(f"Missing {STATE_PATH}. Deploy first.")
    return json.loads(STATE_PATH.read_text())


def runtime_url(runtime_id: str) -> str:
    region = os.environ.get("AWS_REGION", "ap-south-1")
    account = "485947658225"
    arn = f"arn:aws:bedrock-agentcore:{region}:{account}:runtime/{runtime_id}"
    return (
        f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/"
        f"{quote(arn, safe='')}/invocations?qualifier=DEFAULT"
    )


def invoke_agent(
    runtime_id: str,
    prompt: str,
    session_id: str,
    actor_id: str,
) -> dict:
    import boto3
    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    region = os.environ.get("AWS_REGION", "ap-south-1")
    url = runtime_url(runtime_id)
    body = json.dumps(
        {"prompt": prompt, "session_id": session_id, "actor_id": actor_id}
    ).encode()
    creds = boto3.Session(region_name=region).get_credentials().get_frozen_credentials()
    req = AWSRequest(
        method="POST",
        url=url,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    SigV4Auth(creds, "bedrock-agentcore", region).add_auth(req)
    prepared = req.prepare()
    http_req = urllib.request.Request(
        prepared.url, data=prepared.body, headers=dict(prepared.headers)
    )
    with urllib.request.urlopen(http_req, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


def agent_runtime_id(state: dict, agent: str) -> str:
    key = {
        "schema": "schema_agent_runtime_id",
        "schema_agent": "schema_agent_runtime_id",
        "quality": "quality_agent_runtime_id",
        "quality_agent": "quality_agent_runtime_id",
    }[agent]
    return state[key]


def find_question(qid: str) -> tuple[str, dict]:
    data = load_questions()
    qid = qid.upper()
    for agent_key, items in data.items():
        if agent_key == "memory_session":
            for item in items:
                if item["id"].upper() == qid:
                    return "memory", item
            continue
        for item in items:
            if item["id"].upper() == qid:
                agent = "schema" if agent_key.startswith("schema") else "quality"
                return agent, item
    raise SystemExit(f"Unknown question id: {qid}")


def score_signals(text: str, signals: list[str]) -> tuple[list[str], list[str]]:
    lower = text.lower()
    hit, miss = [], []
    for s in signals:
        if s.lower() in lower:
            hit.append(s)
        else:
            miss.append(s)
    return hit, miss


def cmd_list(_: argparse.Namespace) -> None:
    data = load_questions()
    print("\n=== Schema Agent — ask these ===\n")
    for q in data["schema_agent"]:
        print(f"{q['id']}  {q['title']}")
        print(f"    Q: {q['prompt']}")
        print(f"    Why: {q['why_ask']}\n")

    print("=== Quality Agent — ask these ===\n")
    for q in data["quality_agent"]:
        print(f"{q['id']}  {q['title']}")
        print(f"    Q: {q['prompt']}")
        print(f"    Why: {q['why_ask']}\n")

    print("=== Memory / session ===\n")
    for q in data["memory_session"]:
        print(f"{q['id']}  {q['title']}")
        for i, turn in enumerate(q["turns"], 1):
            print(f"    Turn {i}: {turn}")
        print(f"    Why: {q['why_ask']}\n")


def cmd_ask(args: argparse.Namespace) -> None:
    state = load_state()
    agent, q = find_question(args.id)
    session_id = args.session or f"harness-{q['id'].lower()}-{int(time.time())}"
    actor_id = args.actor or "harness-user"

    if agent == "memory":
        rid = agent_runtime_id(state, q.get("agent", "schema_agent"))
        print(f"Running memory turns on {q.get('agent')} session={session_id}")
        transcript = []
        for i, turn in enumerate(q["turns"], 1):
            print(f"\n--- Turn {i} ---\n> {turn}\n")
            resp = invoke_agent(rid, turn, session_id, actor_id)
            print(json.dumps(resp, indent=2)[:3000])
            transcript.append({"turn": i, "prompt": turn, "response": resp})
            time.sleep(1)
        text = str(transcript[-1]["response"].get("response", ""))
        hit, miss = score_signals(text, q.get("expect_signals", []))
        print(f"\nSignals hit={hit} miss={miss}")
        return

    rid = agent_runtime_id(state, agent)
    print(f"[{q['id']}] {q['title']} → {agent}  session={session_id}")
    print(f"\n> {q['prompt']}\n")
    resp = invoke_agent(rid, q["prompt"], session_id, actor_id)
    print(json.dumps(resp, indent=2)[:4000])
    blob = json.dumps(resp)
    hit, miss = score_signals(blob, q.get("expect_signals", []))
    print(f"\nSignals hit={hit} miss={miss}")
    if args.save:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        out = RESULTS_DIR / f"{q['id']}-{int(time.time())}.json"
        out.write_text(
            json.dumps(
                {
                    "question": q,
                    "session_id": session_id,
                    "actor_id": actor_id,
                    "response": resp,
                    "signals_hit": hit,
                    "signals_miss": miss,
                    "at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            )
        )
        print(f"Saved {out}")


def cmd_interactive(args: argparse.Namespace) -> None:
    state = load_state()
    rid = agent_runtime_id(state, args.agent)
    session_id = args.session or f"interactive-{int(time.time())}"
    actor_id = args.actor or "harness-user"
    print(f"Interactive {args.agent}  session={session_id}  (type exit to quit)\n")
    while True:
        try:
            prompt = input("You> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not prompt:
            continue
        if prompt.lower() in {"exit", "quit"}:
            break
        resp = invoke_agent(rid, prompt, session_id, actor_id)
        if resp.get("error"):
            print(f"Error: {resp['error']}\n")
        else:
            print(f"Agent> {resp.get('response')}\n")


def cmd_batch(args: argparse.Namespace) -> None:
    state = load_state()
    data = load_questions()
    agent = args.agent
    bank = data["schema_agent"] if agent.startswith("schema") else data["quality_agent"]
    ids = {x.strip().upper() for x in args.ids.split(",") if x.strip()} if args.ids else {
        q["id"] for q in bank
    }
    session_id = args.session or f"batch-{agent}-{int(time.time())}"
    actor_id = args.actor or "harness-user"
    rid = agent_runtime_id(state, agent)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    results = []

    for q in bank:
        if q["id"] not in ids:
            continue
        print(f"\n>>> {q['id']} {q['title']}")
        resp = invoke_agent(rid, q["prompt"], f"{session_id}-{q['id']}", actor_id)
        blob = json.dumps(resp)
        hit, miss = score_signals(blob, q.get("expect_signals", []))
        row = {
            "id": q["id"],
            "title": q["title"],
            "prompt": q["prompt"],
            "response": resp,
            "signals_hit": hit,
            "signals_miss": miss,
            "ok_soft": len(hit) >= max(1, len(q.get("expect_signals", [])) // 2),
        }
        results.append(row)
        print(f"    soft_pass={row['ok_soft']} hit={hit} miss={miss}")
        time.sleep(1)

    out = RESULTS_DIR / f"batch-{agent}-{run_id}.json"
    out.write_text(
        json.dumps(
            {
                "agent": agent,
                "session_prefix": session_id,
                "results": results,
                "at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        )
    )
    passed = sum(1 for r in results if r["ok_soft"])
    print(f"\nBatch done: {passed}/{len(results)} soft-pass → {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description="TugonAI question harness")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="Show curated questions")
    p_list.set_defaults(func=cmd_list)

    p_ask = sub.add_parser("ask", help="Ask one curated question by id")
    p_ask.add_argument("id", help="e.g. S3 or Q2 or M1")
    p_ask.add_argument("--session", default="")
    p_ask.add_argument("--actor", default="")
    p_ask.add_argument("--save", action="store_true")
    p_ask.set_defaults(func=cmd_ask)

    p_int = sub.add_parser("interactive", help="Free-form chat with an agent")
    p_int.add_argument("--agent", choices=["schema", "quality"], default="schema")
    p_int.add_argument("--session", default="")
    p_int.add_argument("--actor", default="")
    p_int.set_defaults(func=cmd_interactive)

    p_batch = sub.add_parser("batch", help="Run several curated questions")
    p_batch.add_argument("--agent", choices=["schema", "quality"], required=True)
    p_batch.add_argument("--ids", default="", help="Comma ids, default all for agent")
    p_batch.add_argument("--session", default="")
    p_batch.add_argument("--actor", default="")
    p_batch.set_defaults(func=cmd_batch)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
