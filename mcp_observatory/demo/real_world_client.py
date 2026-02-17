"""Simple MCP client demo that interacts with the real-world MCP server."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcp_observatory.demo.real_world_server import RealWorldMCPServer


@dataclass
class RealWorldMCPClient:
    """Minimal client that calls server-exposed scenario endpoints."""

    server: RealWorldMCPServer

    async def list_scenarios(self) -> list[str]:
        return await self.server.list_scenarios()

    async def execute_scenario(self, scenario_name: str) -> dict[str, Any]:
        return await self.server.execute_scenario_by_name(scenario_name)

    async def execute_all(self) -> list[dict[str, Any]]:
        scenario_names = await self.list_scenarios()
        results: list[dict[str, Any]] = []
        for scenario_name in scenario_names:
            results.append(await self.execute_scenario(scenario_name))
        return results


async def run_client_demo() -> list[dict[str, Any]]:
    server = RealWorldMCPServer()
    client = RealWorldMCPClient(server=server)
    try:
        return await client.execute_all()
    finally:
        await server.close()
