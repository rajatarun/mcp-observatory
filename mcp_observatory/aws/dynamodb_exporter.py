"""DynamoDB span exporter, extracted from four near-identical vendored copies.

ToolWeave, TeamWeave and DeviceWeave each wrote their own exporter from an
mcp-observatory ``TraceContext`` to a DynamoDB table, resolved from
``OBSERVATORY_METRICS_TABLE``, with a TTL attribute for automatic expiry.
This is that exporter, generalised: it writes every populated field of the
span (telemetry, hallucination/risk signals, and the policy decision, which
``TraceContext`` already carries as ``policy_decision``/``fallback_reason``)
rather than a hand-picked subset, so a new span field does not silently go
unrecorded.

``boto3`` is only imported when a table is actually needed (construction
does not require it), so importing this module -- or the package -- never
requires ``boto3`` to be installed. Install it with the ``aws`` extra:
``pip install mcp-observatory[aws]``.
"""

from __future__ import annotations

import os
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from ..core.context import TraceContext
from ..exporters.base import Exporter

DEFAULT_TABLE_NAME_ENV = "OBSERVATORY_METRICS_TABLE"
DEFAULT_TTL_SECONDS = 90 * 24 * 60 * 60  # 90 days, matching the vendored copies


def _import_boto3():
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - exercised via monkeypatch in tests
        raise RuntimeError(
            "DynamoDBSpanExporter needs boto3. Install it with `pip install "
            "mcp-observatory[aws]` (or just `pip install boto3`)."
        ) from exc
    return boto3


def _to_dynamo_value(value: Any) -> Any:
    """Convert one Python value to something DynamoDB's Table resource accepts.

    ``float`` is rejected by boto3's serializer (DynamoDB numbers are
    exact); everything else it already knows how to serialise.
    """
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


class DynamoDBSpanExporter(Exporter):
    """Write completed spans to a DynamoDB table, with a TTL attribute.

    Item shape: ``pk = "SPAN#{tool_name or model or 'unknown'}"``,
    ``sk = "{start_time.isoformat()}#{trace_id}"``, plus every field of
    ``TraceContext.to_dict()`` that is not ``None`` (floats become
    ``Decimal``, datetimes become ISO-8601 strings), plus ``ttl`` (epoch
    seconds) for DynamoDB's native item-expiry.

    Exports are best-effort: a failed ``put_item`` (missing table, missing
    credentials, throttling, ...) is swallowed so telemetry never breaks
    the caller's actual request, matching the vendored copies this was
    extracted from.
    """

    def __init__(
        self,
        *,
        table_name: Optional[str] = None,
        table_name_env: str = DEFAULT_TABLE_NAME_ENV,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        region_name: Optional[str] = None,
        resource: Any = None,
    ) -> None:
        """
        Args:
            table_name: DynamoDB table name. Defaults to
                ``os.environ[table_name_env]``.
            table_name_env: Environment variable to read ``table_name``
                from when it is not passed explicitly.
            ttl_seconds: How long an item survives before DynamoDB expires
                it. Default 90 days.
            region_name: Optional AWS region for the lazily created boto3
                session; defaults to boto3's own resolution (env/config).
            resource: A pre-built boto3 DynamoDB resource (or a stand-in
                with a compatible ``.Table(name)``), for tests or callers
                that already manage their own session. When omitted, one
                is created lazily via ``boto3.resource("dynamodb")`` on
                first export.
        """
        self._table_name = table_name or os.getenv(table_name_env)
        if not self._table_name:
            raise ValueError(
                f"DynamoDBSpanExporter needs a table name: pass table_name= "
                f"or set {table_name_env}."
            )
        self._ttl_seconds = ttl_seconds
        self._region_name = region_name
        self._resource = resource
        self._table = resource.Table(self._table_name) if resource is not None else None

    def _get_table(self):
        if self._table is None:
            boto3 = _import_boto3()
            kwargs = {"region_name": self._region_name} if self._region_name else {}
            self._resource = boto3.resource("dynamodb", **kwargs)
            self._table = self._resource.Table(self._table_name)
        return self._table

    def _build_item(self, context: TraceContext) -> dict:
        item: dict = {}
        for key, value in context.to_dict().items():
            if value is None:
                continue
            item[key] = _to_dynamo_value(value)

        partition = context.tool_name or context.model or "unknown"
        sort = f"{context.start_time.isoformat()}#{context.trace_id}"
        item["pk"] = f"SPAN#{partition}"
        item["sk"] = sort
        item["ttl"] = int(time.time()) + self._ttl_seconds
        return item

    async def export(self, context: TraceContext) -> None:
        try:
            table = self._get_table()
            table.put_item(Item=self._build_item(context))
        except Exception:
            # Best-effort: a metrics write must never break the caller.
            pass
