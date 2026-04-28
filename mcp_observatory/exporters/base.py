"""Base exporter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..core.context import TraceContext


class Exporter(ABC):
    """Abstract base class for telemetry exporters."""

    @abstractmethod
    async def export(self, context: TraceContext) -> None:
        """Export one completed trace span."""

    async def close(self) -> None:
        """Close exporter resources if needed."""
