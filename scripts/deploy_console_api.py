#!/usr/bin/env python3.11
"""
Deploy harness/ui FastAPI as a Lambda Function URL and attach it to CloudFront /api/*.

  /opt/homebrew/bin/python3.11 scripts/deploy_console_api.py

Requires: aws CLI, pip, zip. Uses deploy_state.json + AWS credentials from the environment.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI_DIR = ROOT / "harness" / "ui"
STATE_PATH = ROOT / "src" / "gateway" / "setup" / "deploy_state.json"
QUESTIONS_PATH = ROOT / "harness" / "questions.json"

FUNCTION_NAME = os.environ.get("CONSOLE_API_FUNCTION", "tugonai-console-api")
ROLE_NAME = os.environ.get("CONSOLE_API_ROLE", "TugonAIConsoleApiRole")
CF_ID = os.environ.get("CLOUDFRONT_DISTRIBUTION_ID", "E83KARFKKWVE5")
LAMBDA_REGION = os.environ.get("CONSOLE_API_REGION", "us-east-1")
AGENT_REGION = os.environ.get("AWS_REGION", "ap-south-1")
ACCOUNT = os.environ.get("AWS_ACCOUNT", "485947658225")


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd))
    try:
        return subprocess.run(cmd, check=True, text=True, capture_output=True, **kwargs)
    except subprocess.CalledProcessError as e:
        print(e.stdout or "")
        print(e.stderr or "")
        raise


def aws_json(cmd: list[str]) -> dict:
    out = run(cmd).stdout
    return json.loads(out) if out.strip() else {}


def aws_ok(cmd: list[str]) -> bool:
    p = subprocess.run(cmd, text=True, capture_output=True)
    return p.returncode == 0


def ensure_role() -> str:
    role_arn = f"arn:aws:iam::{ACCOUNT}:role/{ROLE_NAME}"
    if aws_ok(["aws", "iam", "get-role", "--role-name", ROLE_NAME]):
        print(f"Role exists: {role_arn}")
        return role_arn
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    run(
        [
            "aws",
            "iam",
            "create-role",
            "--role-name",
            ROLE_NAME,
            "--assume-role-policy-document",
            json.dumps(trust),
        ]
    )
    run(
        [
            "aws",
            "iam",
            "attach-role-policy",
            "--role-name",
            ROLE_NAME,
            "--policy-arn",
            "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
        ]
    )
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:InvokeAgentRuntime",
                    "bedrock:InvokeModel",
                    "bedrock:InvokeModelWithResponseStream",
                ],
                "Resource": "*",
            }
        ],
    }
    run(
        [
            "aws",
            "iam",
            "put-role-policy",
            "--role-name",
            ROLE_NAME,
            "--policy-name",
            "AgentCoreInvoke",
            "--policy-document",
            json.dumps(policy),
        ]
    )
    print("Waiting for IAM role propagation…")
    time.sleep(12)
    return role_arn


def build_zip() -> Path:
    if not STATE_PATH.exists():
        raise SystemExit(f"Missing {STATE_PATH}")
    if not QUESTIONS_PATH.exists():
        raise SystemExit(f"Missing {QUESTIONS_PATH}")

    build = Path(tempfile.mkdtemp(prefix="tugonai-console-api-"))
    print(f"Packaging in {build}")
    run(
        [
            "pip3",
            "install",
            "--quiet",
            "--upgrade",
            "--platform",
            "manylinux2014_x86_64",
            "--implementation",
            "cp",
            "--python-version",
            "3.12",
            "--only-binary=:all:",
            "--target",
            str(build),
            "mangum",
            "fastapi",
            "pydantic",
            "starlette",
            "anyio",
            "typing-extensions",
            "annotated-types",
            "pydantic-core",
            "idna",
            "sniffio",
        ]
    )
    shutil.copy(UI_DIR / "app.py", build / "app.py")
    shutil.copy(UI_DIR / "lambda_handler.py", build / "lambda_handler.py")
    shutil.copy(QUESTIONS_PATH, build / "questions.json")

    # Strip Cognito client secret from Lambda package.
    state = json.loads(STATE_PATH.read_text())
    gw = state.get("gateway") or {}
    slim = {
        "schema_agent_runtime_id": state.get("schema_agent_runtime_id"),
        "quality_agent_runtime_id": state.get("quality_agent_runtime_id"),
        "memory_id": state.get("memory_id"),
        "mcp_runtime_id": state.get("mcp_runtime_id"),
        "region": state.get("region") or AGENT_REGION,
        "gateway": {"gateway_id": gw.get("gateway_id")},
    }
    (build / "deploy_state.json").write_text(json.dumps(slim, indent=2))

    zip_path = ROOT / "build" / "console-api.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    if zip_path.exists():
        zip_path.unlink()
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", root_dir=build)
    shutil.rmtree(build, ignore_errors=True)
    print(f"Zip: {zip_path} ({zip_path.stat().st_size // 1024} KB)")
    return zip_path


def upsert_lambda(role_arn: str, zip_path: Path) -> str:
    env = {
        "Variables": {
            "AWS_REGION": AGENT_REGION,
            # Reserved keys cannot be set; region for boto3 via AWS_REGION above.
            "SCHEMA_AGENT_RUNTIME_ID": json.loads(STATE_PATH.read_text())[
                "schema_agent_runtime_id"
            ],
            "QUALITY_AGENT_RUNTIME_ID": json.loads(STATE_PATH.read_text())[
                "quality_agent_runtime_id"
            ],
            "MEMORY_ID": json.loads(STATE_PATH.read_text()).get("memory_id") or "",
            "MCP_RUNTIME_ID": json.loads(STATE_PATH.read_text()).get("mcp_runtime_id")
            or "",
            "GATEWAY_ID": (json.loads(STATE_PATH.read_text()).get("gateway") or {}).get(
                "gateway_id"
            )
            or "",
        }
    }
    # Lambda forbids setting AWS_REGION in environment for some runtimes —
    # use AGENT_AWS_REGION and patch app if needed. Try AGENT_REGION instead.
    env["Variables"].pop("AWS_REGION", None)
    env["Variables"]["AGENT_AWS_REGION"] = AGENT_REGION

    exists = aws_ok(
        [
            "aws",
            "lambda",
            "get-function",
            "--function-name",
            FUNCTION_NAME,
            "--region",
            LAMBDA_REGION,
        ]
    )

    if not exists:
        out = aws_json(
            [
                "aws",
                "lambda",
                "create-function",
                "--function-name",
                FUNCTION_NAME,
                "--runtime",
                "python3.12",
                "--role",
                role_arn,
                "--handler",
                "lambda_handler.handler",
                "--timeout",
                "120",
                "--memory-size",
                "512",
                "--zip-file",
                f"fileb://{zip_path}",
                "--environment",
                json.dumps(env),
                "--region",
                LAMBDA_REGION,
            ]
        )
        print("Created function", out.get("FunctionArn"))
    else:
        run(
            [
                "aws",
                "lambda",
                "update-function-code",
                "--function-name",
                FUNCTION_NAME,
                "--zip-file",
                f"fileb://{zip_path}",
                "--region",
                LAMBDA_REGION,
            ]
        )
        # Wait for code update before config update.
        time.sleep(3)
        run(
            [
                "aws",
                "lambda",
                "update-function-configuration",
                "--function-name",
                FUNCTION_NAME,
                "--timeout",
                "120",
                "--memory-size",
                "512",
                "--environment",
                json.dumps(env),
                "--region",
                LAMBDA_REGION,
            ]
        )
        print("Updated function", FUNCTION_NAME)

    # Wait active
    for _ in range(30):
        cfg = aws_json(
            [
                "aws",
                "lambda",
                "get-function-configuration",
                "--function-name",
                FUNCTION_NAME,
                "--region",
                LAMBDA_REGION,
            ]
        )
        if cfg.get("State") == "Active" and cfg.get("LastUpdateStatus") in (
            None,
            "Successful",
        ):
            break
        time.sleep(2)

    return f"arn:aws:lambda:{LAMBDA_REGION}:{ACCOUNT}:function:{FUNCTION_NAME}"


def ensure_function_url() -> str:
    if aws_ok(
        [
            "aws",
            "lambda",
            "get-function-url-config",
            "--function-name",
            FUNCTION_NAME,
            "--region",
            LAMBDA_REGION,
        ]
    ):
        out = aws_json(
            [
                "aws",
                "lambda",
                "get-function-url-config",
                "--function-name",
                FUNCTION_NAME,
                "--region",
                LAMBDA_REGION,
            ]
        )
        url = out["FunctionUrl"]
        print("Function URL exists:", url)
        return url.rstrip("/")

    out = aws_json(
        [
            "aws",
            "lambda",
            "create-function-url-config",
            "--function-name",
            FUNCTION_NAME,
            "--auth-type",
            "NONE",
            "--cors",
            json.dumps(
                {
                    "AllowOrigins": ["*"],
                    "AllowMethods": ["*"],
                    "AllowHeaders": ["*"],
                    "MaxAge": 86400,
                }
            ),
            "--region",
            LAMBDA_REGION,
        ]
    )
    p = subprocess.run(
        [
            "aws",
            "lambda",
            "add-permission",
            "--function-name",
            FUNCTION_NAME,
            "--statement-id",
            "FunctionURLAllowPublicAccess",
            "--action",
            "lambda:InvokeFunctionUrl",
            "--principal",
            "*",
            "--function-url-auth-type",
            "NONE",
            "--region",
            LAMBDA_REGION,
        ],
        text=True,
        capture_output=True,
    )
    if p.returncode != 0 and "ResourceConflictException" not in (p.stderr or ""):
        print(p.stderr)
        raise SystemExit(p.returncode)
    p2 = subprocess.run(
        [
            "aws",
            "lambda",
            "add-permission",
            "--function-name",
            FUNCTION_NAME,
            "--statement-id",
            "FunctionURLAllowInvokeFunction",
            "--action",
            "lambda:InvokeFunction",
            "--principal",
            "*",
            "--region",
            LAMBDA_REGION,
        ],
        text=True,
        capture_output=True,
    )
    if p2.returncode != 0 and "ResourceConflictException" not in (p2.stderr or ""):
        print(p2.stderr)
        raise SystemExit(p2.returncode)
    url = out["FunctionUrl"]
    print("Created Function URL:", url)
    return url.rstrip("/")


def attach_cloudfront(function_url: str) -> None:
    # function_url like https://abc.lambda-url.us-east-1.on.aws
    domain = function_url.replace("https://", "").rstrip("/")
    raw = run(
        [
            "aws",
            "cloudfront",
            "get-distribution-config",
            "--id",
            CF_ID,
        ]
    ).stdout
    payload = json.loads(raw)
    etag = payload["ETag"]
    cfg = payload["DistributionConfig"]

    origins = cfg.setdefault("Origins", {"Quantity": 0, "Items": []})
    items = origins.setdefault("Items", [])
    origin_id = "tugonai-console-api"
    items = [o for o in items if o.get("Id") != origin_id]
    items.append(
        {
            "Id": origin_id,
            "DomainName": domain,
            "OriginPath": "",
            "CustomHeaders": {"Quantity": 0},
            "CustomOriginConfig": {
                "HTTPPort": 80,
                "HTTPSPort": 443,
                "OriginProtocolPolicy": "https-only",
                "OriginSslProtocols": {"Quantity": 1, "Items": ["TLSv1.2"]},
                "OriginReadTimeout": 60,
                "OriginKeepaliveTimeout": 5,
            },
            "ConnectionAttempts": 3,
            "ConnectionTimeout": 10,
            "OriginShield": {"Enabled": False},
        }
    )
    origins["Items"] = items
    origins["Quantity"] = len(items)

    behaviors = cfg.setdefault("CacheBehaviors", {"Quantity": 0, "Items": []})
    bitems = [
        b
        for b in behaviors.get("Items", [])
        if b.get("PathPattern") not in {"/api", "/api/*"}
    ]
    # CachingDisabled + AllViewerExceptHostHeader (managed policies)
    api_behavior = {
        "PathPattern": "/api/*",
        "TargetOriginId": origin_id,
        "ViewerProtocolPolicy": "redirect-to-https",
        "AllowedMethods": {
            "Quantity": 7,
            "Items": ["HEAD", "DELETE", "POST", "GET", "OPTIONS", "PUT", "PATCH"],
            "CachedMethods": {"Quantity": 2, "Items": ["HEAD", "GET"]},
        },
        "SmoothStreaming": False,
        "Compress": True,
        "LambdaFunctionAssociations": {"Quantity": 0},
        "FunctionAssociations": {"Quantity": 0},
        "FieldLevelEncryptionId": "",
        "CachePolicyId": "4135ea2d-6df8-44a3-9df3-4b5a84be39ad",  # CachingDisabled
        "OriginRequestPolicyId": "b689b0a8-53d0-40ab-baf2-68738e2966ac",  # AllViewerExceptHostHeader
        "TrustedSigners": {"Enabled": False, "Quantity": 0},
        "TrustedKeyGroups": {"Enabled": False, "Quantity": 0},
    }
    bitems.insert(0, api_behavior)
    behaviors["Items"] = bitems
    behaviors["Quantity"] = len(bitems)

    # S3 REST origins do not use bucket website IndexDocument — set this or `/` 403s.
    cfg["DefaultRootObject"] = "index.html"

    # Stop mapping missing objects to index.html@200 (was masking /api as empty SSE).
    cfg["CustomErrorResponses"] = {
        "Quantity": 2,
        "Items": [
            {
                "ErrorCode": 403,
                "ResponsePagePath": "/error.html",
                "ResponseCode": "403",
                "ErrorCachingMinTTL": 0,
            },
            {
                "ErrorCode": 404,
                "ResponsePagePath": "/error.html",
                "ResponseCode": "404",
                "ErrorCachingMinTTL": 0,
            },
        ],
    }

    tmp = Path(tempfile.mkstemp(suffix=".json")[1])
    tmp.write_text(json.dumps(cfg))
    run(
        [
            "aws",
            "cloudfront",
            "update-distribution",
            "--id",
            CF_ID,
            "--if-match",
            etag,
            "--distribution-config",
            f"file://{tmp}",
        ]
    )
    tmp.unlink(missing_ok=True)
    print(f"CloudFront {CF_ID} updated: /api/* → {domain}")


def sync_static_and_invalidate() -> None:
    run(
        [
            "aws",
            "s3",
            "sync",
            str(UI_DIR / "static"),
            "s3://tugonai/",
            "--delete",
            "--exclude",
            ".DS_Store",
        ]
    )
    inv = aws_json(
        [
            "aws",
            "cloudfront",
            "create-invalidation",
            "--distribution-id",
            CF_ID,
            "--paths",
            "/*",
        ]
    )
    print("Invalidation:", inv.get("Invalidation", {}).get("Id"))


def main() -> None:
    # app.py reads AWS_REGION for AgentCore client — map AGENT_AWS_REGION in Lambda via
    # a tiny patch in app if needed. Set process env for local packaging clarity.
    os.environ.setdefault("AWS_REGION", AGENT_REGION)

    role_arn = ensure_role()
    zip_path = build_zip()
    upsert_lambda(role_arn, zip_path)
    url = ensure_function_url()
    attach_cloudfront(url)
    sync_static_and_invalidate()
    print("\nDone.")
    print(f"Function URL: {url}")
    print(f"Console: https://d2ho05na7pcde8.cloudfront.net")
    print("Wait ~1–3 min for CloudFront to deploy, then hard-refresh.")


if __name__ == "__main__":
    main()
