"""High-level instrumentation helpers for MCP servers."""

from __future__ import annotations

from typing import Optional

from .core.interceptor import MCPInterceptor
from .core.tracer import Tracer
from .exporters.base import Exporter


def instrument(service_name: str, *, exporter: Optional[Exporter] = None) -> MCPInterceptor:
    """Create a ready-to-use interceptor for an MCP server.

    Args:
        service_name: Logical service name for traces.
        exporter: Optional exporter instance for shipping telemetry.

    Returns:
        Configured :class:`~mcp_observatory.core.interceptor.MCPInterceptor`.
    """
    tracer = Tracer(service=service_name)
    return MCPInterceptor(tracer=tracer, exporter=exporter)


# Backward-compatible alias.
instrument_mcp_server = instrument
