"""
Shared Gateway Client — OAuth + MCP transport for all agents.

Supports:
  1) GATEWAY_CONFIG_JSON env (full JSON)
  2) GATEWAY_CONFIG_PATH / gateway_config.json file
"""

import json
import os
import sys
from pathlib import Path

from bedrock_agentcore_starter_toolkit.operations.gateway.client import GatewayClient
from mcp.client.streamable_http import streamablehttp_client


class GatewaySession:
    def __init__(self, config_path=None):
        self.config = self._load_config(config_path)
        self.region = self.config.get("region") or os.environ.get("AWS_REGION", "ap-south-1")
        self.gateway_url = self.config["gateway_url"]
        self._client = GatewayClient(region_name=self.region)
        self.access_token = self._client.get_access_token_for_cognito(
            self.config["client_info"]
        )

    def create_transport(self):
        return streamablehttp_client(
            self.gateway_url,
            headers={"Authorization": f"Bearer {self.access_token}"},
        )

    def transport_factory(self):
        return lambda: self.create_transport()

    @staticmethod
    def _load_config(config_path=None):
        raw = os.getenv("GATEWAY_CONFIG_JSON", "").strip()
        if raw:
            return json.loads(raw)

        candidates = []
        if config_path:
            candidates.append(Path(config_path))
        env_path = os.getenv("GATEWAY_CONFIG_PATH", "")
        if env_path:
            candidates.append(Path(env_path))
        here = Path(__file__).resolve().parent
        candidates.extend(
            [
                here / "gateway_config.json",
                Path("/app/gateway_config.json"),
                Path.cwd() / "gateway_config.json",
            ]
        )
        try:
            candidates.append(
                Path(__file__).resolve().parents[1]
                / "gateway"
                / "setup"
                / "gateway_config.json"
            )
        except IndexError:
            pass

        for p in candidates:
            try:
                if p.exists():
                    with open(p) as f:
                        return json.load(f)
            except OSError:
                continue

        print("ERROR: gateway_config.json / GATEWAY_CONFIG_JSON not found!")
        print("Run:  cd src/gateway/setup && python setup_gateway.py")
        sys.exit(1)


def list_gateway_tools(mcp_client):
    all_tools, more, token = [], True, None
    while more:
        page = mcp_client.list_tools_sync(pagination_token=token)
        all_tools.extend(page)
        token = page.pagination_token
        more = token is not None
    return all_tools
