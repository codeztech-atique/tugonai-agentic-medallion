"""
Gateway Setup — Create AgentCore Gateway + Cognito OAuth2.0 (ap-south-1)

Usage:
  pip install -r requirements.txt
  python setup_gateway.py
"""

from bedrock_agentcore_starter_toolkit.operations.gateway.client import GatewayClient
import json
import logging
import time

REGION = "ap-south-1"
GATEWAY_NAME = "tugonai-medallion-gateway"


def setup_gateway():
    print(f"Setting up AgentCore Gateway in {REGION}...")

    client = GatewayClient(region_name=REGION)
    client.logger.setLevel(logging.INFO)

    print("\n[1/4] Creating Cognito OAuth2.0 authorization server...")
    cognito = client.create_oauth_authorizer_with_cognito(GATEWAY_NAME)
    print("  -> Cognito user pool + app client created")

    print("\n[2/4] Creating MCP Gateway with semantic search...")
    gateway = client.create_mcp_gateway(
        name=GATEWAY_NAME,
        role_arn=None,
        authorizer_config=cognito["authorizer_config"],
        enable_semantic_search=True,
    )
    print(f"  -> Gateway URL : {gateway['gatewayUrl']}")
    print(f"  -> Gateway ID  : {gateway['gatewayId']}")

    print("\n[3/4] Configuring IAM permissions...")
    client.fix_iam_permissions(gateway)
    print("  -> Waiting 60s for IAM propagation...")
    time.sleep(60)
    print("  -> IAM role ready")

    config = {
        "gateway_url": gateway["gatewayUrl"],
        "gateway_id": gateway["gatewayId"],
        "region": REGION,
        "client_info": cognito["client_info"],
    }

    with open("gateway_config.json", "w") as f:
        json.dump(config, f, indent=2)

    print("\n" + "=" * 65)
    print("Gateway setup complete!")
    print(f"  Config saved: gateway_config.json")
    print("Next: deploy medallion-db MCP, then attach_mcp_target.py")
    print("=" * 65)
    return config


if __name__ == "__main__":
    setup_gateway()
