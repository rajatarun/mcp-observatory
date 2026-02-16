"""MCP Observatory package.

This package provides lightweight observability primitives for instrumenting
Model Context Protocol (MCP) servers.
"""

from .execution import TieredExecutionConfig, TieredExecutionEngine
from .hallucination.config import HallucinationConfig
from .instrument import instrument, instrument_mcp_server

__all__ = [
    "instrument",
    "instrument_mcp_server",
    "HallucinationConfig",
    "TieredExecutionConfig",
    "TieredExecutionEngine",
]
