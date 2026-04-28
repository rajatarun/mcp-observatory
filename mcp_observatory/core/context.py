"""Tracing context models for MCP requests and model invocations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import uuid4

from ..utils.time import utc_now_naive


def _new_id() -> str:
    return str(uuid4())


@dataclass
class TraceContext:
    """Represents telemetry for a single MCP interaction span."""

    service: str
    model: Optional[str] = None
    tool_name: Optional[str] = None
    trace_id: str = field(default_factory=_new_id)
    span_id: str = field(default_factory=_new_id)
    parent_span_id: Optional[str] = None
    start_time: datetime = field(default_factory=utc_now_naive)
    end_time: Optional[datetime] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    retries: int = 0
    fallback_used: bool = False
    confidence: Optional[float] = None

    # v1/v2 shared fields
    risk_tier: Optional[str] = None
    prompt_template_id: Optional[str] = None
    prompt_hash: Optional[str] = None
    normalized_prompt_hash: Optional[str] = None
    answer_hash: Optional[str] = None
    grounding_score: Optional[float] = None
    verifier_score: Optional[float] = None
    self_consistency_score: Optional[float] = None
    numeric_variance_score: Optional[float] = None
    tool_claim_mismatch: Optional[bool] = None
    hallucination_risk_score: Optional[float] = None
    hallucination_risk_level: Optional[str] = None
    prompt_size_chars: int = 0
    is_shadow: bool = False
    shadow_parent_trace_id: Optional[str] = None
    gate_blocked: bool = False
    fallback_type: Optional[str] = None
    fallback_reason: Optional[str] = None

    # v2 execution control plane
    request_id: Optional[str] = None
    session_id: Optional[str] = None
    method: Optional[str] = None
    tool_args_hash: Optional[str] = None
    tool_criticality: Optional[str] = None
    policy_decision: Optional[str] = None
    policy_id: Optional[str] = None
    policy_version: Optional[str] = None
    grounding_risk: Optional[float] = None
    self_consistency_risk: Optional[float] = None
    numeric_instability_risk: Optional[float] = None
    tool_mismatch_risk: Optional[float] = None
    drift_risk: Optional[float] = None
    composite_risk_score: Optional[float] = None
    composite_risk_level: Optional[str] = None
    shadow_disagreement_score: Optional[float] = None
    shadow_numeric_variance: Optional[float] = None
    exec_token_id: Optional[str] = None
    exec_token_ttl_ms: Optional[int] = None
    exec_token_hash: Optional[str] = None
    exec_token_verified: Optional[bool] = None

    def finish(self) -> None:
        self.end_time = utc_now_naive()

    def to_dict(self) -> dict:
        return self.__dict__.copy()
