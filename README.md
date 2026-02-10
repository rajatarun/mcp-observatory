# MCP Observatory

MCP Observatory is a lightweight observability / APM library for Model Context Protocol (MCP) servers. It traces model calls, estimates token usage/cost, and exports telemetry to PostgreSQL.

## Features

- `TraceContext` aligned to PostgreSQL schema fields.
- Prompt identity fields:
  - `prompt_template_id` (manual template/version id)
  - `prompt_hash` (hash of final prompt)
  - `normalized_prompt_hash` (hash after removing numbers/timestamps/UUIDs)
  - `prompt_size_chars`
- Safety and routing fields:
  - `risk_tier` (manual)
  - `is_shadow`, `shadow_parent_trace_id`
  - `gate_blocked` (manual or confidence-threshold derived)
  - `fallback_used`, `fallback_type`, `fallback_reason`
- `MCPInterceptor` to wrap model calls and collect metrics.
- `PostgresExporter` powered by `asyncpg`.

## Installation

```bash
pip install mcp-observatory
```

For local development:

```bash
pip install -e .[dev]
```

## Quick start

```python
import asyncio
from mcp_observatory import instrument
from mcp_observatory.exporters.postgres import PostgresExporter

exporter = PostgresExporter("postgresql://user:pass@localhost/mcp")
interceptor = instrument(service_name="example-mcp", exporter=exporter)


async def main():
    await interceptor.intercept_model_call(
        model="gpt-4o",
        prompt="Invoice #92311 at 2026-02-10T12:01:00Z for customer 1002 uuid 550e8400-e29b-41d4-a716-446655440000",
        response="Needs human review before approval.",
        risk_tier="high",
        prompt_template_id="payment-risk-v3",
        is_shadow=True,
        shadow_parent_trace_id="11111111-1111-4111-8111-111111111111",
        confidence=0.42,
        gate_blocked=True,
        fallback_used=True,
        fallback_type="human_review",
        fallback_reason="low_confidence",
    )


asyncio.run(main())
```

## Notes on prompt hashes

- `prompt_hash` is SHA-256 of the exact final prompt.
- `normalized_prompt_hash` is SHA-256 after normalization that replaces:
  - UUIDs -> `<uuid>`
  - timestamps -> `<timestamp>`
  - numbers -> `<number>`

This helps detect semantically-similar prompts despite volatile IDs or timestamps.

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
