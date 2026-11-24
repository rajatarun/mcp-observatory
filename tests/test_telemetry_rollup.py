"""Tests for TelemetryRollupEngine (weave-telemetry-v1) and telemetry CLI commands."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from mcp_observatory.cli import main as cli_main
from mcp_observatory.exporters import (
    TELEMETRY_SCHEMA,
    TelemetryRollupEngine,
    validate_telemetry_event,
)


def _event(
    event_id: str,
    *,
    source_repo: str = "HarnessWeave",
    event_type: str = "llm_call",
    status: str = "ok",
    latency_ms: float = 100.0,
    tokens_in: int = 120,
    tokens_out: int = 40,
    cost_usd: float = 0.002,
    trace_id: str | None = "trace-1",
    timestamp: str = "2026-11-23T12:00:00Z",
    attributes: dict[str, Any] | None = None,
    schema: str = TELEMETRY_SCHEMA,
) -> dict[str, Any]:
    return {
        "schema": schema,
        "event_id": event_id,
        "source_repo": source_repo,
        "event_type": event_type,
        "status": status,
        "latency_ms": latency_ms,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": cost_usd,
        "trace_id": trace_id,
        "timestamp": timestamp,
        "attributes": attributes if attributes is not None else {},
    }


def _write_jsonl(path: Path, records: list[Any]) -> None:
    lines: list[str] = []
    for rec in records:
        if isinstance(rec, str):
            lines.append(rec)
        else:
            lines.append(json.dumps(rec))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_validate_telemetry_event_valid_and_invalid_cases() -> None:
    valid = _event("evt-1", trace_id=None, attributes={"model_id": "local/llama-3b"})
    normalized = validate_telemetry_event(valid)
    assert normalized is not None
    assert normalized["event_id"] == "evt-1"
    assert normalized["trace_id"] == ""
    assert normalized["timestamp"] == "2026-11-23T12:00:00Z"
    assert json.loads(normalized["attributes_json"]) == {"model_id": "local/llama-3b"}

    # Wrong schema
    assert validate_telemetry_event(_event("evt-bad-schema", schema="other-v1")) is None
    # Missing required string
    bad_missing = _event("evt-missing")
    del bad_missing["source_repo"]
    assert validate_telemetry_event(bad_missing) is None
    # Negative latency / cost / tokens
    assert validate_telemetry_event(_event("evt-neg-lat", latency_ms=-1.0)) is None
    assert validate_telemetry_event(_event("evt-neg-cost", cost_usd=-0.01)) is None
    assert validate_telemetry_event(_event("evt-neg-tok", tokens_in=-5)) is None
    # Booleans must not pass as numeric values
    assert validate_telemetry_event(_event("evt-bool-tok", tokens_out=True)) is None  # type: ignore[arg-type]
    # Invalid timestamp
    assert validate_telemetry_event(_event("evt-bad-ts", timestamp="not-a-timestamp")) is None
    # Invalid attributes type
    bad_attrs = _event("evt-bad-attrs")
    bad_attrs["attributes"] = ["not", "a", "dict"]
    assert validate_telemetry_event(bad_attrs) is None


def test_sqlite_wal_schema_and_columns(tmp_path: Path) -> None:
    db_path = tmp_path / "telemetry.sqlite3"
    with TelemetryRollupEngine(db_path) as engine:
        assert engine.ingest_event(_event("evt-wal")) == "ingested"

    conn = sqlite3.connect(str(db_path))
    try:
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert str(journal_mode).lower() == "wal"

        cols = [row[1] for row in conn.execute("PRAGMA table_info(telemetry_events)").fetchall()]
        assert cols == [
            "event_id",
            "source_repo",
            "event_type",
            "status",
            "latency_ms",
            "tokens_in",
            "tokens_out",
            "cost_usd",
            "trace_id",
            "timestamp",
            "attributes_json",
        ]
    finally:
        conn.close()


def test_ingest_jsonl_idempotent_duplicates_and_invalid_counting(tmp_path: Path) -> None:
    db_path = tmp_path / "telemetry.sqlite3"
    jsonl_path = tmp_path / "events.jsonl"

    _write_jsonl(
        jsonl_path,
        [
            _event("evt-1", source_repo="HarnessWeave", latency_ms=50.0),
            _event("evt-2", source_repo="ModelWeave", latency_ms=80.0),
            # Duplicate within the same file
            _event("evt-1", source_repo="HarnessWeave", latency_ms=999.0),
            # Blank line should be ignored (not counted as invalid)
            "",
            # Malformed JSON
            "{not valid json",
            # Wrong schema
            _event("evt-bad-schema", schema="wrong-schema-v0"),
            # Missing required field
            {"schema": TELEMETRY_SCHEMA, "event_id": "evt-incomplete"},
        ],
    )

    with TelemetryRollupEngine(db_path) as engine:
        first = engine.ingest_jsonl(jsonl_path)
        assert first == {"ingested": 2, "skipped_duplicates": 1, "invalid": 3}

        # Re-ingesting the exact same file skips all valid rows idempotently
        second = engine.ingest_jsonl(jsonl_path)
        assert second == {"ingested": 0, "skipped_duplicates": 3, "invalid": 3}

        rollup = engine.compute_rollup()
        assert rollup["total_events"] == 2
        # Original evt-1 latency (50.0) preserved over duplicate (999.0)
        assert rollup["by_source_repo"]["HarnessWeave"]["p50_latency_ms"] == 50.0


def test_compute_rollup_multi_repo_percentiles_error_rate_cost_and_filters(tmp_path: Path) -> None:
    db_path = tmp_path / "telemetry.sqlite3"
    jsonl_path = tmp_path / "multi_repo.jsonl"

    # Latencies across all 5 events: [10, 20, 30, 40, 100]
    # p50 rank = 0.50 * 4 = 2.0 -> 30.0
    # p95 rank = 0.95 * 4 = 3.8 -> 40 * 0.2 + 100 * 0.8 = 88.0
    records = [
        _event(
            "e1",
            source_repo="HarnessWeave",
            status="ok",
            latency_ms=10.0,
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.001,
            timestamp="2026-11-23T10:00:00Z",
            attributes={"model_id": "local/llama-3b"},
        ),
        _event(
            "e2",
            source_repo="HarnessWeave",
            status="error",
            latency_ms=40.0,
            tokens_in=200,
            tokens_out=0,
            cost_usd=0.002,
            timestamp="2026-11-23T10:10:00Z",
            attributes={"model_id": "local/llama-3b"},
        ),
        _event(
            "e3",
            source_repo="ModelWeave",
            status="ok",
            latency_ms=20.0,
            tokens_in=300,
            tokens_out=100,
            cost_usd=0.005,
            timestamp="2026-11-23T10:20:00Z",
            attributes={"model": "gemini-2.5-flash"},
        ),
        _event(
            "e4",
            source_repo="ModelWeave",
            status="timeout",
            latency_ms=100.0,
            tokens_in=150,
            tokens_out=0,
            cost_usd=0.003,
            timestamp="2026-11-23T10:30:00Z",
            attributes={"model": "gemini-2.5-flash"},
        ),
        _event(
            "e5",
            source_repo="ToolWeave",
            status="ok",
            latency_ms=30.0,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            timestamp="2026-11-23T10:40:00+00:00",
            attributes={"tool_name": "fetch_weather"},
        ),
    ]
    _write_jsonl(jsonl_path, records)

    with TelemetryRollupEngine(db_path) as engine:
        res = engine.ingest_jsonl(jsonl_path)
        assert res == {"ingested": 5, "skipped_duplicates": 0, "invalid": 0}

        overall = engine.compute_rollup()
        assert overall["total_events"] == 5
        assert overall["error_count"] == 2
        assert overall["error_rate"] == pytest.approx(0.4)
        assert overall["tokens_in"] == 750
        assert overall["tokens_out"] == 150
        assert overall["cost_usd"] == pytest.approx(0.011)
        assert overall["p50_latency_ms"] == 30.0
        assert overall["p95_latency_ms"] == 88.0

        assert set(overall["by_source_repo"].keys()) == {"HarnessWeave", "ModelWeave", "ToolWeave"}
        hw = overall["by_source_repo"]["HarnessWeave"]
        assert hw["total_events"] == 2
        assert hw["error_count"] == 1
        assert hw["error_rate"] == pytest.approx(0.5)
        assert hw["p50_latency_ms"] == 25.0
        assert hw["cost_usd"] == pytest.approx(0.003)

        assert set(overall["by_model"].keys()) == {"local/llama-3b", "gemini-2.5-flash"}
        assert overall["by_model"]["local/llama-3b"]["total_events"] == 2
        assert overall["by_model"]["gemini-2.5-flash"]["cost_usd"] == pytest.approx(0.008)

        # Filter by source_repo
        mw_only = engine.compute_rollup(source_repo="ModelWeave")
        assert mw_only["total_events"] == 2
        assert mw_only["error_count"] == 1
        assert list(mw_only["by_source_repo"].keys()) == ["ModelWeave"]

        # Filter by since_iso
        recent = engine.compute_rollup(since_iso="2026-11-23T10:25:00Z")
        assert recent["total_events"] == 2
        assert recent["error_count"] == 1
        assert set(recent["by_source_repo"].keys()) == {"ModelWeave", "ToolWeave"}

        with pytest.raises(ValueError):
            engine.compute_rollup(since_iso="not-an-iso-ts")


def test_compute_rollup_empty_database(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.sqlite3"
    with TelemetryRollupEngine(db_path) as engine:
        rollup = engine.compute_rollup()
        assert rollup["total_events"] == 0
        assert rollup["error_count"] == 0
        assert rollup["error_rate"] == 0.0
        assert rollup["tokens_in"] == 0
        assert rollup["tokens_out"] == 0
        assert rollup["cost_usd"] == 0.0
        assert rollup["p50_latency_ms"] is None
        assert rollup["p95_latency_ms"] is None
        assert rollup["by_source_repo"] == {}
        assert rollup["by_model"] == {}


def test_cli_ingest_telemetry_and_rollup_json_and_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = tmp_path / "cli_telemetry.sqlite3"
    jsonl_path = tmp_path / "cli_events.jsonl"

    _write_jsonl(
        jsonl_path,
        [
            _event(
                "cli-1",
                source_repo="HarnessWeave",
                status="ok",
                latency_ms=25.0,
                tokens_in=50,
                tokens_out=25,
                cost_usd=0.001,
                timestamp="2026-11-23T11:00:00Z",
                attributes={"model_id": "local/qwen-3b"},
            ),
            _event(
                "cli-2",
                source_repo="ToolWeave",
                status="error",
                latency_ms=75.0,
                tokens_in=10,
                tokens_out=0,
                cost_usd=0.0,
                timestamp="2026-11-23T11:15:00Z",
            ),
            _event("cli-1", source_repo="HarnessWeave", latency_ms=25.0),
            {"schema": "bad-v0", "event_id": "cli-bad"},
        ],
    )

    rc = cli_main(["ingest-telemetry", "--db", str(db_path), "--input", str(jsonl_path), "--json"])
    assert rc == 0
    ingest_out = json.loads(capsys.readouterr().out)
    assert ingest_out == {"ingested": 2, "skipped_duplicates": 1, "invalid": 1}

    # Human output for ingest-telemetry
    rc = cli_main(["ingest-telemetry", "--db", str(db_path), "--input", str(jsonl_path)])
    assert rc == 0
    assert "Ingested 0 events" in capsys.readouterr().out

    # JSON output for rollup
    rc = cli_main(["rollup", "--db", str(db_path), "--json"])
    assert rc == 0
    rollup_out = json.loads(capsys.readouterr().out)
    assert rollup_out["total_events"] == 2
    assert rollup_out["error_count"] == 1
    assert rollup_out["error_rate"] == pytest.approx(0.5)
    assert rollup_out["p50_latency_ms"] == 50.0
    assert set(rollup_out["by_source_repo"].keys()) == {"HarnessWeave", "ToolWeave"}

    # Filtered rollup via --repo and --since
    rc = cli_main(
        [
            "rollup",
            "--db",
            str(db_path),
            "--repo",
            "ToolWeave",
            "--since",
            "2026-11-23T11:10:00Z",
            "--json",
        ]
    )
    assert rc == 0
    filtered_out = json.loads(capsys.readouterr().out)
    assert filtered_out["total_events"] == 1
    assert filtered_out["error_count"] == 1
    assert list(filtered_out["by_source_repo"].keys()) == ["ToolWeave"]

    # Human output for rollup
    rc = cli_main(["rollup", "--db", str(db_path)])
    assert rc == 0
    human_out = capsys.readouterr().out
    assert "MCP Observatory Telemetry Rollup" in human_out
    assert "HarnessWeave" in human_out

    # Missing input file -> exit code 1
    rc = cli_main(
        ["ingest-telemetry", "--db", str(db_path), "--input", str(tmp_path / "missing.jsonl")]
    )
    assert rc == 1
    assert "not found" in capsys.readouterr().err.lower()

    # Missing DB file for rollup -> exit code 1
    rc = cli_main(["rollup", "--db", str(tmp_path / "missing.sqlite3")])
    assert rc == 1
    assert "not found" in capsys.readouterr().err.lower()

    # Invalid --since -> exit code 1
    rc = cli_main(["rollup", "--db", str(db_path), "--since", "bad-date"])
    assert rc == 1
    assert "invalid iso-8601" in capsys.readouterr().err.lower()
