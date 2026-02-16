"""PostgreSQL exporter for MCP Observatory trace data."""

from __future__ import annotations

from typing import Optional

import asyncpg

from ..core.context import TraceContext
from .base import Exporter


INSERT_SQL = """
INSERT INTO mcp_traces (
    trace_id, span_id, parent_span_id, service, model, tool_name,
    start_time, end_time, prompt_tokens, completion_tokens, cost_usd,
    retries, fallback_used, confidence,
    risk_tier, prompt_template_id, prompt_hash, normalized_prompt_hash, answer_hash,
    grounding_score, verifier_score, self_consistency_score, numeric_variance_score,
    tool_claim_mismatch, hallucination_risk_score, hallucination_risk_level,
    prompt_size_chars, is_shadow, shadow_parent_trace_id, gate_blocked,
    fallback_type, fallback_reason,
    request_id, session_id, method, tool_args_hash, tool_criticality,
    policy_decision, policy_id, policy_version,
    grounding_risk, self_consistency_risk, numeric_instability_risk,
    tool_mismatch_risk, drift_risk, composite_risk_score, composite_risk_level,
    shadow_disagreement_score, shadow_numeric_variance,
    exec_token_id, exec_token_ttl_ms, exec_token_hash, exec_token_verified
)
VALUES (
    $1::uuid, $2::uuid, $3::uuid, $4, $5, $6,
    $7, $8, $9, $10, $11,
    $12, $13, $14,
    $15, $16, $17, $18, $19,
    $20, $21, $22, $23,
    $24, $25, $26,
    $27, $28, $29::uuid, $30,
    $31, $32,
    $33, $34, $35, $36, $37,
    $38, $39, $40,
    $41, $42, $43,
    $44, $45, $46, $47,
    $48, $49,
    $50, $51, $52, $53
)
"""


class PostgresExporter(Exporter):
    """Exporter that persists spans into PostgreSQL using ``asyncpg``."""

    def __init__(
        self,
        dsn: Optional[str] = None,
        *,
        pool: Optional[asyncpg.Pool] = None,
        min_size: int = 1,
        max_size: int = 10,
    ) -> None:
        self._dsn = dsn
        self._pool = pool
        self._min_size = min_size
        self._max_size = max_size

    async def connect(self) -> None:
        if self._pool is not None:
            return
        if not self._dsn:
            raise ValueError("Either `dsn` or `pool` must be provided for PostgresExporter.")

        self._pool = await asyncpg.create_pool(dsn=self._dsn, min_size=self._min_size, max_size=self._max_size)

    async def export(self, context: TraceContext) -> None:
        if self._pool is None:
            await self.connect()

        assert self._pool is not None
        p = context.to_dict()
        async with self._pool.acquire() as conn:
            await conn.execute(
                INSERT_SQL,
                p["trace_id"], p["span_id"], p["parent_span_id"], p["service"], p["model"], p["tool_name"],
                p["start_time"], p["end_time"], p["prompt_tokens"], p["completion_tokens"], p["cost_usd"],
                p["retries"], p["fallback_used"], p["confidence"],
                p["risk_tier"], p["prompt_template_id"], p["prompt_hash"], p["normalized_prompt_hash"], p["answer_hash"],
                p["grounding_score"], p["verifier_score"], p["self_consistency_score"], p["numeric_variance_score"],
                p["tool_claim_mismatch"], p["hallucination_risk_score"], p["hallucination_risk_level"],
                p["prompt_size_chars"], p["is_shadow"], p["shadow_parent_trace_id"], p["gate_blocked"],
                p["fallback_type"], p["fallback_reason"],
                p["request_id"], p["session_id"], p["method"], p["tool_args_hash"], p["tool_criticality"],
                p["policy_decision"], p["policy_id"], p["policy_version"],
                p["grounding_risk"], p["self_consistency_risk"], p["numeric_instability_risk"],
                p["tool_mismatch_risk"], p["drift_risk"], p["composite_risk_score"], p["composite_risk_level"],
                p["shadow_disagreement_score"], p["shadow_numeric_variance"],
                p["exec_token_id"], p["exec_token_ttl_ms"], p["exec_token_hash"], p["exec_token_verified"],
            )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
