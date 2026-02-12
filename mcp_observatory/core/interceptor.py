"""Interception utilities for instrumenting model calls in MCP servers."""

from __future__ import annotations

import hashlib
import re
from typing import Any, Awaitable, Callable, Optional

from ..cost.pricing import estimate_cost
from ..cost.tokenizer import estimate_tokens
from ..exporters.base import Exporter
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
from .tracer import Tracer

ModelCallable = Callable[..., Awaitable[Any]]

UUID_RE = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\b")
TIMESTAMP_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?\b")
NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")


class MCPInterceptor:
    """Intercepts async model calls to collect trace and cost metrics."""

    def __init__(
        self,
        tracer: Tracer,
        exporter: Optional[Exporter] = None,
        *,
        hallucination_config: Optional[HallucinationConfig] = None,
        verifier: Optional[Verifier] = None,
    ) -> None:
        self.tracer = tracer
        self.exporter = exporter
        self.hallucination_config = hallucination_config or HallucinationConfig()
        self.verifier = verifier or LocalHeuristicVerifier()

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
        **call_kwargs: Any,
    ) -> Any:
        """Record telemetry around a model call."""
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
        """Best-effort extraction of textual content from model responses."""
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
        """Hash text to a stable SHA-256 digest."""
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @classmethod
    def _normalize_prompt(cls, prompt: str) -> str:
        """Normalize prompt by removing UUIDs, timestamps, and numbers."""
        normalized = UUID_RE.sub("<uuid>", prompt)
        normalized = TIMESTAMP_RE.sub("<timestamp>", normalized)
        normalized = NUMBER_RE.sub("<number>", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip().lower()
        return normalized
