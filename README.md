# MCP Observatory

MCP Observatory is a lightweight observability / APM library for Model Context Protocol (MCP) servers. It traces model calls, estimates token usage/cost, and exports telemetry to PostgreSQL.

## Features

- `TraceContext` aligned to the PostgreSQL schema fields:
  - `trace_id`, `span_id`, `parent_span_id`, `service`, `model`, `tool_name`
  - `start_time`, `end_time`, `prompt_tokens`, `completion_tokens`, `cost_usd`
  - `retries`, `fallback_used`, `confidence`
- `Tracer` start/end span helpers.
- `MCPInterceptor` to wrap model calls and collect metrics.
- Token and cost estimation utilities.
- `PostgresExporter` powered by `asyncpg`.

## Installation

```bash
pip install mcp-observatory
```

For local development:

```bash
pip install -e .[dev]
```

## Quick start (your preferred usage)

```python
import asyncio
from mcp_observatory import instrument
from mcp_observatory.exporters.postgres import PostgresExporter

exporter = PostgresExporter("postgresql://user:pass@localhost/mcp")

interceptor = instrument(
    service_name="example-mcp",
    exporter=exporter,
)


async def main():
    await interceptor.intercept_model_call(
        model="gpt-4o",
        prompt="Hello MCP",
        response="Hello human",
    )


asyncio.run(main())
```

## Async callable mode

```python
async def model_call(*, prompt: str, model: str):
    return {"text": f"{model} says: {prompt}"}

await interceptor.intercept_model_call(
    model="gpt-4o-mini",
    prompt="What is MCP observability?",
    call=model_call,
    tool_name="answer_question",
)
```

## Database setup

Apply the schema from `schema/postgres.sql`:

```bash
psql "$DATABASE_URL" -f schema/postgres.sql
```

## Example script

```bash
python examples/simple_mcp_server.py
```

## License

Apache License 2.0. See [LICENSE](LICENSE).
