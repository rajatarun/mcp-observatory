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
            prompt="Summarize the purpose of observability in MCP servers.",
            response="Observability helps you track performance, errors, and cost.",
            tool_name="payment_risk_check",
            retries=1,
            fallback_used=True,
            confidence=0.62,
            confidence_gate_threshold=0.70,
            high_risk_path=True,
            deterministic_fallback_triggered=True,
            prompt_diff_score=0.41,
            prompt_diff_threshold=0.30,
            shadow_agreement=False,
            is_golden_financial_scenario=True,
            golden_scenario_passed=False,
        )
        print("Model response:", response)
        print("Metrics snapshot:", interceptor.get_metrics_snapshot())
        print("Active alerts:", interceptor.get_active_alerts())
    finally:
        await exporter.close()


if __name__ == "__main__":
    asyncio.run(main())
