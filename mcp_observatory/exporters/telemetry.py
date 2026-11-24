"""Unified local-first telemetry ingestor and rollup engine for ``weave-telemetry-v1``."""

from __future__ import annotations

import json
import math
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Self

TELEMETRY_SCHEMA = "weave-telemetry-v1"
ERROR_STATUSES = frozenset({"error", "failed", "failure", "timeout", "aborted"})


def _parse_iso_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _is_non_negative_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0.0
    )


def _is_non_negative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _percentile(sorted_values: list[float], pct: float) -> float | None:
    """Compute linear-interpolated percentile (0..100) over sorted values."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return round(sorted_values[0], 3)
    rank = (pct / 100.0) * (len(sorted_values) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return round(sorted_values[lo], 3)
    weight = rank - lo
    val = sorted_values[lo] * (1.0 - weight) + sorted_values[hi] * weight
    return round(val, 3)


def validate_telemetry_event(record: Any) -> dict[str, Any] | None:
    """Validate and normalize a ``weave-telemetry-v1`` record.

    Returns a normalized dict ready for persistence, or ``None`` if invalid.
    """
    if not isinstance(record, dict):
        return None
    if record.get("schema") != TELEMETRY_SCHEMA:
        return None

    required_strings = ("event_id", "source_repo", "event_type", "status", "timestamp")
    for field in required_strings:
        val = record.get(field)
        if not isinstance(val, str) or not val.strip():
            return None

    parsed_ts = _parse_iso_utc(record["timestamp"])
    if parsed_ts is None:
        return None

    latency_ms = record.get("latency_ms")
    if not _is_non_negative_number(latency_ms):
        return None

    tokens_in = record.get("tokens_in", 0)
    if not _is_non_negative_int(tokens_in):
        return None

    tokens_out = record.get("tokens_out", 0)
    if not _is_non_negative_int(tokens_out):
        return None

    cost_usd = record.get("cost_usd", 0.0)
    if not _is_non_negative_number(cost_usd):
        return None

    trace_id = record.get("trace_id", "")
    if trace_id is None:
        trace_id = ""
    if not isinstance(trace_id, str):
        return None

    attributes = record.get("attributes", {})
    if not isinstance(attributes, dict):
        return None

    return {
        "event_id": record["event_id"].strip(),
        "source_repo": record["source_repo"].strip(),
        "event_type": record["event_type"].strip(),
        "status": record["status"].strip(),
        "latency_ms": float(latency_ms),
        "tokens_in": int(tokens_in),
        "tokens_out": int(tokens_out),
        "cost_usd": float(cost_usd),
        "trace_id": trace_id,
        "timestamp": parsed_ts.isoformat().replace("+00:00", "Z"),
        "attributes_json": json.dumps(attributes, sort_keys=True, ensure_ascii=False),
    }


def _summarize_rows(rows: list[sqlite3.Row]) -> dict[str, Any]:
    total = len(rows)
    error_count = 0
    tokens_in = 0
    tokens_out = 0
    cost_usd = 0.0
    latencies: list[float] = []

    for row in rows:
        status = str(row["status"]).strip().lower()
        if status in ERROR_STATUSES:
            error_count += 1
        tokens_in += int(row["tokens_in"])
        tokens_out += int(row["tokens_out"])
        cost_usd += float(row["cost_usd"])
        latencies.append(float(row["latency_ms"]))

    latencies.sort()
    return {
        "total_events": total,
        "error_count": error_count,
        "error_rate": round(error_count / total, 6) if total > 0 else 0.0,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": round(cost_usd, 6),
        "p50_latency_ms": _percentile(latencies, 50.0),
        "p95_latency_ms": _percentile(latencies, 95.0),
    }


class TelemetryRollupEngine:
    """SQLite WAL ingestor and rollup engine for ``weave-telemetry-v1`` streams."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        if str(db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
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
                CREATE TABLE IF NOT EXISTS telemetry_events (
                    event_id TEXT PRIMARY KEY,
                    source_repo TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    latency_ms REAL NOT NULL,
                    tokens_in INTEGER NOT NULL,
                    tokens_out INTEGER NOT NULL,
                    cost_usd REAL NOT NULL,
                    trace_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    attributes_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_telemetry_source_ts
                    ON telemetry_events (source_repo, timestamp);
                CREATE INDEX IF NOT EXISTS idx_telemetry_ts
                    ON telemetry_events (timestamp);
                """
            )
            self._conn.commit()

    def ingest_event(self, record: dict[str, Any]) -> str:
        """Ingest a single ``weave-telemetry-v1`` event.

        Returns one of ``"ingested"``, ``"duplicate"``, or ``"invalid"``.
        """
        normalized = validate_telemetry_event(record)
        if normalized is None:
            return "invalid"
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT OR IGNORE INTO telemetry_events (
                    event_id,
                    source_repo,
                    event_type,
                    status,
                    latency_ms,
                    tokens_in,
                    tokens_out,
                    cost_usd,
                    trace_id,
                    timestamp,
                    attributes_json
                ) VALUES (
                    :event_id,
                    :source_repo,
                    :event_type,
                    :status,
                    :latency_ms,
                    :tokens_in,
                    :tokens_out,
                    :cost_usd,
                    :trace_id,
                    :timestamp,
                    :attributes_json
                )
                """,
                normalized,
            )
            self._conn.commit()
            return "ingested" if cursor.rowcount == 1 else "duplicate"

    def ingest_jsonl(self, jsonl_path: str | Path) -> dict[str, int]:
        """Validate and idempotently ingest a ``weave-telemetry-v1`` JSONL file."""
        path = Path(jsonl_path)
        if not path.is_file():
            raise FileNotFoundError(f"Telemetry JSONL file not found: {path}")

        ingested = 0
        skipped_duplicates = 0
        invalid = 0

        with path.open("r", encoding="utf-8") as handle, self._lock:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    parsed = json.loads(line)
                except json.JSONDecodeError:
                    invalid += 1
                    continue

                normalized = validate_telemetry_event(parsed)
                if normalized is None:
                    invalid += 1
                    continue

                cursor = self._conn.execute(
                    """
                    INSERT OR IGNORE INTO telemetry_events (
                        event_id,
                        source_repo,
                        event_type,
                        status,
                        latency_ms,
                        tokens_in,
                        tokens_out,
                        cost_usd,
                        trace_id,
                        timestamp,
                        attributes_json
                    ) VALUES (
                        :event_id,
                        :source_repo,
                        :event_type,
                        :status,
                        :latency_ms,
                        :tokens_in,
                        :tokens_out,
                        :cost_usd,
                        :trace_id,
                        :timestamp,
                        :attributes_json
                    )
                    """,
                    normalized,
                )
                if cursor.rowcount == 1:
                    ingested += 1
                else:
                    skipped_duplicates += 1
            self._conn.commit()

        return {
            "ingested": ingested,
            "skipped_duplicates": skipped_duplicates,
            "invalid": invalid,
        }

    def compute_rollup(
        self,
        *,
        source_repo: str | None = None,
        since_iso: str | None = None,
    ) -> dict[str, Any]:
        """Compute aggregate and per-repo/per-model telemetry rollups."""
        since_dt: datetime | None = None
        if since_iso is not None:
            since_dt = _parse_iso_utc(since_iso)
            if since_dt is None:
                raise ValueError(f"Invalid ISO-8601 timestamp for since_iso: {since_iso!r}")

        with self._lock:
            if source_repo is not None:
                rows = self._conn.execute(
                    "SELECT * FROM telemetry_events WHERE source_repo = ? ORDER BY timestamp ASC",
                    (source_repo,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT * FROM telemetry_events ORDER BY timestamp ASC"
                ).fetchall()

        filtered: list[sqlite3.Row] = []
        for row in rows:
            if since_dt is not None:
                row_dt = _parse_iso_utc(row["timestamp"])
                if row_dt is None or row_dt < since_dt:
                    continue
            filtered.append(row)

        overall = _summarize_rows(filtered)

        grouped_repo: dict[str, list[sqlite3.Row]] = {}
        grouped_model: dict[str, list[sqlite3.Row]] = {}
        for row in filtered:
            grouped_repo.setdefault(str(row["source_repo"]), []).append(row)
            try:
                attrs = json.loads(row["attributes_json"])
            except json.JSONDecodeError:
                attrs = {}
            if isinstance(attrs, dict):
                model = attrs.get("model_id") or attrs.get("model")
                if isinstance(model, str) and model.strip():
                    grouped_model.setdefault(model.strip(), []).append(row)

        by_source_repo = {
            repo: _summarize_rows(repo_rows)
            for repo, repo_rows in sorted(grouped_repo.items())
        }
        by_model = {
            model: _summarize_rows(model_rows)
            for model, model_rows in sorted(grouped_model.items())
        }

        return {
            "db_path": str(self.db_path),
            "source_repo": source_repo,
            "since_iso": since_iso,
            **overall,
            "by_source_repo": by_source_repo,
            "by_model": by_model,
        }

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()


__all__ = [
    "TELEMETRY_SCHEMA",
    "TelemetryRollupEngine",
    "validate_telemetry_event",
]
