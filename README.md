# MCP Observatory

MCP Observatory is a lightweight observability / APM library for Model Context Protocol (MCP) servers. It traces model calls, estimates token usage/cost, and exports telemetry to PostgreSQL.

## Features

- `TraceContext` aligned to PostgreSQL schema fields:
  - `trace_id`, `span_id`, `parent_span_id`, `service`, `model`, `tool_name`
  - `start_time`, `end_time`, `prompt_tokens`, `completion_tokens`, `cost_usd`
  - `retries`, `fallback_used`, `confidence`
- `MCPInterceptor` with derived metrics for:
  - golden financial scenarios
  - prompt diff detectors
  - shadow model evaluations
  - confidence-gated execution
  - deterministic fallbacks for high-risk paths
- Built-in alert evaluation (`get_active_alerts`) from configurable thresholds.
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
        confidence=0.64,
        confidence_gate_threshold=0.70,
        high_risk_path=True,
        deterministic_fallback_triggered=True,
        prompt_diff_score=0.42,
        shadow_agreement=False,
        is_golden_financial_scenario=True,
        golden_scenario_passed=True,
    )

    snapshot = interceptor.get_metrics_snapshot()
    alerts = interceptor.get_active_alerts()
    print(snapshot)
    print(alerts)


asyncio.run(main())
```

## Metrics for decision patterns

`MCPInterceptor.get_metrics_snapshot()` provides rates and measurements to drive alerts:

- `avg_cost_usd`
- `fallback_rate`
- `retry_rate`
- `low_confidence_rate`
- `confidence_gate_block_rate`
- `prompt_diff_violation_rate`
- `shadow_disagreement_rate`
- `deterministic_fallback_rate`
- `high_risk_path_rate`
- `golden_financial_failure_rate`

`MCPInterceptor.get_active_alerts()` compares these against defaults and returns triggered alert keys.

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
