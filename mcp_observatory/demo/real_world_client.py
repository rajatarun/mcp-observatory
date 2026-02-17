"""Simple MCP client demo that interacts with the real-world MCP server."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcp_observatory.demo.real_world_server import RealWorldMCPServer, build_real_world_scenarios


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


@dataclass(frozen=True)
class PromptInvocationMVP:
    """Prompt-to-tool MVP using an LLM-style planner and server function invocation."""

    system_instruction: str = (
        "You are an MCP planner. Choose one server scenario name that best matches the user prompt. "
        "Return only the scenario name."
    )

    def generate_user_prompt_templates(self) -> list[str]:
        """Generate starter user prompts (GenSI-style prompt seeds) for MVP usage."""
        return [scenario.prompt for scenario in build_real_world_scenarios()]

    def llm_plan_scenario(self, user_prompt: str) -> str:
        """LLM-style planner: maps natural language prompt to scenario name.

        This is intentionally deterministic for demo/test reliability.
        """
        p = user_prompt.lower()
        rules = [
            ("wire", "wire-transfer-large-amount"),
            ("refund", "invoice-refund"),
            ("freeze card", "freeze-card-suspected-fraud"),
            ("unfreeze", "unfreeze-card-with-ticket"),
            ("overnight", "expedited-shipment"),
            ("cancel shipment", "cancel-shipment"),
            ("clinic", "schedule-clinic-visit"),
            ("subscription", "change-subscription-plan"),
            ("password", "reset-enterprise-password"),
            ("feature flag", "publish-feature-flag"),
        ]
        for token, scenario_name in rules:
            if token in p:
                return scenario_name
        return "invoice-refund"

    async def invoke_from_prompt(self, client: RealWorldMCPClient, user_prompt: str) -> dict[str, Any]:
        """Run full MVP loop: user prompt -> planned server function -> execution."""
        scenario_name = self.llm_plan_scenario(user_prompt)
        result = await client.execute_scenario(scenario_name)
        return {
            "system_instruction": self.system_instruction,
            "user_prompt": user_prompt,
            "planned_scenario": scenario_name,
            "server_response": result,
        }


async def run_client_demo() -> list[dict[str, Any]]:
    server = RealWorldMCPServer()
    client = RealWorldMCPClient(server=server)
    try:
        return await client.execute_all()
    finally:
        await server.close()


async def run_prompt_invocation_demo(user_prompt: str) -> dict[str, Any]:
    server = RealWorldMCPServer()
    client = RealWorldMCPClient(server=server)
    planner = PromptInvocationMVP()
    try:
        return await planner.invoke_from_prompt(client, user_prompt)
    finally:
        await server.close()
