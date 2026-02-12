"""Example MCP server instrumentation using MCP Observatory and PostgresExporter."""

from __future__ import annotations

import asyncio
import os

from mcp_observatory import HallucinationConfig, instrument
from mcp_observatory.exporters import PostgresExporter


async def main() -> None:
    dsn = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/postgres")

    exporter = PostgresExporter(dsn=dsn)
    interceptor = instrument(
        "example-mcp-server",
        exporter=exporter,
        hallucination_config=HallucinationConfig(enable_self_consistency=True, self_consistency_mode="shadow"),
    )

    try:
        response = await interceptor.intercept_model_call(
            model="gpt-4o",
            prompt="Invoice #92311 at 2026-02-10T12:01:00Z for customer 1002 uuid 550e8400-e29b-41d4-a716-446655440000",
            response="Payment completed and sent. Total due is 149.25 USD.",
            secondary_response="Payment done. Amount processed: 150.25 USD.",
            retrieved_context="invoice 92311 customer 1002 balance due 149.25 usd payment failed due to declined card",
            tool_result_summary="payment API failed: card declined by issuer",
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
        print("Hallucination fields were computed and exported with this call.")
    finally:
        await exporter.close()


if __name__ == "__main__":
    asyncio.run(main())
