"""Example MCP server using v2 risk-bound execution control plane."""

from __future__ import annotations

import asyncio
import os

from mcp_observatory import instrument
from mcp_observatory.exporters import PostgresExporter
from mcp_observatory.fallback.router import FallbackRouter
from mcp_observatory.policy.registry import DEFAULT_REGISTRY, tool_profile


@tool_profile(criticality="HIGH", irreversible=True, regulatory=True, risk_tier="HIGH", registry=DEFAULT_REGISTRY)
async def execute_transfer(*, amount: float, destination: str) -> dict:
    return {"status": "executed", "amount": amount, "destination": destination}


async def draft_transfer(tool_args: dict) -> dict:
    return {
        "status": "draft_created",
        "amount": tool_args.get("amount"),
        "destination": tool_args.get("destination"),
        "message": "Transfer blocked; created draft for review.",
    }


async def main() -> None:
    dsn = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")
    exporter = PostgresExporter(dsn=dsn)

    fallback_router = FallbackRouter()
    fallback_router.register("execute_transfer", draft_transfer)

    interceptor = instrument("example-mcp-server", exporter=exporter, fallback_router=fallback_router)

    try:
        result = await interceptor.intercept_tool_call(
            tool_name="execute_transfer",
            tool_args={"amount": 25000.0, "destination": "acct-0091"},
            tool_fn=execute_transfer,
            prompt="Transfer 25,000 USD to acct-0091 immediately.",
            model_answer="Transfer completed successfully and funds were sent.",
            secondary_answer="Transfer may have completed.",
            retrieved_context="payments gateway returned declined, transfer failed",
            tool_result_summary="payment API failed: transfer declined",
            prompt_template_id="transfer-prod-v2",
            request_id="req-demo-001",
            session_id="sess-demo-001",
            shadow_answer="Transfer failed and was not sent.",
        )
        print("Tool result:", result)
    finally:
        await exporter.close()


if __name__ == "__main__":
    asyncio.run(main())
