# MCP Observatory

Enterprise-grade observability and APM instrumentation for Model Context Protocol (MCP) servers.

MCP Observatory provides structured tracing, cost telemetry, prompt identity controls, risk-routing signals, and PostgreSQL export capabilities so platform teams can operate MCP workloads with production governance and measurable SLOs.

## 1. Executive Summary

MCP Observatory is designed for organizations running model-backed workflows that require:

- auditable prompt and response telemetry,
- cost visibility and control,
- confidence-based gating and fallback routing,
- shadow traffic analysis,
- standardized persistence into SQL analytics systems.

It introduces a lightweight instrumentation API for MCP server code paths while preserving operationally useful fields for incident response, compliance, and continuous optimization.

---

## 2. Core Capabilities

### 2.1 Distributed Trace Context (MCP-Oriented)
Each model interaction is captured as a trace span with canonical IDs and execution metadata:

- `trace_id`, `span_id`, `parent_span_id`
- `service`, `model`, `tool_name`
- `start_time`, `end_time`

### 2.2 Token and Cost APM Metrics
Built-in token estimation and model pricing support:

- `prompt_tokens`
- `completion_tokens`
- `cost_usd`
- `retries`

### 2.3 Prompt Identity & Template Governance
For template drift analysis and noisy prompt clustering:

- `prompt_template_id` (manual template/version ID)
- `prompt_hash` (SHA-256 of the exact final prompt)
- `normalized_prompt_hash` (SHA-256 after normalizing UUIDs, timestamps, numbers)
- `prompt_size_chars`

### 2.4 Risk, Gating, and Fallback Routing Signals
For policy-driven execution and safe degradation:

- `risk_tier`
- `confidence`
- `gate_blocked`
- `fallback_used`
- `fallback_type` (`template | human_review | draft_only`)
- `fallback_reason` (`low_confidence | tool_error | policy_violation`)

### 2.5 Shadow Evaluation Support
For offline/parallel quality comparisons:

- `is_shadow`
- `shadow_parent_trace_id`

### 2.6 PostgreSQL Export
Native async exporter writes structured spans to Postgres (`asyncpg`) for SIEM/APM warehouse integration.

---

## 3. Architecture Overview

```text
MCP Server Handler
   │
   ├── MCPInterceptor.intercept_model_call(...)
   │      ├── TraceContext creation
   │      ├── prompt hashing / normalization
   │      ├── token + cost estimation
   │      └── risk/gate/fallback/shadow field capture
   │
   └── Exporter (optional)
          └── PostgresExporter -> mcp_traces table
```

---

## 4. Installation

```bash
pip install mcp-observatory
```

For development:

```bash
pip install -e .[dev]
```

---

## 5. Enterprise Quick Start

```python
import asyncio
from mcp_observatory import instrument
from mcp_observatory.exporters.postgres import PostgresExporter

exporter = PostgresExporter("postgresql://user:pass@localhost/mcp")
interceptor = instrument(service_name="payments-mcp", exporter=exporter)


async def main() -> None:
    await interceptor.intercept_model_call(
        model="gpt-4o",
        tool_name="payment_risk_check",
        prompt="Invoice #92311 at 2026-02-10T12:01:00Z for customer 1002 uuid 550e8400-e29b-41d4-a716-446655440000",
        response="Needs human review before approval.",

        # Governance metadata
        risk_tier="high",
        prompt_template_id="payment-risk-v3",

        # Shadow mode
        is_shadow=True,
        shadow_parent_trace_id="11111111-1111-4111-8111-111111111111",

        # Gate + fallback routing
        confidence=0.42,
        gate_blocked=True,
        fallback_used=True,
        fallback_type="human_review",
        fallback_reason="low_confidence",

        retries=1,
    )

    await exporter.close()


asyncio.run(main())
```

---

## 6. Operational Field Dictionary

| Field | Type | Purpose |
|---|---|---|
| `trace_id` | UUID | End-to-end request correlation |
| `span_id` | UUID | Span-level unique ID |
| `parent_span_id` | UUID | Parent linkage for nested spans |
| `service` | TEXT | Service boundary identifier |
| `model` | TEXT | Model used for generation |
| `tool_name` | TEXT | MCP tool/function path |
| `start_time` / `end_time` | TIMESTAMP | Execution timing |
| `prompt_tokens` / `completion_tokens` | INT | Usage telemetry |
| `cost_usd` | FLOAT | Estimated spend |
| `retries` | INT | Retry behavior tracking |
| `fallback_used` | BOOLEAN | Whether fallback was triggered |
| `confidence` | FLOAT | Confidence signal from app/model |
| `risk_tier` | TEXT | Manual risk classification |
| `prompt_template_id` | TEXT | Template version control |
| `prompt_hash` | TEXT | Exact prompt identity |
| `normalized_prompt_hash` | TEXT | Prompt identity minus dynamic noise |
| `prompt_size_chars` | INT | Prompt payload size |
| `is_shadow` | BOOLEAN | Shadow evaluation marker |
| `shadow_parent_trace_id` | UUID | Parent trace reference for shadow run |
| `gate_blocked` | BOOLEAN | Gate decision status |
| `fallback_type` | TEXT | Fallback strategy used |
| `fallback_reason` | TEXT | Why fallback was used |

---

## 7. Prompt Normalization Strategy

`normalized_prompt_hash` is derived by replacing volatile entities before hashing:

- UUIDs → `<uuid>`
- timestamps → `<timestamp>`
- numbers → `<number>`
- whitespace collapsed, then lowercased

This enables high-signal clustering for semantically equivalent prompts with runtime-specific IDs.

---

## 8. PostgreSQL Schema and Setup

Apply schema:

```bash
psql "$DATABASE_URL" -f schema/postgres.sql
```

The schema includes indexes for:

- `trace_id`
- `(service, start_time DESC)`
- `(model, start_time DESC)`
- `prompt_hash`
- `normalized_prompt_hash`

---

## 9. Reliability and Governance Patterns

Recommended enterprise patterns:

1. **Confidence-Gated Execution**
   - Block or downgrade responses when confidence drops below policy threshold.
2. **Deterministic Fallback Routing**
   - Always set `fallback_type` and `fallback_reason` for auditable fallback behavior.
3. **Template Lifecycle Management**
   - Use `prompt_template_id` as a mandatory deployment artifact (e.g., `risk-v3.2`).
4. **Shadow Rollouts**
   - Enable `is_shadow=true` for candidate model validation before production cutover.
5. **Prompt Drift Monitoring**
   - Alert on sudden spread of `normalized_prompt_hash` cardinality per tool/service.

---

## 10. Example Script

Run the included end-to-end sample:

```bash
python examples/simple_mcp_server.py
```

---

## 11. License

Apache License 2.0. See [LICENSE](LICENSE).
