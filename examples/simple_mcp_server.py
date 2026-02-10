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
            tool_name="summarize",
            retries=1,
            fallback_used=False,
            confidence=0.92,
        )
        print("Model response:", response)
    finally:
        await exporter.close()


if __name__ == "__main__":
    asyncio.run(main())
