"""Run the real-world MCP client against the in-process demo server."""

from __future__ import annotations

import asyncio

from mcp_observatory.demo.real_world_client import run_client_demo


async def main() -> None:
    results = await run_client_demo()
    print("Client executed scenarios against MCP server:")
    for item in results:
        status = item["result"].get("status", "unknown") if isinstance(item.get("result"), dict) else "unknown"
        print(f"- {item['scenario']}: status={status} pattern={item['execution_pattern']}")


if __name__ == "__main__":
    asyncio.run(main())
