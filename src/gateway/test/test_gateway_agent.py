"""
Test Gateway — list medallion tools and run an interactive Strands agent.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient
try:
    from shared.gateway_client import GatewaySession, list_gateway_tools
except ImportError:
    from gateway_client import GatewaySession, list_gateway_tools  # type: ignore


REGION = os.environ.get("AWS_REGION", "ap-south-1")
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-4-6-20250624-v1:0")


def run():
    gw = GatewaySession()
    print(f"Gateway: {gw.gateway_url}")
    print(f"Region:  {gw.region}")
    print(f"Model:   {MODEL_ID}\n")

    mcp_client = MCPClient(gw.transport_factory())

    with mcp_client:
        tools = list_gateway_tools(mcp_client)
        print(f"Tools ({len(tools)}): {[t.tool_name for t in tools]}")
        print("-" * 60)

        model = BedrockModel(model_id=MODEL_ID, region_name=REGION, streaming=True)
        agent = Agent(
            model=model,
            tools=tools,
            system_prompt=(
                "You help with a medallion support-ticket lakehouse. "
                "Use MCP tools to inspect bronze/silver/gold/meta. Be concise."
            ),
        )

        print("\nInteractive Agent Ready (type 'exit' to quit)\n")
        while True:
            user_input = input("You: ").strip()
            if user_input.lower() in ("exit", "quit", "bye"):
                print("Goodbye!")
                break
            if not user_input:
                continue
            print("\nThinking...\n")
            response = agent(user_input)
            print(f"\nAgent: {response}\n")
            print("-" * 60)


if __name__ == "__main__":
    run()
