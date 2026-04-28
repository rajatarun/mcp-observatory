"""Tracer implementation for MCP Observatory."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator, Optional
from uuid import uuid4

from .context import TraceContext


class Tracer:
    """Simple tracer that creates and finalizes :class:`TraceContext` spans."""

    def __init__(self, service: str) -> None:
        self.service = service

    def start_span(
        self,
        *,
        model: Optional[str] = None,
        tool_name: Optional[str] = None,
        parent: Optional[TraceContext] = None,
    ) -> TraceContext:
        """Create a new span context aligned to the schema."""
        return TraceContext(
            service=self.service,
            model=model,
            tool_name=tool_name,
            trace_id=parent.trace_id if parent else str(uuid4()),
            parent_span_id=parent.span_id if parent else None,
        )

    def end_span(self, span: TraceContext) -> TraceContext:
        """Mark a span as finished."""
        span.finish()
        return span

    @contextmanager
    def span(
        self,
        *,
        model: Optional[str] = None,
        tool_name: Optional[str] = None,
        parent: Optional[TraceContext] = None,
    ) -> Generator[TraceContext, None, None]:
        """Context-manager helper for creating spans around operations."""
        span = self.start_span(model=model, tool_name=tool_name, parent=parent)
        try:
            yield span
        finally:
            self.end_span(span)
