"""Wrapper API for observability-first agent/model invocation control."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from ..cost.pricing import estimate_cost
from ..cost.tokenizer import estimate_tokens
from ..exporters.base import Exporter
from ..hallucination.scoring import compute_hallucination_risk_score, risk_level_for_score
from ..hallucination.signals import (
    LocalHeuristicVerifier,
    compute_grounding_score,
    compute_numeric_variance_score,
    compute_self_consistency_score,
    detect_tool_claim_mismatch,
)
from ..risk import scoring as risk_scoring
from ..risk import signals as risk_signals
from .context import TraceContext
from .tracer import Tracer

InvokeCallable = Callable[..., Any]
DecisionCallable = Callable[[TraceContext, Any], "WrapperDecision"]


@dataclass(frozen=True)
class WrapperDecision:
    """Decision envelope emitted by wrapper policy evaluation.

    Attributes:
        action: Outcome directive. One of:
            - ``"allow"``  — output is within all budgets; proceed normally.
            - ``"review"`` — a budget threshold was exceeded; human review recommended.
            - ``"block"``  — output is empty or otherwise unusable; discard it.
        reason: Machine-readable cause for the decision. Common values:
            ``"within_budget"``, ``"empty_output"``, ``"cost_budget_exceeded"``,
            ``"latency_budget_exceeded"``.  ``None`` when no reason applies.
        metadata: Supplementary key/value data explaining the decision.
            Populated only for ``"review"`` actions, e.g.
            ``{"cost_usd": 0.31, "max_cost_usd": 0.25}``.
    """

    action: str
    reason: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WrapperPolicy:
    """Simple threshold policy for wrapper output decisioning.

    Attributes:
        max_cost_usd: Maximum acceptable cost in USD per invocation.
            Invocations that exceed this value receive a ``"review"`` decision.
            Default: ``0.25``.
        max_latency_ms: Maximum acceptable wall-clock latency in milliseconds.
            Invocations that exceed this value receive a ``"review"`` decision.
            Default: ``8000.0``.
    """

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
    """Structured wrapper output with metrics and policy decision.

    Attributes:
        output: Raw return value from the primary ``call`` callable.
        span: Completed :class:`TraceContext` for the primary invocation.
            The span carries all computed metrics after ``invoke()`` returns:

            *Telemetry*
              ``prompt_tokens``, ``completion_tokens``, ``cost_usd``,
              ``prompt_hash``, ``normalized_prompt_hash``, ``answer_hash``,
              ``tool_args_hash``, ``prompt_size_chars``, ``method``,
              ``is_shadow``, ``start_time``, ``end_time``.

            *Hallucination signals*
              ``grounding_score`` — Jaccard overlap between answer and
              retrieved context (``None`` if no context supplied).
              ``self_consistency_score`` — token-overlap between primary and
              shadow answer (``None`` if no shadow).
              ``numeric_variance_score`` — relative numeric drift between
              primary and shadow answer (or internal spread if no shadow).
              ``tool_claim_mismatch`` — ``True`` when the model claims success
              but the tool result indicates failure (``None`` if no tool summary).
              ``verifier_score`` — local heuristic goodness score in [0, 1].

            *Hallucination composite*
              ``hallucination_risk_score`` — weighted composite in [0, 1].
              ``hallucination_risk_level`` — ``"low"`` / ``"medium"`` / ``"high"``.

            *Risk signals*
              ``drift_risk`` — ``1.0`` if prompt hash changed, else ``0.0``.
              ``grounding_risk`` — inverse grounding overlap in [0, 1].
              ``self_consistency_risk`` — inverse consistency in [0, 1].
              ``numeric_instability_risk`` — numeric drift in [0, 1].
              ``tool_mismatch_risk`` — ``1.0`` on tool/answer mismatch, else ``0.0``.

            *Risk composite*
              ``composite_risk_score`` — renormalised weighted composite in [0, 1].
              ``composite_risk_level`` — ``"low"`` / ``"medium"`` / ``"high"``.

            *Shadow comparison* (set only when ``dual_invoke=True``)
              ``shadow_disagreement_score`` — Jaccard-based token disagreement.
              ``shadow_numeric_variance`` — mean absolute numeric delta.

            *Policy*
              ``policy_decision`` — mirrors ``decision.action``.
              ``fallback_reason`` — mirrors ``decision.reason``.

        decision: :class:`WrapperDecision` produced by the active policy.
        shadow_output: Raw return value from the shadow ``call`` callable, or
            ``None`` when ``dual_invoke=False``.
        shadow_span: Completed :class:`TraceContext` for the shadow invocation,
            or ``None`` when ``dual_invoke=False``.
    """

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

    Args:
        tracer: :class:`~mcp_observatory.core.tracer.Tracer` used to create
            and finish trace spans.
        exporter: Optional :class:`~mcp_observatory.exporters.base.Exporter`
            that receives the completed span after each invocation.
        policy: :class:`WrapperPolicy` that decides whether to allow, review,
            or block the output based on cost/latency budgets.  Defaults to
            ``WrapperPolicy()`` with 0.25 USD and 8 000 ms limits.
        decision_fn: Custom callable with signature
            ``(span: TraceContext, output: Any) -> WrapperDecision`` that
            overrides ``policy`` entirely when provided.
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
        retrieved_context: Optional[str] = None,
        tool_result_summary: Optional[str] = None,
        previous_prompt_hash: Optional[str] = None,
        **call_kwargs: Any,
    ) -> WrapperResult:
        """Invoke any callable through the observability wrapper.

        Executes ``call(**call_kwargs)``, records a telemetry span, computes
        all hallucination and risk metrics, applies the active policy, and
        returns a :class:`WrapperResult` containing the raw output, the
        populated span, and the policy decision.

        Args:
            source: Invocation source label stored on the span method field,
                e.g. ``"agent"`` or ``"model"``.
            model: Logical model identifier used for token and cost estimation
                (e.g. ``"gpt-4o"``).
            prompt: Full prompt or request text sent to the model/agent.
                Used for token estimation, hashing, and verifier scoring.
            input_payload: Structured request payload (dict, list, or string).
                Hashed and stored on the span; not forwarded to ``call``.
            call: Sync or async callable to execute.  Receives ``**call_kwargs``
                as keyword arguments.
            dual_invoke: When ``True``, execute a second *shadow* invocation
                immediately after the primary one.  The shadow output is used
                as the secondary answer for self-consistency and numeric
                variance metrics.  Default: ``False``.
            shadow_source: Source label for the shadow span.
                Defaults to ``source``.
            shadow_model: Model identifier for the shadow invocation.
                Defaults to ``model``.
            shadow_prompt: Prompt for the shadow invocation.
                Defaults to ``prompt``.
            shadow_input_payload: Payload for the shadow invocation.
                Defaults to ``input_payload`` (or the merged agent/model params
                dict when ``shadow_agent_params`` / ``shadow_model_params`` are
                provided).
            shadow_call: Callable for the shadow invocation.
                Defaults to ``call``.
            shadow_call_kwargs: Keyword arguments forwarded to ``shadow_call``.
                Defaults to the primary ``call_kwargs``.
            shadow_agent_params: Agent parameter envelope used to build the
                shadow payload when ``shadow_input_payload`` is not supplied.
            shadow_model_params: Model parameter envelope used to build the
                shadow payload when ``shadow_input_payload`` is not supplied.
            retrieved_context: Optional text retrieved from a knowledge source
                (e.g. RAG context).  Used to compute ``grounding_score`` and
                ``grounding_risk`` on the span.
            tool_result_summary: Optional string summarising tool execution
                results.  Used to detect ``tool_claim_mismatch`` and compute
                ``tool_mismatch_risk``.
            previous_prompt_hash: SHA-256 hex digest of the previous
                invocation's prompt (as returned in ``span.prompt_hash``).
                Used to compute ``drift_risk``; omit for the first call in a
                session.
            **call_kwargs: Additional keyword arguments forwarded verbatim to
                ``call``.

        Returns:
            :class:`WrapperResult` with the following fields populated:

            - ``output`` — raw return value of ``call``.
            - ``span`` — completed :class:`TraceContext` with all telemetry,
              hallucination signals, risk signals, and composite scores.
            - ``decision`` — :class:`WrapperDecision` with ``action``,
              ``reason``, and optional ``metadata``.
            - ``shadow_output`` — raw return value of the shadow callable
              (``None`` if ``dual_invoke=False``).
            - ``shadow_span`` — completed :class:`TraceContext` for the shadow
              invocation (``None`` if ``dual_invoke=False``).
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

        await self._populate_metrics(
            span=span,
            output=output,
            prompt=prompt,
            secondary_output=shadow_output,
            retrieved_context=retrieved_context,
            tool_result_summary=tool_result_summary,
            previous_prompt_hash=previous_prompt_hash,
        )

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

    async def _populate_metrics(
        self,
        *,
        span: TraceContext,
        output: Any,
        prompt: str,
        secondary_output: Any = None,
        retrieved_context: Optional[str] = None,
        tool_result_summary: Optional[str] = None,
        previous_prompt_hash: Optional[str] = None,
    ) -> None:
        """Compute and populate all hallucination and risk metrics on the span."""
        answer = _to_text(output)
        secondary_answer: Optional[str] = _to_text(secondary_output) if secondary_output is not None else None

        # --- Hallucination signals ---
        span.grounding_score = compute_grounding_score(answer, retrieved_context)
        span.self_consistency_score = compute_self_consistency_score(answer, secondary_answer)
        span.numeric_variance_score = compute_numeric_variance_score(answer, secondary_answer)
        span.tool_claim_mismatch = detect_tool_claim_mismatch(answer, tool_result_summary)

        verifier_score, _ = await LocalHeuristicVerifier().score(prompt, answer, retrieved_context)
        span.verifier_score = verifier_score

        # --- Hallucination composite ---
        span.hallucination_risk_score = compute_hallucination_risk_score(
            grounding_score=span.grounding_score,
            self_consistency_score=span.self_consistency_score,
            verifier_score=span.verifier_score,
            numeric_variance_score=span.numeric_variance_score,
            tool_claim_mismatch=span.tool_claim_mismatch,
        )
        span.hallucination_risk_level = risk_level_for_score(span.hallucination_risk_score)

        # --- Risk signals ---
        span.drift_risk = risk_signals.drift_risk(
            previous_prompt_hash=previous_prompt_hash,
            current_prompt_hash=span.prompt_hash or "",
        )
        span.grounding_risk = risk_signals.grounding_risk(answer, retrieved_context)
        span.self_consistency_risk = risk_signals.self_consistency_risk(answer, secondary_answer)
        span.numeric_instability_risk = risk_signals.numeric_instability_risk(answer, secondary_answer)
        span.tool_mismatch_risk = risk_signals.tool_mismatch_risk(answer, tool_result_summary)

        low_grounding = span.grounding_score is not None and span.grounding_score < 0.10
        _verifier_risk = risk_signals.verifier_risk(answer, low_grounding=low_grounding)

        # --- Composite risk ---
        components = {
            "grounding_risk": span.grounding_risk,
            "self_consistency_risk": span.self_consistency_risk,
            "verifier_risk": _verifier_risk,
            "numeric_instability_risk": span.numeric_instability_risk,
            "tool_mismatch_risk": span.tool_mismatch_risk,
            "drift_risk": span.drift_risk,
        }
        span.composite_risk_score, span.composite_risk_level = risk_scoring.composite_risk_score(components)

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
