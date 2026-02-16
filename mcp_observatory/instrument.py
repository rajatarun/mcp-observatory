"""High-level instrumentation helpers for MCP servers."""

from __future__ import annotations

from typing import Optional

from .core.interceptor import MCPInterceptor, V2Config
from .core.tracer import Tracer
from .exporters.base import Exporter
from .fallback.router import FallbackRouter
from .hallucination.config import HallucinationConfig
from .hallucination.signals import Verifier
from .policy.engine import PolicyEngine
from .policy.registry import ToolRegistry
from .token.issuer import TokenIssuer
from .token.verifier import TokenVerifier


def instrument(
    service_name: str,
    *,
    exporter: Optional[Exporter] = None,
    hallucination_config: Optional[HallucinationConfig] = None,
    verifier: Optional[Verifier] = None,
    tool_registry: Optional[ToolRegistry] = None,
    policy_engine: Optional[PolicyEngine] = None,
    token_issuer: Optional[TokenIssuer] = None,
    token_verifier: Optional[TokenVerifier] = None,
    fallback_router: Optional[FallbackRouter] = None,
    v2_config: Optional[V2Config] = None,
) -> MCPInterceptor:
    """Create a ready-to-use interceptor for an MCP server."""
    tracer = Tracer(service=service_name)
    return MCPInterceptor(
        tracer=tracer,
        exporter=exporter,
        hallucination_config=hallucination_config,
        verifier=verifier,
        tool_registry=tool_registry,
        policy_engine=policy_engine,
        token_issuer=token_issuer,
        token_verifier=token_verifier,
        fallback_router=fallback_router,
        v2_config=v2_config,
    )


instrument_mcp_server = instrument
