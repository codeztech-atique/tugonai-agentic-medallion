#!/usr/bin/env python3.11
"""
Deploy TugonAI Medallion stack to AWS Bedrock AgentCore (ap-south-1).

Order:
  1) IAM runtime role
  2) Memory (STM + LTM with SEMANTIC strategy only)
  3) MCP medallion-db runtime (protocol MCP, DATABASE_URL=Supabase)
  4) Gateway + Cognito + attach MCP target
  5) Schema + Quality agent runtimes (HTTP, Gateway + Memory)

Uses agentcore CLI S3 remote build (no local Docker required).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
REGION = os.environ.get("AWS_REGION", "ap-south-1")
ACCOUNT = boto3.client("sts").get_caller_identity()["Account"]
RUNTIME_ROLE_NAME = "TugonAIAgentCoreRuntimeRole"
MEMORY_NAME = "TugonAIMedallionSemanticMemory"
STATE_PATH = ROOT / "src" / "gateway" / "setup" / "deploy_state.json"

# Load .env
env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL or "localhost" in DATABASE_URL:
    print("ERROR: Set Supabase DATABASE_URL in .env before deploy")
    sys.exit(1)

os.environ["AWS_REGION"] = REGION
os.environ["AWS_DEFAULT_REGION"] = REGION


def sh(cmd: list[str] | str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    print(f"$ {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    return subprocess.run(
        cmd,
        cwd=str(cwd or ROOT),
        check=check,
        text=True,
        shell=isinstance(cmd, str),
    )


def save_state(update: dict) -> dict:
    state = {}
    if STATE_PATH.exists():
        state = json.loads(STATE_PATH.read_text())
    state.update(update)
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))
    return state


def ensure_runtime_role() -> str:
    iam = boto3.client("iam")
    try:
        arn = iam.get_role(RoleName=RUNTIME_ROLE_NAME)["Role"]["Arn"]
        print(f"✓ Runtime role exists: {arn}")
        return arn
    except ClientError:
        pass

    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": ACCOUNT},
                    "ArnLike": {
                        "aws:SourceArn": f"arn:aws:bedrock-agentcore:{REGION}:{ACCOUNT}:*"
                    },
                },
            }
        ],
    }
    print(f"Creating IAM role {RUNTIME_ROLE_NAME}…")
    iam.create_role(
        RoleName=RUNTIME_ROLE_NAME,
        AssumeRolePolicyDocument=json.dumps(trust),
        Description="Execution role for TugonAI AgentCore runtimes",
    )
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ECR",
                "Effect": "Allow",
                "Action": [
                    "ecr:GetAuthorizationToken",
                    "ecr:BatchGetImage",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchCheckLayerAvailability",
                ],
                "Resource": "*",
            },
            {
                "Sid": "Logs",
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                    "logs:DescribeLogStreams",
                ],
                "Resource": f"arn:aws:logs:{REGION}:{ACCOUNT}:*",
            },
            {
                "Sid": "BedrockModel",
                "Effect": "Allow",
                "Action": [
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                    "bedrock:Converse",
                    "bedrock:ConverseStream",
                    "bedrock:ApplyGuardrail",
                ],
                "Resource": "*",
            },
            {
                # First invoke of Marketplace-hosted models auto-subscribes;
                # without these, AgentCore ConverseStream returns AccessDeniedException.
                "Sid": "MarketplaceModelAccess",
                "Effect": "Allow",
                "Action": [
                    "aws-marketplace:ViewSubscriptions",
                    "aws-marketplace:Subscribe",
                    "aws-marketplace:Unsubscribe",
                ],
                "Resource": "*",
            },
            {
                "Sid": "AgentCoreMemory",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:CreateEvent",
                    "bedrock-agentcore:GetEvent",
                    "bedrock-agentcore:ListEvents",
                    "bedrock-agentcore:RetrieveMemoryRecords",
                    "bedrock-agentcore:GetMemoryRecord",
                    "bedrock-agentcore:ListMemoryRecords",
                    "bedrock-agentcore:GetMemory",
                    "bedrock-agentcore:DeleteEvent",
                ],
                "Resource": "*",
            },
            {
                "Sid": "XRay",
                "Effect": "Allow",
                "Action": [
                    "xray:PutTraceSegments",
                    "xray:PutTelemetryRecords",
                ],
                "Resource": "*",
            },
        ],
    }
    iam.put_role_policy(
        RoleName=RUNTIME_ROLE_NAME,
        PolicyName="TugonAIAgentCoreRuntimePolicy",
        PolicyDocument=json.dumps(policy),
    )
    print("Waiting 15s for IAM propagation…")
    time.sleep(15)
    arn = iam.get_role(RoleName=RUNTIME_ROLE_NAME)["Role"]["Arn"]
    print(f"✓ Created runtime role: {arn}")
    return arn


def ensure_memory() -> str:
    from bedrock_agentcore_starter_toolkit.operations.memory.manager import MemoryManager
    from bedrock_agentcore_starter_toolkit.operations.memory.models.strategies import (
        SemanticStrategy,
    )

    mgr = MemoryManager(region_name=REGION)
    # Prefer existing by name
    try:
        memories = boto3.client(
            "bedrock-agentcore-control", region_name=REGION
        ).list_memories()
        for m in memories.get("memories", []):
            if m.get("id") and MEMORY_NAME.lower() in (m.get("id") or "").lower():
                mid = m["id"]
                print(f"✓ Reusing memory: {mid}")
                return mid
            # list may return name field
            if m.get("name") == MEMORY_NAME:
                mid = m["id"]
                print(f"✓ Reusing memory: {mid}")
                return mid
    except Exception as e:
        print(f"list_memories note: {e}")

    print("Creating STM+LTM memory with SEMANTIC strategy only…")
    memory = mgr.create_memory_and_wait(
        name=MEMORY_NAME,
        description="TugonAI medallion agents — short-term sessions + semantic long-term",
        strategies=[
            SemanticStrategy(
                name="SemanticFacts",
                description="Semantic facts for medallion pipeline agents",
                namespaces=["/users/{actorId}/facts"],
            )
        ],
        event_expiry_days=30,
        enable_observability=False,
        max_wait=300,
        poll_interval=8,
    )
    mid = memory.id if hasattr(memory, "id") else memory["id"]
    print(f"✓ Memory ACTIVE: {mid}")
    return mid


def write_agentcore_config(
    project_dir: Path,
    agent_name: str,
    entrypoint: str,
    role_arn: str,
    memory_id: str | None,
    memory_enabled: bool,
) -> None:
    cfg_dir = project_dir / ".agentcore"
    cfg_dir.mkdir(exist_ok=True)
    memory_block = {
        "enabled": memory_enabled,
        "mode": "create_new" if memory_enabled else "skip",
        "memory_id": memory_id or "",
        "short_term_retention_days": 30,
        "long_term_retention": "unlimited",
        "strategies": ["semantic_memory"],
    }
    config = {
        "entrypoint": entrypoint,
        "entry_module": Path(entrypoint).stem,
        "agent_name": agent_name,
        "cfn_logical_id": "".join(
            p[:1].upper() + p[1:] for p in agent_name.replace("-", "_").split("_") if p
        ),
        "requirements_file": "requirements.txt",
        "deployment_type": "s3",
        "python_runtime": "PYTHON_3_11",
        "aws_region": REGION,
        "aws_account": ACCOUNT,
        "company_prefix": "tugonai",
        "company_id": ACCOUNT,
        "execution_role": role_arn,
        "s3_uri": "",
        "container_uri": "",
        "authorization": {"mode": "iam", "oauth_issuer": "", "oauth_audience": ""},
        "request_header_allowlist": "",
        "memory": memory_block,
    }
    (cfg_dir / "config.json").write_text(json.dumps(config, indent=2))

    mem_mode = "STM_AND_LTM" if memory_enabled else "DISABLED"
    yml = f"""version: 1

agent:
  name: "{agent_name}"
  language: python
  entrypoint: "{entrypoint}"
  entry_module: "{Path(entrypoint).stem}"
  requirements: "requirements.txt"

deployment:
  type: "s3"
  region: "{REGION}"
  account: "{ACCOUNT}"
  runtime: "PYTHON_3_11"
  execution_role: "{role_arn}"
  s3_uri: ""
  container_uri: ""

lifecycle_configuration:
  idle_runtime_session_timeout: null
  max_lifetime: null

bedrock_agentcore:
  agent_id: null
  agent_arn: null
  agent_session_id: null

codebuild:
  project_name: null
  execution_role: null
  source_bucket: null

memory:
  mode: {mem_mode}
  memory_id: "{memory_id or ''}"
  memory_arn: null
  memory_name: "{agent_name}_memory"
  event_expiry_days: 30
  first_invoke_memory_check_done: false
  was_created_by_toolkit: false

identity:
  credential_providers: []
  workload: null

aws_jwt:
  enabled: false
  audiences: []
  signing_algorithm: ES384
  issuer_url: null
  duration_seconds: 300

authorization_configuration:
  mode: "iam"
  oauth_configuration:
    issuer_url: ""
    audience: ""

request_header_configuration:
  allowlist: ""

api_key_env_var_name: null
"""
    (project_dir / "bedrock_agentcore.yml").write_text(yml)


def normalize_runtime_name(name: str) -> str:
    name = name.replace("-", "_").replace(" ", "_").lower()
    name = "".join(c for c in name if c.isalnum() or c == "_")
    if not name or not name[0].isalpha():
        name = "a_" + name
    return name[:48]


def find_runtime_id(runtime_name: str) -> str | None:
    client = boto3.client("bedrock-agentcore-control", region_name=REGION)
    resp = client.list_agent_runtimes()
    for r in resp.get("agentRuntimes", []):
        if r.get("agentRuntimeName") == runtime_name:
            return r.get("agentRuntimeId")
    return None


def get_runtime(runtime_id: str) -> dict:
    client = boto3.client("bedrock-agentcore-control", region_name=REGION)
    return client.get_agent_runtime(agentRuntimeId=runtime_id)


def wait_runtime_ready(runtime_id: str, timeout_s: int = 600) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        info = get_runtime(runtime_id)
        status = info.get("status") or info.get("agentRuntimeStatus")
        print(f"  wait {runtime_id}: status={status}")
        if status in ("READY", "ACTIVE"):
            return info
        if status in ("CREATE_FAILED", "UPDATE_FAILED", "FAILED", "DELETE_FAILED"):
            raise RuntimeError(f"Runtime failed: {info}")
        time.sleep(8)
    raise TimeoutError(f"Runtime not ready: {runtime_id}")


def update_runtime_env(
    runtime_id: str,
    role_arn: str,
    container_uri: str,
    protocol: str,
    env: dict[str, str],
) -> None:
    client = boto3.client("bedrock-agentcore-control", region_name=REGION)
    wait_runtime_ready(runtime_id)
    if container_uri and not container_uri.endswith(":latest") and ":" not in container_uri.split("/")[-1]:
        container_uri = f"{container_uri}:latest"
    kwargs = {
        "agentRuntimeId": runtime_id,
        "agentRuntimeArtifact": {
            "containerConfiguration": {"containerUri": container_uri}
        },
        "roleArn": role_arn,
        "networkConfiguration": {"networkMode": "PUBLIC"},
        "protocolConfiguration": {"serverProtocol": protocol},
        "environmentVariables": env,
    }
    print(f"Updating runtime {runtime_id} protocol={protocol} env_keys={list(env)}")
    client.update_agent_runtime(**kwargs)
    wait_runtime_ready(runtime_id)


def deploy_with_cli(project_dir: Path, stack_name: str) -> str:
    """Run agentcore deploy; return runtime id."""
    agent_name = json.loads((project_dir / ".agentcore" / "config.json").read_text())[
        "agent_name"
    ]
    runtime_name = normalize_runtime_name(agent_name)
    sh(["agentcore", "deploy", "--stack-name", stack_name, "--region", REGION], cwd=project_dir)
    rid = find_runtime_id(runtime_name)
    if not rid:
        # retry list
        time.sleep(5)
        rid = find_runtime_id(runtime_name)
    if not rid:
        raise RuntimeError(f"Runtime not found after deploy: {runtime_name}")
    return rid


def setup_gateway() -> dict:
    from bedrock_agentcore_starter_toolkit.operations.gateway.client import GatewayClient
    import logging

    client = GatewayClient(region_name=REGION)
    client.logger.setLevel(logging.INFO)
    name = "tugonai-medallion-gateway"
    print("Creating Cognito OAuth + Gateway (semantic search ON)…")
    cognito = client.create_oauth_authorizer_with_cognito(name)
    gateway = client.create_mcp_gateway(
        name=name,
        role_arn=None,
        authorizer_config=cognito["authorizer_config"],
        enable_semantic_search=True,
    )
    client.fix_iam_permissions(gateway)
    print("Waiting 60s for IAM propagation…")
    time.sleep(60)
    cfg = {
        "gateway_url": gateway["gatewayUrl"],
        "gateway_id": gateway["gatewayId"],
        "region": REGION,
        "client_info": cognito["client_info"],
    }
    out = ROOT / "src" / "gateway" / "setup" / "gateway_config.json"
    out.write_text(json.dumps(cfg, indent=2))
    print(f"✓ Gateway saved: {out}")
    return cfg


def attach_mcp(gateway_cfg: dict, mcp_endpoint: str) -> None:
    from bedrock_agentcore_starter_toolkit.operations.gateway.client import GatewayClient

    client = GatewayClient(region_name=REGION)
    gateway = {
        "gatewayUrl": gateway_cfg["gateway_url"],
        "gatewayId": gateway_cfg["gateway_id"],
    }
    print(f"Attaching MCP target medallion-db → {mcp_endpoint}")
    target = client.create_mcp_gateway_target(
        gateway=gateway,
        name="medallion-db",
        target_type="mcp_server",
        target_payload={"mcp_endpoint": mcp_endpoint},
        credentials=None,
    )
    path = ROOT / "src" / "gateway" / "targets" / "mcp" / "target_medallion-db.json"
    path.write_text(json.dumps(target, indent=2, default=str))
    print(f"✓ Target attached: {path}")


def runtime_mcp_endpoint(runtime_id: str) -> str:
    info = get_runtime(runtime_id)
    # Prefer explicit endpoint URL fields when present
    for key in ("agentRuntimeEndpoint", "endpointUrl", "agentRuntimeArn"):
        if key in info and isinstance(info[key], str) and info[key].startswith("http"):
            url = info[key].rstrip("/")
            return url if url.endswith("/mcp") else f"{url}/mcp"

    # Construct from ARN pattern used by AgentCore
    arn = info.get("agentRuntimeArn") or ""
    # Fallback: list endpoints
    ctrl = boto3.client("bedrock-agentcore-control", region_name=REGION)
    try:
        eps = ctrl.list_agent_runtime_endpoints(agentRuntimeId=runtime_id)
        for ep in eps.get("agentRuntimeEndpoints", []) or eps.get("endpoints", []) or []:
            for k in ("agentRuntimeEndpointUrl", "endpointUrl", "url"):
                if ep.get(k):
                    url = ep[k].rstrip("/")
                    return url if url.endswith("/mcp") else f"{url}/mcp"
    except Exception as e:
        print(f"endpoint list note: {e}")

    # Last resort documented invoke URL shape
    # https://bedrock-agentcore.{region}.amazonaws.com/runtimes/{encoded_arn}/invocations
    from urllib.parse import quote

    if arn:
        encoded = quote(arn, safe="")
        base = f"https://bedrock-agentcore.{REGION}.amazonaws.com/runtimes/{encoded}/invocations"
        return base  # attach script may need /mcp — caller adjusts
    raise RuntimeError(f"Could not resolve MCP endpoint for {runtime_id}: {info}")


def main():
    print("=" * 60)
    print("TugonAI AgentCore deploy")
    print("=" * 60)

    role_arn = ensure_runtime_role()
    memory_id = ensure_memory()
    save_state({"runtime_role_arn": role_arn, "memory_id": memory_id, "region": REGION})

    # --- MCP ---
    mcp_dir = ROOT / "src" / "tools" / "mcp" / "medallion_db"
    write_agentcore_config(
        mcp_dir,
        agent_name="medallion_db_mcp",
        entrypoint="main.py",
        role_arn=role_arn,
        memory_id=None,
        memory_enabled=False,
    )
    print("\n=== Deploying Medallion DB MCP ===")
    mcp_runtime_id = deploy_with_cli(mcp_dir, "medallion-db-mcp")
    mcp_info = get_runtime(mcp_runtime_id)
    container_uri = (
        mcp_info.get("agentRuntimeArtifact", {})
        .get("containerConfiguration", {})
        .get("containerUri")
    )
    if not container_uri:
        # fallback from config
        cfg = json.loads((mcp_dir / ".agentcore" / "config.json").read_text())
        container_uri = cfg.get("container_uri", "") + ":latest"
        if not container_uri.endswith(":latest"):
            container_uri = (cfg.get("container_uri") or "") + ":latest"

    update_runtime_env(
        mcp_runtime_id,
        role_arn,
        container_uri if ":" in container_uri else f"{container_uri}:latest",
        protocol="MCP",
        env={
            "DATABASE_URL": DATABASE_URL,
            "CSV_PATH": "/app/data/raw_tickets.csv",
            "AWS_REGION": REGION,
            "PORT": "8000",
        },
    )
    save_state({"mcp_runtime_id": mcp_runtime_id, "mcp_container_uri": container_uri})

    # Wait for READY then resolve endpoint
    time.sleep(10)
    mcp_endpoint = runtime_mcp_endpoint(mcp_runtime_id)
    if not mcp_endpoint.endswith("/mcp") and "invocations" not in mcp_endpoint:
        mcp_endpoint = mcp_endpoint.rstrip("/") + "/mcp"
    print(f"MCP endpoint candidate: {mcp_endpoint}")
    save_state({"mcp_endpoint": mcp_endpoint})

    # --- Gateway ---
    print("\n=== Setting up Gateway ===")
    gw_cfg_path = ROOT / "src" / "gateway" / "setup" / "gateway_config.json"
    if gw_cfg_path.exists():
        gateway_cfg = json.loads(gw_cfg_path.read_text())
        print(f"✓ Reusing gateway_config.json ({gateway_cfg.get('gateway_id')})")
    else:
        gateway_cfg = setup_gateway()
    try:
        attach_mcp(gateway_cfg, mcp_endpoint)
    except Exception as e:
        print(f"Attach MCP warning (may need endpoint tweak): {e}")
        # Try with /mcp suffix variants
        for alt in [
            mcp_endpoint,
            mcp_endpoint.rstrip("/") + "/mcp",
            mcp_endpoint.replace("/invocations", "/mcp"),
        ]:
            try:
                print(f"Retry attach with {alt}")
                attach_mcp(gateway_cfg, alt)
                mcp_endpoint = alt
                break
            except Exception as e2:
                print(f"  failed: {e2}")
        else:
            raise

    save_state({"gateway": gateway_cfg, "mcp_endpoint": mcp_endpoint})
    gateway_json = json.dumps(gateway_cfg)

    # --- Agents ---
    for name, rel, stack in [
        ("schema_agent", "src/agents/http/strands/schema_agent", "tugonai-schema-agent"),
        ("quality_agent", "src/agents/http/strands/quality_agent", "tugonai-quality-agent"),
    ]:
        project = ROOT / rel
        write_agentcore_config(
            project,
            agent_name=name,
            entrypoint="main.py",
            role_arn=role_arn,
            memory_id=memory_id,
            memory_enabled=True,
        )
        # Bake gateway config file into image as fallback
        (project / "gateway_config.json").write_text(json.dumps(gateway_cfg, indent=2))
        print(f"\n=== Deploying {name} ===")
        rid = deploy_with_cli(project, stack)
        info = get_runtime(rid)
        curi = (
            info.get("agentRuntimeArtifact", {})
            .get("containerConfiguration", {})
            .get("containerUri")
        )
        if not curi:
            curi = json.loads((project / ".agentcore" / "config.json").read_text()).get(
                "container_uri", ""
            )
            if curi and not curi.endswith(":latest"):
                curi = f"{curi}:latest"
        update_runtime_env(
            rid,
            role_arn,
            curi,
            protocol="HTTP",
            env={
                "AWS_REGION": REGION,
                "MODEL_ID": os.environ.get(
                    "MODEL_ID", "apac.anthropic.claude-3-haiku-20240307-v1:0"
                ),
                "BEDROCK_AGENTCORE_MEMORY_ID": memory_id,
                "MEMORY_ID": memory_id,
                "GATEWAY_CONFIG_JSON": gateway_json,
            },
        )
        save_state({f"{name}_runtime_id": rid})

    print("\n" + "=" * 60)
    print("DEPLOY COMPLETE")
    print(json.dumps(json.loads(STATE_PATH.read_text()), indent=2))
    print("=" * 60)


if __name__ == "__main__":
    main()
