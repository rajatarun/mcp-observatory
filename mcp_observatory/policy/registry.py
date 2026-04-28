"""Registry for tool risk profiles."""

from __future__ import annotations

from typing import Callable, Dict, Optional, Union

from .types import Criticality, ToolProfile


class ToolRegistry:
    """In-memory registry for MCP tool profile metadata."""

    def __init__(self) -> None:
        self._profiles: Dict[str, ToolProfile] = {}

    def register(self, profile: ToolProfile) -> None:
        self._profiles[profile.name] = profile

    def get(self, tool_name: str) -> ToolProfile:
        return self._profiles.get(tool_name, ToolProfile(name=tool_name, criticality=Criticality.LOW))

    def all(self) -> Dict[str, ToolProfile]:
        return dict(self._profiles)


def _to_criticality(value: Union[str, Criticality]) -> Criticality:
    if isinstance(value, Criticality):
        return value
    return Criticality[value.upper()]


def tool_profile(
    *,
    name: Optional[str] = None,
    criticality: Union[str, Criticality] = Criticality.LOW,
    blast_radius: str = "limited",
    irreversible: bool = False,
    regulatory: bool = False,
    risk_tier: Optional[str] = None,
    registry: Optional[ToolRegistry] = None,
) -> Callable:
    """Decorator registering a callable with a tool profile."""

    effective_registry = registry or DEFAULT_REGISTRY

    def decorator(fn: Callable) -> Callable:
        profile = ToolProfile(
            name=name or fn.__name__,
            criticality=_to_criticality(criticality),
            blast_radius=blast_radius,
            irreversible=irreversible,
            regulatory=regulatory,
            risk_tier=risk_tier,
        )
        effective_registry.register(profile)
        setattr(fn, "_tool_profile", profile)
        return fn

    return decorator


DEFAULT_REGISTRY = ToolRegistry()
