"""High-level instrumentation helpers for MCP servers."""

from __future__ import annotations

from typing import Optional

from .core.interceptor import MCPInterceptor
from .core.tracer import Tracer
from .exporters.base import Exporter
from .hallucination.config import HallucinationConfig
from .hallucination.signals import Verifier


def instrument(
    service_name: str,
    *,
    exporter: Optional[Exporter] = None,
    hallucination_config: Optional[HallucinationConfig] = None,
    verifier: Optional[Verifier] = None,
) -> MCPInterceptor:
    """Create a ready-to-use interceptor for an MCP server."""
    tracer = Tracer(service=service_name)
    return MCPInterceptor(
        tracer=tracer,
        exporter=exporter,
        hallucination_config=hallucination_config,
        verifier=verifier,
    )


# Backward-compatible alias.
instrument_mcp_server = instrument
