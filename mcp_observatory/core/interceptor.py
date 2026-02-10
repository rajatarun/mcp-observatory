"""Interception utilities for instrumenting model calls in MCP servers."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from ..cost.pricing import estimate_cost
from ..cost.tokenizer import estimate_tokens
from ..exporters.base import Exporter
from .metrics import AlertThresholds, MetricsSnapshot, build_alerts, ratio, zeroed_counters
from .tracer import Tracer

ModelCallable = Callable[..., Awaitable[Any]]


class MCPInterceptor:
    """Intercepts async model calls to collect trace and cost metrics."""

    def __init__(self, tracer: Tracer, exporter: Optional[Exporter] = None) -> None:
        self.tracer = tracer
        self.exporter = exporter
        self._metrics = zeroed_counters()

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
        confidence_gate_threshold: Optional[float] = None,
        prompt_diff_score: Optional[float] = None,
        prompt_diff_threshold: float = 0.30,
        shadow_agreement: Optional[bool] = None,
        high_risk_path: bool = False,
        deterministic_fallback_triggered: bool = False,
        is_golden_financial_scenario: bool = False,
        golden_scenario_passed: Optional[bool] = None,
        **call_kwargs: Any,
    ) -> Any:
        """Record telemetry around a model call.

        Supports two usage patterns:
        1) Pass ``call`` (an async callable). The interceptor executes it.
        2) Pass an already-computed ``response`` (manual instrumentation mode).

        Additional metrics support patterns such as prompt-diff detection,
        shadow-model evaluation, confidence-gated execution, and deterministic
        fallbacks for high-risk paths.
        """
        if call is None and response is None:
            raise ValueError("Either `call` or `response` must be provided.")

        span = self.tracer.start_span(model=model, tool_name=tool_name)
        span.prompt_tokens = estimate_tokens(prompt)
        span.retries = retries
        span.fallback_used = fallback_used
        span.confidence = confidence

        self._metrics["total_calls"] += 1
        if retries > 0:
            self._metrics["retry_calls"] += 1
        if fallback_used:
            self._metrics["fallback_calls"] += 1
        if high_risk_path:
            self._metrics["high_risk_calls"] += 1
        if deterministic_fallback_triggered:
            self._metrics["deterministic_fallback_calls"] += 1
        if confidence is not None and confidence_gate_threshold is not None and confidence < confidence_gate_threshold:
            self._metrics["confidence_gate_blocks"] += 1
        if confidence is not None and confidence < 0.5:
            self._metrics["low_confidence_calls"] += 1
        if prompt_diff_score is not None and prompt_diff_score > prompt_diff_threshold:
            self._metrics["prompt_diff_violations"] += 1
        if shadow_agreement is not None:
            self._metrics["shadow_calls"] += 1
            if not shadow_agreement:
                self._metrics["shadow_disagreements"] += 1
        if is_golden_financial_scenario:
            self._metrics["golden_financial_calls"] += 1
            if golden_scenario_passed is False:
                self._metrics["golden_financial_failures"] += 1

        try:
            result = response
            if call is not None:
                result = await call(prompt=prompt, model=model, **call_kwargs)

            response_text = self._extract_response_text(result)
            span.completion_tokens = estimate_tokens(response_text)
            span.cost_usd = estimate_cost(model, span.prompt_tokens, span.completion_tokens)
            self._metrics["total_cost_usd"] += span.cost_usd
            self.tracer.end_span(span)

            if self.exporter:
                await self.exporter.export(span)

            return result
        except Exception:
            span.cost_usd = estimate_cost(model, span.prompt_tokens, 0)
            self._metrics["total_cost_usd"] += span.cost_usd
            self.tracer.end_span(span)
            if self.exporter:
                await self.exporter.export(span)
            raise

    def get_metrics_snapshot(self) -> MetricsSnapshot:
        """Return aggregated decisioning metrics for alerting and dashboards."""
        total = int(self._metrics["total_calls"])
        avg_cost = (self._metrics["total_cost_usd"] / total) if total else 0.0
        return MetricsSnapshot(
            total_calls=total,
            avg_cost_usd=avg_cost,
            fallback_rate=ratio(int(self._metrics["fallback_calls"]), total),
            retry_rate=ratio(int(self._metrics["retry_calls"]), total),
            low_confidence_rate=ratio(int(self._metrics["low_confidence_calls"]), total),
            confidence_gate_block_rate=ratio(int(self._metrics["confidence_gate_blocks"]), total),
            prompt_diff_violation_rate=ratio(int(self._metrics["prompt_diff_violations"]), total),
            shadow_disagreement_rate=ratio(
                int(self._metrics["shadow_disagreements"]), int(self._metrics["shadow_calls"])
            ),
            deterministic_fallback_rate=ratio(int(self._metrics["deterministic_fallback_calls"]), total),
            high_risk_path_rate=ratio(int(self._metrics["high_risk_calls"]), total),
            golden_financial_failure_rate=ratio(
                int(self._metrics["golden_financial_failures"]), int(self._metrics["golden_financial_calls"])
            ),
        )

    def get_active_alerts(self, thresholds: Optional[AlertThresholds] = None) -> list[str]:
        """Evaluate active alerts from current metrics and threshold policy."""
        return build_alerts(self.get_metrics_snapshot(), thresholds or AlertThresholds())

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
