"""Exporter implementations for MCP Observatory."""

from .base import Exporter
from .sqlite import SQLiteSpanExporter

__all__ = ["Exporter", "PostgresExporter", "SQLiteSpanExporter"]


def __getattr__(name: str):
    if name == "PostgresExporter":
        from .postgres import PostgresExporter

        return PostgresExporter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
