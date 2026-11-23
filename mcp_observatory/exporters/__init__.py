"""Exporter implementations for MCP Observatory."""

from .base import Exporter
from .sqlite import SQLiteSpanExporter
from .sync_bridge import (
    EncryptedSyncBridge,
    SyncBatchResult,
    decrypt_envelope,
    encrypt_spans,
)

__all__ = [
    "EncryptedSyncBridge",
    "Exporter",
    "PostgresExporter",
    "SQLiteSpanExporter",
    "SyncBatchResult",
    "decrypt_envelope",
    "encrypt_spans",
]


def __getattr__(name: str):
    if name == "PostgresExporter":
        from .postgres import PostgresExporter

        return PostgresExporter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
