"""SQLite (WAL) span exporter conforming to the shared Observatory v2.0.0 item contract.

Provides durable, offline-first span storage for standalone laptops, containers,
and edge devices (e.g. Raspberry Pi) with zero external database dependencies,
plus an optional pending/flush queue for syncing to cloud backends when online.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..core.context import TraceContext
from .base import Exporter

DEFAULT_TTL_SECONDS = 90 * 24 * 60 * 60


def _serialize_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


class SQLiteSpanExporter(Exporter):
    """Persist Observatory spans into a local SQLite WAL database."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        namespace: str = "OBSERVATORY",
    ) -> None:
        self.db_path = Path(db_path)
        if str(db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ttl_seconds = ttl_seconds
        self._namespace = namespace
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS observatory_spans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pk TEXT NOT NULL,
                    sk TEXT NOT NULL,
                    span_date TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    service TEXT,
                    trace_id TEXT,
                    ttl INTEGER NOT NULL,
                    item_json TEXT NOT NULL,
                    flushed INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_spans_timeline
                    ON observatory_spans (span_date, timestamp);
                CREATE INDEX IF NOT EXISTS idx_spans_flushed
                    ON observatory_spans (flushed, id);
                """
            )
            self._conn.commit()

    def build_item(self, context: TraceContext) -> dict[str, Any]:
        item: dict[str, Any] = {}
        for key, value in context.to_dict().items():
            if value is None:
                continue
            item[key] = _serialize_value(value)

        start_dt = context.start_time
        if start_dt.tzinfo is None:
            start_dt = start_dt.replace(tzinfo=timezone.utc)
        started = start_dt.astimezone(timezone.utc).isoformat()
        operation = (
            context.operation
            or ("invoke_tool" if context.tool_name else "invoke_model" if context.model else "unknown")
        )
        discriminator = operation if self._namespace == "OBSERVATORY" else (
            context.tool_name or context.model or "unknown"
        )
        item["pk"] = f"{self._namespace}#{discriminator}"
        item["sk"] = f"{started}#{context.trace_id}"
        item["timestamp"] = started
        item["span_date"] = started[:10]
        item["operation"] = operation
        item["ttl"] = int(time.time()) + self._ttl_seconds
        return item

    async def export(self, context: TraceContext) -> None:
        item = self.build_item(context)
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO observatory_spans (
                    pk, sk, span_date, timestamp, operation, service, trace_id, ttl, item_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["pk"],
                    item["sk"],
                    item["span_date"],
                    item["timestamp"],
                    item["operation"],
                    item.get("service"),
                    item.get("trace_id"),
                    item["ttl"],
                    json.dumps(item, default=str),
                ),
            )
            self._conn.commit()

    def recent(self, *, limit: int = 50, span_date: Optional[str] = None) -> list[dict[str, Any]]:
        with self._lock:
            if span_date:
                rows = self._conn.execute(
                    "SELECT item_json FROM observatory_spans WHERE span_date = ? ORDER BY timestamp DESC LIMIT ?",
                    (span_date, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT item_json FROM observatory_spans ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [json.loads(r["item_json"]) for r in rows]

    def pending(self, *, limit: int = 100) -> list[tuple[int, dict[str, Any]]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, item_json FROM observatory_spans WHERE flushed = 0 ORDER BY id ASC LIMIT ?",
                (limit,),
            ).fetchall()
            return [(int(r["id"]), json.loads(r["item_json"])) for r in rows]

    def mark_flushed(self, row_ids: list[int]) -> None:
        if not row_ids:
            return
        placeholders = ",".join("?" for _ in row_ids)
        with self._lock:
            self._conn.execute(
                f"UPDATE observatory_spans SET flushed = 1 WHERE id IN ({placeholders})",
                row_ids,
            )
            self._conn.commit()

    def prune_expired(self, *, now_epoch: Optional[int] = None) -> int:
        cutoff = now_epoch if now_epoch is not None else int(time.time())
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM observatory_spans WHERE ttl <= ?",
                (cutoff,),
            )
            self._conn.commit()
            return cur.rowcount

    def close(self) -> None:
        with self._lock:
            self._conn.close()
