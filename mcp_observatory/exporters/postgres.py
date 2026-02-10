"""PostgreSQL exporter for MCP Observatory trace data."""

from __future__ import annotations

from typing import Optional

import asyncpg

from ..core.context import TraceContext
from .base import Exporter


INSERT_SQL = """
INSERT INTO mcp_traces (
    trace_id,
    span_id,
    parent_span_id,
    service,
    model,
    tool_name,
    start_time,
    end_time,
    prompt_tokens,
    completion_tokens,
    cost_usd,
    retries,
    fallback_used,
    confidence
)
VALUES (
    $1::uuid, $2::uuid, $3::uuid, $4, $5, $6,
    $7, $8, $9, $10, $11, $12, $13, $14
)
"""


class PostgresExporter(Exporter):
    """Exporter that persists spans into PostgreSQL using ``asyncpg``."""

    def __init__(
        self,
        dsn: Optional[str] = None,
        *,
        pool: Optional[asyncpg.Pool] = None,
        min_size: int = 1,
        max_size: int = 10,
    ) -> None:
        self._dsn = dsn
        self._pool = pool
        self._min_size = min_size
        self._max_size = max_size

    async def connect(self) -> None:
        """Initialize a connection pool if one was not supplied."""
        if self._pool is not None:
            return
        if not self._dsn:
            raise ValueError("Either `dsn` or `pool` must be provided for PostgresExporter.")

        self._pool = await asyncpg.create_pool(
            dsn=self._dsn,
            min_size=self._min_size,
            max_size=self._max_size,
        )

    async def export(self, context: TraceContext) -> None:
        """Insert a completed trace context into PostgreSQL."""
        if self._pool is None:
            await self.connect()

        assert self._pool is not None
        payload = context.to_dict()

        async with self._pool.acquire() as conn:
            await conn.execute(
                INSERT_SQL,
                payload["trace_id"],
                payload["span_id"],
                payload["parent_span_id"],
                payload["service"],
                payload["model"],
                payload["tool_name"],
                payload["start_time"],
                payload["end_time"],
                payload["prompt_tokens"],
                payload["completion_tokens"],
                payload["cost_usd"],
                payload["retries"],
                payload["fallback_used"],
                payload["confidence"],
            )

    async def close(self) -> None:
        """Close the underlying pool if it exists."""
        if self._pool is not None:
            await self._pool.close()
            self._pool = None
