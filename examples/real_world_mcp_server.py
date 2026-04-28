"""Run the real-world MCP server scenarios demo."""

from __future__ import annotations

import asyncio

from mcp_observatory.demo.real_world_server import main


if __name__ == "__main__":
    asyncio.run(main())
