"""Wrapper API for observability-first agent/model invocation control."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from ..cost.pricing import estimate_cost
from ..cost.tokenizer import estimate_tokens
from ..exporters.base import Exporter
from .context import TraceContext
from .tracer import Tracer

InvokeCallable = Callable[..., Any]
DecisionCallable = Callable[[TraceContext, Any], "WrapperDecision"]


@dataclass(frozen=True)
class WrapperDecision:
    """Decision envelope emitted by wrapper policy evaluation."""

    action: str
    reason: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WrapperPolicy:
    """Simple threshold policy for wrapper output decisioning."""

    max_cost_usd: float = 0.25
    max_latency_ms: float = 8_000.0

    def decide(self, span: TraceContext, output: Any) -> WrapperDecision:
        if span.end_time is None:
            raise ValueError("Span must be completed before decisioning.")

        latency_ms = (span.end_time - span.start_time).total_seconds() * 1000.0
        output_text = _to_text(output)

        if not output_text.strip():
            return WrapperDecision(action="block", reason="empty_output")
        if span.cost_usd > self.max_cost_usd:
            return WrapperDecision(
                action="review",
                reason="cost_budget_exceeded",
                metadata={"cost_usd": span.cost_usd, "max_cost_usd": self.max_cost_usd},
            )
        if latency_ms > self.max_latency_ms:
            return WrapperDecision(
                action="review",
                reason="latency_budget_exceeded",
                metadata={"latency_ms": round(latency_ms, 2), "max_latency_ms": self.max_latency_ms},
            )
        return WrapperDecision(action="allow", reason="within_budget")


@dataclass(frozen=True)
class WrapperResult:
    """Structured wrapper output with metrics and policy decision."""

    output: Any
    span: TraceContext
    decision: WrapperDecision
    shadow_output: Any = None
    shadow_span: Optional[TraceContext] = None


class InvocationWrapperAPI:
    """Observability wrapper for agent/model inputs and outputs.

    This API accepts either an *agent* or *model* source invocation,
    records telemetry metrics in a trace span, and emits a policy decision
    that can be consumed by downstream execution logic.
    """

    def __init__(
        self,
        tracer: Tracer,
        exporter: Optional[Exporter] = None,
        *,
        policy: Optional[WrapperPolicy] = None,
        decision_fn: Optional[DecisionCallable] = None,
    ) -> None:
        self.tracer = tracer
        self.exporter = exporter
        self.policy = policy or WrapperPolicy()
        self.decision_fn = decision_fn

    async def invoke(
        self,
        *,
        source: str,
        model: str,
        prompt: str,
        input_payload: Any,
        call: InvokeCallable,
        dual_invoke: bool = False,
        shadow_source: Optional[str] = None,
        shadow_model: Optional[str] = None,
        shadow_prompt: Optional[str] = None,
        shadow_input_payload: Any = None,
        shadow_call: Optional[InvokeCallable] = None,
        shadow_call_kwargs: Optional[dict[str, Any]] = None,
        shadow_agent_params: Optional[dict[str, Any]] = None,
        shadow_model_params: Optional[dict[str, Any]] = None,
        **call_kwargs: Any,
    ) -> WrapperResult:
        """Invoke any callable through the observability wrapper.

        Args:
            source: Invocation source, usually ``"agent"`` or ``"model"``.
            model: Logical model identifier used for token/cost estimation.
            prompt: Prompt or request text.
            input_payload: Structured request payload to hash/store in span.
            call: Sync or async callable to execute.
            dual_invoke: When ``True``, execute a second shadow invocation for comparison.
            shadow_source: Shadow invocation source; defaults to primary source.
            shadow_model: Shadow model; defaults to primary model.
            shadow_prompt: Shadow prompt; defaults to primary prompt.
            shadow_input_payload: Shadow payload; defaults to primary payload.
            shadow_call: Shadow callable; defaults to primary callable.
            shadow_call_kwargs: Shadow callable kwargs; defaults to primary kwargs.
            shadow_agent_params: Optional shadow-agent parameter envelope for measurement.
            shadow_model_params: Optional shadow-model parameter envelope for measurement.
            **call_kwargs: Arguments forwarded to ``call``.
        """
        output, span = await self._execute_with_span(
            source=source,
            model=model,
            prompt=prompt,
            input_payload=input_payload,
            call=call,
            call_kwargs=call_kwargs,
        )

        shadow_output: Any = None
        shadow_span: Optional[TraceContext] = None

        if dual_invoke:
            shadow_payload = input_payload if shadow_input_payload is None else shadow_input_payload
            if shadow_input_payload is None and (shadow_agent_params is not None or shadow_model_params is not None):
                shadow_payload = {
                    "agent_params": shadow_agent_params or {},
                    "model_params": shadow_model_params or {},
                }

            shadow_output, shadow_span = await self._execute_with_span(
                source=shadow_source or source,
                model=shadow_model or model,
                prompt=shadow_prompt or prompt,
                input_payload=shadow_payload,
                call=shadow_call or call,
                call_kwargs=shadow_call_kwargs if shadow_call_kwargs is not None else call_kwargs,
                parent=span,
                is_shadow=True,
            )
            span.shadow_disagreement_score = _disagreement_score(output, shadow_output)
            span.shadow_numeric_variance = _numeric_variance(output, shadow_output)

        decision = self._decide(span=span, output=output)
        span.policy_decision = decision.action
        if decision.reason:
            span.fallback_reason = decision.reason

        if self.exporter:
            await self.exporter.export(span)

        return WrapperResult(
            output=output,
            span=span,
            decision=decision,
            shadow_output=shadow_output,
            shadow_span=shadow_span,
        )

    async def _execute_with_span(
        self,
        *,
        source: str,
        model: str,
        prompt: str,
        input_payload: Any,
        call: InvokeCallable,
        call_kwargs: dict[str, Any],
        parent: Optional[TraceContext] = None,
        is_shadow: bool = False,
    ) -> tuple[Any, TraceContext]:
        span = self.tracer.start_span(model=model, parent=parent)
        span.method = f"wrapper/{source}"
        span.is_shadow = is_shadow
        span.shadow_parent_trace_id = parent.trace_id if parent else None
        span.prompt_size_chars = len(prompt)
        span.prompt_tokens = estimate_tokens(prompt)
        span.prompt_hash = _sha256_hex(prompt)
        span.normalized_prompt_hash = _sha256_hex(_to_text(input_payload))
        span.tool_args_hash = _sha256_hex(_to_json(input_payload))

        output = call(**call_kwargs)
        if isinstance(output, Awaitable):
            output = await output

        output_text = _to_text(output)
        span.answer_hash = _sha256_hex(output_text)
        span.completion_tokens = estimate_tokens(output_text)
        span.cost_usd = estimate_cost(model, span.prompt_tokens, span.completion_tokens)
        self.tracer.end_span(span)
        return output, span

    def _decide(self, *, span: TraceContext, output: Any) -> WrapperDecision:
        if self.decision_fn is not None:
            return self.decision_fn(span, output)
        return self.policy.decide(span, output)


def _to_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _to_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list, tuple)):
        return _to_json(value)
    return str(value)


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _disagreement_score(primary_output: Any, shadow_output: Any) -> float:
    primary_text = _to_text(primary_output)
    shadow_text = _to_text(shadow_output)
    if not primary_text and not shadow_text:
        return 0.0
    if primary_text == shadow_text:
        return 0.0

    primary_tokens = set(primary_text.lower().split())
    shadow_tokens = set(shadow_text.lower().split())
    union = primary_tokens | shadow_tokens
    if not union:
        return 0.0
    intersection = primary_tokens & shadow_tokens
    return round(1.0 - (len(intersection) / len(union)), 6)


def _numeric_variance(primary_output: Any, shadow_output: Any) -> Optional[float]:
    primary_vals = _extract_numbers(_to_text(primary_output))
    shadow_vals = _extract_numbers(_to_text(shadow_output))
    if not primary_vals or not shadow_vals:
        return None

    length = min(len(primary_vals), len(shadow_vals))
    if length == 0:
        return None

    deltas = [abs(primary_vals[idx] - shadow_vals[idx]) for idx in range(length)]
    return round(sum(deltas) / float(length), 6)


def _extract_numbers(text: str) -> list[float]:
    out: list[float] = []
    token = ""
    for char in text:
        if char.isdigit() or (char in {".", "-"} and (not token or token == "-")):
            token += char
            continue
        if token:
            try:
                out.append(float(token))
            except ValueError:
                pass
            token = ""
    if token:
        try:
            out.append(float(token))
        except ValueError:
            pass
    return out
