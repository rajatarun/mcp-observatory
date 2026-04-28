"""Interception utilities for model and tool execution in MCP servers."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional
from uuid import uuid4

from ..cost.pricing import estimate_cost
from ..cost.tokenizer import estimate_tokens
from ..exporters.base import Exporter
from ..fallback.router import FallbackRouter
from ..fallback.templates import review_response_template
from ..hallucination.config import HallucinationConfig
from ..hallucination.scoring import compute_hallucination_risk_score, risk_level_for_score
from ..hallucination.signals import (
    LocalHeuristicVerifier,
    Verifier,
    compute_grounding_score,
    compute_numeric_variance_score,
    compute_self_consistency_score,
    detect_tool_claim_mismatch,
    normalize_text,
    sha256_hash,
)
from ..policy.engine import PolicyConfig, PolicyEngine
from ..policy.registry import DEFAULT_REGISTRY, ToolRegistry
from ..policy.types import Decision
from ..risk.vector import compute_risk_vector
from ..shadow.lane import schedule_shadow_lane
from ..token.issuer import TokenIssuer
from ..token.verifier import TokenVerifier
from ..utils.hashing import args_hash
from .tracer import Tracer

ModelCallable = Callable[..., Awaitable[Any]]
ToolCallable = Callable[..., Awaitable[Any]]

UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b")
TIMESTAMP_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?\b")
NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")


@dataclass
class V2Config:
    """Configuration for v2 risk-bound execution control plane."""

    enabled: bool = True
    shadow_for_high_risk: bool = True


class MCPInterceptor:
    """Intercepts async model calls and tool executions."""

    def __init__(
        self,
        tracer: Tracer,
        exporter: Optional[Exporter] = None,
        *,
        hallucination_config: Optional[HallucinationConfig] = None,
        verifier: Optional[Verifier] = None,
        tool_registry: Optional[ToolRegistry] = None,
        policy_engine: Optional[PolicyEngine] = None,
        token_issuer: Optional[TokenIssuer] = None,
        token_verifier: Optional[TokenVerifier] = None,
        fallback_router: Optional[FallbackRouter] = None,
        v2_config: Optional[V2Config] = None,
    ) -> None:
        self.tracer = tracer
        self.exporter = exporter
        self.hallucination_config = hallucination_config or HallucinationConfig()
        self.verifier = verifier or LocalHeuristicVerifier()
        self.tool_registry = tool_registry or DEFAULT_REGISTRY
        self.policy_engine = policy_engine or PolicyEngine(PolicyConfig())
        self.token_issuer = token_issuer or TokenIssuer()
        self.token_verifier = token_verifier or TokenVerifier()
        self.fallback_router = fallback_router or FallbackRouter()
        self.v2_config = v2_config or V2Config()

    async def intercept_request(self, method: str, **kwargs: Any) -> Any:
        """General interception entrypoint."""
        if method == "tools/call":
            return await self.intercept_tool_call(**kwargs)
        return await self.intercept_model_call(**kwargs)

    async def intercept_tool_call(
        self,
        *,
        tool_name: str,
        tool_args: dict,
        tool_fn: ToolCallable,
        model_answer: str,
        tool_result_summary: Optional[str],
        retrieved_context: Optional[str],
        prompt_template_id: Optional[str],
        prompt: str = "",
        secondary_answer: Optional[str] = None,
        previous_prompt_hash: Optional[str] = None,
        request_id: Optional[str] = None,
        session_id: Optional[str] = None,
        shadow_answer: Optional[str] = None,
    ) -> Any:
        """Run end-to-end v2 control plane for a tool invocation."""
        ctx = self.tracer.start_span(model="tool-execution", tool_name=tool_name)
        ctx.request_id = request_id or str(uuid4())
        ctx.session_id = session_id
        ctx.method = "tools/call"
        ctx.prompt_template_id = prompt_template_id
        ctx.tool_args_hash = args_hash(tool_args)

        rv = compute_risk_vector(
            prompt=prompt,
            answer=model_answer,
            retrieved_context=retrieved_context,
            secondary_answer=secondary_answer,
            tool_result_summary=tool_result_summary,
            previous_prompt_hash=previous_prompt_hash,
        )
        ctx.prompt_hash = rv.prompt_hash
        ctx.grounding_risk = rv.grounding_risk
        ctx.self_consistency_risk = rv.self_consistency_risk
        ctx.numeric_instability_risk = rv.numeric_instability_risk
        ctx.tool_mismatch_risk = rv.tool_mismatch_risk
        ctx.drift_risk = rv.drift_risk
        ctx.verifier_score = 1.0 - rv.verifier_risk
        ctx.composite_risk_score = rv.composite_risk_score
        ctx.composite_risk_level = rv.composite_risk_level
        ctx.risk_tier = rv.composite_risk_level

        profile = self.tool_registry.get(tool_name)
        ctx.tool_criticality = profile.criticality.value.lower()
        policy = self.policy_engine.evaluate(
            tool_profile=profile,
            composite_risk_score=rv.composite_risk_score,
            risk_tier=rv.composite_risk_level,
            context={"tool_name": tool_name},
        )
        ctx.policy_decision = policy.decision.value
        ctx.policy_id = policy.policy_id
        ctx.policy_version = policy.policy_version

        if policy.decision == Decision.REVIEW:
            ctx.fallback_used = True
            ctx.fallback_type = "human_review"
            ctx.fallback_reason = policy.reason
            result: Any = review_response_template(tool_name, policy.reason)
        elif policy.decision == Decision.BLOCK:
            ctx.fallback_used = True
            ctx.fallback_reason = policy.reason
            result, fallback_type = await self.fallback_router.route(tool_name=tool_name, tool_args=tool_args, reason=policy.reason)
            ctx.fallback_type = fallback_type
        else:
            token: Optional[str] = None
            if policy.require_token:
                issued = self.token_issuer.issue(
                    trace_id=ctx.trace_id,
                    tool_name=tool_name,
                    tool_args_hash=ctx.tool_args_hash,
                    decision=policy.decision.value,
                    composite_risk_score=rv.composite_risk_score,
                )
                token = issued.token
                ctx.exec_token_id = issued.token_id
                ctx.exec_token_hash = issued.token_hash
                ctx.exec_token_ttl_ms = issued.ttl_ms

            if policy.require_token and token is not None:
                verification = self.token_verifier.verify(token, tool_name=tool_name, tool_args_hash=ctx.tool_args_hash)
                ctx.exec_token_verified = verification.valid
                if not verification.valid:
                    ctx.fallback_used = True
                    ctx.fallback_reason = verification.reason
                    result, fallback_type = await self.fallback_router.route(
                        tool_name=tool_name,
                        tool_args=tool_args,
                        reason=verification.reason,
                    )
                    ctx.fallback_type = fallback_type
                else:
                    result = await tool_fn(**tool_args)
            else:
                ctx.exec_token_verified = None
                result = await tool_fn(**tool_args)

        self.tracer.end_span(ctx)
        if self.exporter:
            await self.exporter.export(ctx)

        if self.v2_config.shadow_for_high_risk and ctx.composite_risk_level == "high":
            try:
                schedule_shadow_lane(
                    parent_context=ctx,
                    primary_answer=model_answer,
                    shadow_answer=shadow_answer,
                    exporter=self.exporter,
                )
            except RuntimeError:
                pass

        return result

    async def intercept_model_call(
        self,
        *,
        model: str,
        prompt: str,
        response: Any = None,
        call: Optional[ModelCallable] = None,
        tool_name: Optional[str] = None,
        retries: int = 0,
        fallback_used: bool = False,
        confidence: Optional[float] = None,
        risk_tier: Optional[str] = None,
        prompt_template_id: Optional[str] = None,
        is_shadow: bool = False,
        shadow_parent_trace_id: Optional[str] = None,
        gate_blocked: Optional[bool] = None,
        confidence_gate_threshold: Optional[float] = None,
        fallback_type: Optional[str] = None,
        fallback_reason: Optional[str] = None,
        secondary_response: Any = None,
        retrieved_context: Optional[str] = None,
        tool_result_summary: Optional[str] = None,
        return_span: bool = False,
        **call_kwargs: Any,
    ) -> Any:
        """Record telemetry around a model call (v1-compatible path)."""
        if call is None and response is None:
            raise ValueError("Either `call` or `response` must be provided.")

        span = self.tracer.start_span(model=model, tool_name=tool_name)
        span.prompt_tokens = estimate_tokens(prompt)
        span.retries = retries
        span.fallback_used = fallback_used
        span.confidence = confidence
        span.risk_tier = risk_tier
        span.prompt_template_id = prompt_template_id
        span.prompt_size_chars = len(prompt)
        span.prompt_hash = self._hash_text(prompt)
        normalized_prompt = self._normalize_prompt(prompt)
        span.normalized_prompt_hash = self._hash_text(normalized_prompt)
        span.is_shadow = is_shadow
        span.shadow_parent_trace_id = shadow_parent_trace_id if is_shadow else None
        span.gate_blocked = (
            gate_blocked
            if gate_blocked is not None
            else (confidence is not None and confidence_gate_threshold is not None and confidence < confidence_gate_threshold)
        )
        span.fallback_type = fallback_type
        span.fallback_reason = fallback_reason

        try:
            result = response
            if call is not None:
                result = await call(prompt=prompt, model=model, **call_kwargs)

            response_text = self._extract_response_text(result)
            secondary_text = self._extract_response_text(secondary_response) if secondary_response is not None else None
            span.completion_tokens = estimate_tokens(response_text)
            span.cost_usd = estimate_cost(model, span.prompt_tokens, span.completion_tokens)

            await self._populate_hallucination_fields(
                prompt=prompt,
                answer=response_text,
                secondary_answer=secondary_text,
                retrieved_context=retrieved_context,
                tool_result_summary=tool_result_summary,
                span=span,
            )

            self.tracer.end_span(span)
            if self.exporter:
                await self.exporter.export(span)
            if return_span:
                return result, span
            return result
        except Exception:
            span.cost_usd = estimate_cost(model, span.prompt_tokens, 0)
            self.tracer.end_span(span)
            if self.exporter:
                await self.exporter.export(span)
            raise

    async def _populate_hallucination_fields(
        self,
        *,
        prompt: str,
        answer: str,
        secondary_answer: Optional[str],
        retrieved_context: Optional[str],
        tool_result_summary: Optional[str],
        span: Any,
    ) -> None:
        config = self.hallucination_config

        if config.enable_prompt_hash:
            span.prompt_hash = sha256_hash(normalize_text(prompt))
            span.answer_hash = sha256_hash(normalize_text(answer))

        if config.enable_grounding_score:
            span.grounding_score = compute_grounding_score(answer, retrieved_context)

        if config.enable_self_consistency:
            if config.self_consistency_mode in {"inline", "shadow"}:
                span.self_consistency_score = compute_self_consistency_score(answer, secondary_answer)

        if config.enable_numeric_variance:
            span.numeric_variance_score = compute_numeric_variance_score(answer, secondary_answer)

        if config.enable_tool_claim_mismatch:
            span.tool_claim_mismatch = detect_tool_claim_mismatch(answer, tool_result_summary)

        if config.enable_verifier:
            span.verifier_score, _reason = await self.verifier.score(prompt, answer, context=retrieved_context)

        span.hallucination_risk_score = compute_hallucination_risk_score(
            grounding_score=span.grounding_score,
            self_consistency_score=span.self_consistency_score,
            verifier_score=span.verifier_score,
            numeric_variance_score=span.numeric_variance_score,
            tool_claim_mismatch=span.tool_claim_mismatch,
        )
        span.hallucination_risk_level = risk_level_for_score(span.hallucination_risk_score)

    @staticmethod
    def _extract_response_text(response: Any) -> str:
        if isinstance(response, str):
            return response
        if isinstance(response, dict):
            for key in ("text", "content", "output", "message"):
                value = response.get(key)
                if isinstance(value, str):
                    return value
        return str(response)

    @staticmethod
    def _hash_text(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @classmethod
    def _normalize_prompt(cls, prompt: str) -> str:
        normalized = UUID_RE.sub("<uuid>", prompt)
        normalized = TIMESTAMP_RE.sub("<timestamp>", normalized)
        normalized = NUMBER_RE.sub("<number>", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip().lower()
        return normalized
