"""Tracing context models for MCP requests and model invocations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4


def _new_id() -> str:
    """Generate a unique trace/span identifier as UUID text."""
    return str(uuid4())


@dataclass
class TraceContext:
    """Represents telemetry for a single MCP model interaction span.

    Fields are intentionally aligned with the PostgreSQL schema in
    ``schema/postgres.sql``.
    """

    service: str
    model: Optional[str] = None
    tool_name: Optional[str] = None
    trace_id: str = field(default_factory=_new_id)
    span_id: str = field(default_factory=_new_id)
    parent_span_id: Optional[str] = None
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    end_time: Optional[datetime] = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    retries: int = 0
    fallback_used: bool = False
    confidence: Optional[float] = None

    # Requested additional controls/attributes.
    risk_tier: Optional[str] = None
    prompt_template_id: Optional[str] = None
    prompt_hash: Optional[str] = None
    normalized_prompt_hash: Optional[str] = None
    prompt_size_chars: int = 0
    is_shadow: bool = False
    shadow_parent_trace_id: Optional[str] = None
    gate_blocked: bool = False
    fallback_type: Optional[str] = None
    fallback_reason: Optional[str] = None

    def finish(self) -> None:
        """Mark the span as finished."""
        self.end_time = datetime.now(timezone.utc).replace(tzinfo=None)

    def to_dict(self) -> dict:
        """Serialize context for exporters."""
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "service": self.service,
            "model": self.model,
            "tool_name": self.tool_name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cost_usd": self.cost_usd,
            "retries": self.retries,
            "fallback_used": self.fallback_used,
            "confidence": self.confidence,
            "risk_tier": self.risk_tier,
            "prompt_template_id": self.prompt_template_id,
            "prompt_hash": self.prompt_hash,
            "normalized_prompt_hash": self.normalized_prompt_hash,
            "prompt_size_chars": self.prompt_size_chars,
            "is_shadow": self.is_shadow,
            "shadow_parent_trace_id": self.shadow_parent_trace_id,
            "gate_blocked": self.gate_blocked,
            "fallback_type": self.fallback_type,
            "fallback_reason": self.fallback_reason,
        }
