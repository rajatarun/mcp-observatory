# MCP Observatory

MCP Observatory provides observability and a **risk-bound execution control plane** for MCP tools.

## v2 Architecture (Control Plane + Data Plane)

### Control Plane
1. Intercept `tools/call` requests.
2. Compute risk vector signals (grounding, self-consistency, numeric instability, tool mismatch, prompt drift, verifier risk).
3. Compute renormalized composite risk score.
4. Evaluate tool policy matrix by criticality and score (`ALLOW`, `BLOCK`, `REVIEW`).
5. If required, issue short-lived signed internal execution token.
6. Verify token at tool wrapper boundary.
7. If blocked/reviewed, route deterministic fallback or deterministic safe response.
8. Optionally schedule async shadow verification lane for disagreement metrics.

### Data Plane
All decisions and telemetry are exported to Postgres (`mcp_traces`) for dashboards and audit.

> Security note: execution tokens are internal signed authorization artifacts for tool execution. They are **not OAuth** and should not be exposed externally. Persist only token hashes.

## Composite Risk Formula

Weights:
- grounding_risk: `0.30`
- self_consistency_risk: `0.25`
- verifier_risk: `0.25`
- numeric_instability_risk: `0.10`
- tool_mismatch_risk: `0.10`
- drift_risk: `0.10`

Only non-null components are used, then weights are renormalized:

```text
composite = sum(risk_i * w_i) / sum(w_i)  # over non-None risks
```

Risk levels:
- `< 0.20` -> `low`
- `0.20 <= score < 0.35` -> `medium`
- `>= 0.35` -> `high`

## Policy Matrix

- **HIGH criticality**
  - `score >= 0.35`: `BLOCK`
  - `0.20 <= score < 0.35`: `REVIEW`
  - `< 0.20`: `ALLOW` (token required)
- **MEDIUM criticality**
  - `score >= 0.50`: `REVIEW`
  - else `ALLOW` (token not required)
- **LOW criticality**
  - always `ALLOW`

## Quick Start

```python
import asyncio
from mcp_observatory import instrument
from mcp_observatory.policy.registry import DEFAULT_REGISTRY, tool_profile
from mcp_observatory.fallback.router import FallbackRouter

@tool_profile(criticality="HIGH", irreversible=True, regulatory=True, risk_tier="HIGH", registry=DEFAULT_REGISTRY)
async def execute_transfer(*, amount: float, destination: str):
    return {"status": "executed", "amount": amount, "destination": destination}

async def draft_transfer(tool_args: dict):
    return {"status": "draft_created", **tool_args}

async def main():
    router = FallbackRouter()
    router.register("execute_transfer", draft_transfer)

    interceptor = instrument("payments", fallback_router=router)

    result = await interceptor.intercept_tool_call(
        tool_name="execute_transfer",
        tool_args={"amount": 1000.0, "destination": "acct-001"},
        tool_fn=execute_transfer,
        prompt="Transfer funds now",
        model_answer="Transfer completed successfully.",
        tool_result_summary="payment API failed: transfer declined",
        retrieved_context="declined transfer",
        prompt_template_id="payments-v2",
    )
    print(result)

asyncio.run(main())
```

## Postgres Schema

Apply schema:

```bash
psql "$DATABASE_URL" -f schema/postgres.sql
```

Recommended dashboard pivots:
- decision trends: `policy_decision` over time
- risk distribution: `composite_risk_level`, `composite_risk_score`
- high-risk tools: `(service, tool_name)` with `BLOCK/REVIEW` rate
- drift tracking: `prompt_template_id` + `prompt_hash`
- shadow quality: `shadow_disagreement_score`, `shadow_numeric_variance`

## Example

Run:

```bash
python examples/simple_mcp_server.py
```

This example registers a high-criticality tool and demonstrates deterministic fallback when risk policy blocks direct execution.
