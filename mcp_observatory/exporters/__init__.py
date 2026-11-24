"""Exporter implementations for MCP Observatory."""

from .base import Exporter
from .query import AuditQueryEngine, verify_audit_bundle
from .slo import SLO_REPORT_SCHEMA, SLOEvaluator, SLOTargets
from .sqlite import SQLiteSpanExporter
from .sync_bridge import (
    EncryptedSyncBridge,
    SyncBatchResult,
    decrypt_envelope,
    encrypt_spans,
)
from .telemetry import (
    TELEMETRY_SCHEMA,
    TelemetryRollupEngine,
    validate_telemetry_event,
)

__all__ = [
    "SLO_REPORT_SCHEMA",
    "TELEMETRY_SCHEMA",
    "AuditQueryEngine",
    "EncryptedSyncBridge",
    "Exporter",
    "PostgresExporter",
    "SLOEvaluator",
    "SLOTargets",
    "SQLiteSpanExporter",
    "SyncBatchResult",
    "TelemetryRollupEngine",
    "decrypt_envelope",
    "encrypt_spans",
    "validate_telemetry_event",
    "verify_audit_bundle",
]


def __getattr__(name: str):
    if name == "PostgresExporter":
        from .postgres import PostgresExporter

        return PostgresExporter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
