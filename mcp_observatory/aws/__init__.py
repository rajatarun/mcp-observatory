"""Shared AWS wiring for mcp-observatory consumers.

Extracted from near-identical code independently vendored by four sibling
services (ToolWeave, DataDictionary, TeamWeave, DeviceWeave):

- :class:`DynamoDBSpanExporter` -- writes span/decision telemetry to a
  DynamoDB table (name from ``OBSERVATORY_METRICS_TABLE``) with a TTL.
- :func:`build_gate` -- wires a ``(proposer, verifier, token_manager)``
  propose/commit gate, ``InMemoryStorage`` by default and Postgres when
  ``MCP_OBSERVATORY_PG_DSN`` is set.

Importing this module never requires ``boto3`` -- it is imported lazily,
only when :class:`DynamoDBSpanExporter` actually needs a table. Install it
with the ``aws`` extra: ``pip install mcp-observatory[aws]``.

No ``observe_model_request``-style helper is provided here: the four
vendored copies do not agree on its shape (see ``CHANGELOG.md`` 0.3.0 for
why), so standardising one would not be a faithful extraction.
"""

from __future__ import annotations

from .dynamodb_exporter import DynamoDBSpanExporter
from .gate import build_gate

__all__ = ["DynamoDBSpanExporter", "build_gate"]
