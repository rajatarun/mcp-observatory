"""Example MCP server instrumentation using MCP Observatory and PostgresExporter."""

from __future__ import annotations

import asyncio
import os

from mcp_observatory import instrument
from mcp_observatory.exporters import PostgresExporter


async def main() -> None:
    dsn = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")

    exporter = PostgresExporter(dsn=dsn)
    interceptor = instrument("example-mcp-server", exporter=exporter)

    try:
        response = await interceptor.intercept_model_call(
            model="gpt-4o",
            prompt="Invoice #92311 at 2026-02-10T12:01:00Z for customer 1002 uuid 550e8400-e29b-41d4-a716-446655440000",
            response="Needs human review before approval.",
            tool_name="payment_risk_check",
            retries=1,
            confidence=0.42,
            risk_tier="high",
            prompt_template_id="payment-risk-v3",
            is_shadow=True,
            shadow_parent_trace_id="11111111-1111-4111-8111-111111111111",
            gate_blocked=True,
            fallback_used=True,
            fallback_type="human_review",
            fallback_reason="low_confidence",
        )
        print("Model response:", response)
    finally:
        await exporter.close()


if __name__ == "__main__":
    asyncio.run(main())
