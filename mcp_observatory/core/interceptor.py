"""Interception utilities for instrumenting model calls in MCP servers."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from ..cost.pricing import estimate_cost
from ..cost.tokenizer import estimate_tokens
from ..exporters.base import Exporter
from .tracer import Tracer

ModelCallable = Callable[..., Awaitable[Any]]


class MCPInterceptor:
    """Intercepts async model calls to collect trace and cost metrics."""

    def __init__(self, tracer: Tracer, exporter: Optional[Exporter] = None) -> None:
        self.tracer = tracer
        self.exporter = exporter

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
        **call_kwargs: Any,
    ) -> Any:
        """Record telemetry around a model call.

        Supports two usage patterns:
        1) Pass ``call`` (an async callable). The interceptor executes it.
        2) Pass an already-computed ``response`` (manual instrumentation mode).

        Args:
            model: Model identifier.
            prompt: Prompt or request body.
            response: Optional precomputed response payload.
            call: Optional async callable that performs the model request.
            tool_name: MCP tool name associated with the call.
            retries: Retry count used for the request.
            fallback_used: Whether a fallback model/strategy was used.
            confidence: Optional confidence score for the response.
            call_kwargs: Keyword arguments forwarded to ``call`` when provided.
        """
        if call is None and response is None:
            raise ValueError("Either `call` or `response` must be provided.")

        span = self.tracer.start_span(model=model, tool_name=tool_name)
        span.prompt_tokens = estimate_tokens(prompt)
        span.retries = retries
        span.fallback_used = fallback_used
        span.confidence = confidence

        try:
            result = response
            if call is not None:
                result = await call(prompt=prompt, model=model, **call_kwargs)

            response_text = self._extract_response_text(result)
            span.completion_tokens = estimate_tokens(response_text)
            span.cost_usd = estimate_cost(model, span.prompt_tokens, span.completion_tokens)
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
