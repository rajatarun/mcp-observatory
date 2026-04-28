"""Tier-based execution policy for MCP responses with deterministic fallback."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

from ..core.context import TraceContext
from ..core.interceptor import MCPInterceptor, ModelCallable
from ..hallucination.scoring import clamp01

FallbackCallable = Callable[..., Awaitable[Any]]


@dataclass(frozen=True)
class ExecutionTier:
    """Policy thresholds for one execution tier."""

    name: str
    max_cost_usd: float
    min_confidence: float
    max_hallucination_risk: float


@dataclass(frozen=True)
class TieredExecutionConfig:
    """Three-tier configuration anchored by a base cost budget."""

    base_cost_usd: float
    tier_1: ExecutionTier
    tier_2: ExecutionTier
    tier_3: ExecutionTier

    @classmethod
    def from_base_cost(
        cls,
        base_cost_usd: float,
        *,
        tier_1_confidence: float,
        tier_1_hallucination_risk: float,
        tier_2_cost_multiplier: float = 2.0,
        tier_2_confidence: float = 0.75,
        tier_2_hallucination_risk: float = 0.30,
        tier_3_cost_multiplier: float = 3.0,
        tier_3_confidence: float = 0.85,
        tier_3_hallucination_risk: float = 0.20,
    ) -> "TieredExecutionConfig":
        """Build a standard three-tier policy from a base cost budget."""
        return cls(
            base_cost_usd=base_cost_usd,
            tier_1=ExecutionTier(
                name="tier_1",
                max_cost_usd=base_cost_usd,
                min_confidence=tier_1_confidence,
                max_hallucination_risk=tier_1_hallucination_risk,
            ),
            tier_2=ExecutionTier(
                name="tier_2",
                max_cost_usd=base_cost_usd * tier_2_cost_multiplier,
                min_confidence=tier_2_confidence,
                max_hallucination_risk=tier_2_hallucination_risk,
            ),
            tier_3=ExecutionTier(
                name="tier_3",
                max_cost_usd=base_cost_usd * tier_3_cost_multiplier,
                min_confidence=tier_3_confidence,
                max_hallucination_risk=tier_3_hallucination_risk,
            ),
        )

    def resolve_tier(self, tier_name: str) -> ExecutionTier:
        """Resolve a tier by name."""
        mapping: Dict[str, ExecutionTier] = {
            self.tier_1.name: self.tier_1,
            self.tier_2.name: self.tier_2,
            self.tier_3.name: self.tier_3,
        }
        if tier_name not in mapping:
            raise ValueError(f"Unknown tier '{tier_name}'. Expected one of: {', '.join(mapping.keys())}.")
        return mapping[tier_name]


@dataclass(frozen=True)
class ExecutionDecision:
    """Policy decision emitted by the instrumentation library."""

    tier: str
    accepted: bool
    response_source: str
    cost_breached: bool
    confidence_breached: bool
    hallucination_breached: bool
    fallback_used: bool
    fallback_reason: Optional[str]


@dataclass(frozen=True)
class ExecutionResult:
    """Output envelope containing response and policy metadata."""

    response: Any
    decision: ExecutionDecision
    mcp_span: TraceContext
    fallback_span: Optional[TraceContext] = None


class TieredExecutionEngine:
    """Executes MCP responses under tier policy and deterministic fallback."""

    def __init__(self, interceptor: MCPInterceptor, config: TieredExecutionConfig) -> None:
        self.interceptor = interceptor
        self.config = config

    async def execute(
        self,
        *,
        tier_name: str,
        model: str,
        prompt: str,
        mcp_call: Optional[ModelCallable] = None,
        mcp_response: Any = None,
        deterministic_fallback: Optional[FallbackCallable] = None,
        confidence: Optional[float] = None,
        secondary_response: Any = None,
        retrieved_context: Optional[str] = None,
        tool_result_summary: Optional[str] = None,
        tool_name: Optional[str] = None,
        **call_kwargs: Any,
    ) -> ExecutionResult:
        """Execute MCP call and apply tier policy against cost/confidence/hallucination."""
        tier = self.config.resolve_tier(tier_name)

        if mcp_call is None and mcp_response is None:
            raise ValueError("Either `mcp_call` or `mcp_response` must be provided.")

        mcp_result, mcp_span = await self.interceptor.intercept_model_call(
            model=model,
            prompt=prompt,
            response=mcp_response,
            call=mcp_call,
            tool_name=tool_name,
            confidence=confidence,
            secondary_response=secondary_response,
            retrieved_context=retrieved_context,
            tool_result_summary=tool_result_summary,
            return_span=True,
            **call_kwargs,
        )

        effective_confidence = self._effective_confidence(explicit_confidence=confidence, span=mcp_span)
        cost_breached = mcp_span.cost_usd > tier.max_cost_usd
        confidence_breached = effective_confidence is None or effective_confidence < tier.min_confidence
        hallucination_risk = mcp_span.hallucination_risk_score if mcp_span.hallucination_risk_score is not None else 1.0
        hallucination_breached = hallucination_risk > tier.max_hallucination_risk

        if not confidence_breached and not hallucination_breached:
            decision = ExecutionDecision(
                tier=tier.name,
                accepted=True,
                response_source="mcp",
                cost_breached=cost_breached,
                confidence_breached=False,
                hallucination_breached=False,
                fallback_used=False,
                fallback_reason="cost_breached" if cost_breached else None,
            )
            return ExecutionResult(response=mcp_result, decision=decision, mcp_span=mcp_span)

        reason_parts: list[str] = []
        if confidence_breached:
            reason_parts.append("low_confidence")
        if hallucination_breached:
            reason_parts.append("high_hallucination")
        fallback_reason = "+".join(reason_parts) if reason_parts else "policy_breach"

        if deterministic_fallback is None:
            decision = ExecutionDecision(
                tier=tier.name,
                accepted=False,
                response_source="none",
                cost_breached=cost_breached,
                confidence_breached=confidence_breached,
                hallucination_breached=hallucination_breached,
                fallback_used=False,
                fallback_reason=fallback_reason,
            )
            return ExecutionResult(response=None, decision=decision, mcp_span=mcp_span)

        fallback_response = await deterministic_fallback(prompt=prompt, model=model, **call_kwargs)
        _, fallback_span = await self.interceptor.intercept_model_call(
            model=f"{model}:deterministic_fallback",
            prompt=prompt,
            response=fallback_response,
            tool_name=tool_name,
            confidence=1.0,
            fallback_used=True,
            gate_blocked=True,
            fallback_type="deterministic",
            fallback_reason=fallback_reason,
            return_span=True,
        )

        decision = ExecutionDecision(
            tier=tier.name,
            accepted=False,
            response_source="deterministic_fallback",
            cost_breached=cost_breached,
            confidence_breached=confidence_breached,
            hallucination_breached=hallucination_breached,
            fallback_used=True,
            fallback_reason=fallback_reason,
        )
        return ExecutionResult(response=fallback_response, decision=decision, mcp_span=mcp_span, fallback_span=fallback_span)

    @staticmethod
    def _effective_confidence(*, explicit_confidence: Optional[float], span: TraceContext) -> Optional[float]:
        """Resolve confidence using observability-first semantics.

        Hallucination risk is already computed from all available hallucination
        signals in MCP Observatory (grounding, self-consistency, verifier,
        numeric variance, tool-claim mismatch). If direct confidence is missing,
        infer confidence as (1 - hallucination_risk).
        """
        if explicit_confidence is not None:
            return clamp01(explicit_confidence)
        if span.confidence is not None:
            return clamp01(span.confidence)
        if span.hallucination_risk_score is not None:
            return clamp01(1.0 - span.hallucination_risk_score)
        return None


__all__ = [
    "ExecutionDecision",
    "ExecutionResult",
    "ExecutionTier",
    "TieredExecutionConfig",
    "TieredExecutionEngine",
]
