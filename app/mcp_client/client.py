
import sys
from pathlib import Path

from langchain_mcp_adapters.client import MultiServerMCPClient


PROJECT_ROOT = Path(__file__).resolve().parents[2]


async def load_mcp_tools():
    client = MultiServerMCPClient(
        {
            "chatbot_tools": {
                "command": sys.executable,
                "args": [
                    "-m",
                    "mcp_server.server",
                ],
                "transport": "stdio",
                "cwd": str(PROJECT_ROOT),
            }
        }
    )

    tools = await client.get_tools()

    return tools

