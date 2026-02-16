"""Async shadow lane evaluation hook."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional

from ..core.context import TraceContext
from ..exporters.base import Exporter
from .compare import disagreement_score, numeric_variance

ShadowCallable = Callable[[str], Awaitable[str]]


async def run_shadow_lane(
    *,
    parent_context: TraceContext,
    primary_answer: str,
    shadow_answer: Optional[str],
    exporter: Optional[Exporter] = None,
) -> TraceContext:
    """Compute disagreement metrics and optionally export a shadow span."""
    span = TraceContext(
        service=parent_context.service,
        model=parent_context.model,
        tool_name=parent_context.tool_name,
        trace_id=parent_context.trace_id,
        parent_span_id=parent_context.span_id,
        is_shadow=True,
        shadow_parent_trace_id=parent_context.trace_id,
    )
    answer = shadow_answer or ""
    span.shadow_disagreement_score = disagreement_score(primary_answer, answer)
    span.shadow_numeric_variance = numeric_variance(primary_answer, answer)
    span.finish()
    if exporter is not None:
        await exporter.export(span)
    return span


def schedule_shadow_lane(**kwargs: object) -> asyncio.Task:
    """Schedule and return a detached shadow lane task."""
    return asyncio.create_task(run_shadow_lane(**kwargs))
