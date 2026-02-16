"""Deterministic fallback routing for blocked/reviewed tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, Optional

from .templates import block_response_template

FallbackCallable = Callable[[dict], Awaitable[Any]]


@dataclass
class FallbackRouter:
    """Routes blocked tool calls to deterministic fallbacks."""

    routes: Dict[str, FallbackCallable] = field(default_factory=dict)

    def register(self, tool_name: str, fallback_fn: FallbackCallable) -> None:
        self.routes[tool_name] = fallback_fn

    async def route(self, *, tool_name: str, tool_args: dict, reason: str) -> tuple[Any, str]:
        fn = self.routes.get(tool_name)
        if fn is None:
            return block_response_template(tool_name, reason), "template"
        return await fn(tool_args), "safe_tool"
