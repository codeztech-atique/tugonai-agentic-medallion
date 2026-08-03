"""
Attach Medallion DB MCP Server as a Gateway target.

Usage:
  python attach_mcp_target.py --name medallion-db --endpoint https://<runtime>/mcp
"""

import argparse
import json
import sys
from pathlib import Path

from bedrock_agentcore_starter_toolkit.operations.gateway.client import GatewayClient


def load_config():
    p = Path(__file__).resolve().parents[1] / "setup" / "gateway_config.json"
    if not p.exists():
        print(f"ERROR: {p} not found. Run setup_gateway.py first.")
        sys.exit(1)
    with open(p) as f:
        return json.load(f)


def attach(name, endpoint):
    cfg = load_config()
    client = GatewayClient(region_name=cfg["region"])
    gateway = {"gatewayUrl": cfg["gateway_url"], "gatewayId": cfg["gateway_id"]}

    print(f"Attaching MCP target '{name}' -> {endpoint}")
    target = client.create_mcp_gateway_target(
        gateway=gateway,
        name=name,
        target_type="mcp_server",
        target_payload={"mcp_endpoint": endpoint} if endpoint else None,
        credentials=None,
    )
    print(f"  -> Target attached: {json.dumps(target, indent=2, default=str)}")

    with open(f"target_{name}.json", "w") as f:
        json.dump(target, f, indent=2, default=str)
    print(f"  -> Saved: target_{name}.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="medallion-db")
    parser.add_argument("--endpoint", required=True, help="MCP server endpoint URL")
    args = parser.parse_args()
    attach(args.name, args.endpoint)
