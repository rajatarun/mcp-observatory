"""Tests for SLOEvaluator (slo-report-v1) and ``mcp-observatory slo`` CLI."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from mcp_observatory.cli import main as cli_main
from mcp_observatory.exporters import (
    SLO_REPORT_SCHEMA,
    TELEMETRY_SCHEMA,
    SLOEvaluator,
    SLOTargets,
    TelemetryRollupEngine,
)
from mcp_observatory.exporters.slo import (
    SLOEvaluator as DirectSLOEvaluator,
)
from mcp_observatory.exporters.slo import (
    SLOTargets as DirectSLOTargets,
)


def _event(
    event_id: str,
    *,
    source_repo: str = "HarnessWeave",
    event_type: str = "llm_call",
    status: str = "ok",
    latency_ms: float = 200.0,
    tokens_in: int = 100,
    tokens_out: int = 50,
    cost_usd: float = 0.01,
    trace_id: str = "trace-slo-1",
    timestamp: str = "2026-11-24T01:00:00Z",
    attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": TELEMETRY_SCHEMA,
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


def _assert_slo_report_structure(report: dict[str, Any]) -> None:
    expected_top = {
        "schema",
        "evaluated_at",
        "window_label",
        "source_repo",
        "status",
        "metrics",
        "targets",
        "breaches",
    }
    assert set(report.keys()) == expected_top
    assert report["schema"] == SLO_REPORT_SCHEMA
    assert report["status"] in {"pass", "warn", "breach", "insufficient_data"}
    # evaluated_at must parse as ISO-8601 UTC timestamp
    raw_ts = report["evaluated_at"]
    assert isinstance(raw_ts, str) and raw_ts.endswith("Z")
    datetime.fromisoformat(raw_ts)

    expected_metrics = {
        "total_events",
        "error_rate",
        "p50_latency_ms",
        "p95_latency_ms",
        "total_cost_usd",
    }
    assert set(report["metrics"].keys()) == expected_metrics

    expected_targets = {
        "max_p95_latency_ms",
        "max_error_rate",
        "max_cost_usd",
        "min_events",
    }
    assert set(report["targets"].keys()) == expected_targets

    assert isinstance(report["breaches"], list)
    for breach in report["breaches"]:
        assert set(breach.keys()) == {"metric", "observed", "threshold", "severity", "message"}
        assert breach["severity"] in {"warn", "breach"}
        assert isinstance(breach["message"], str) and breach["message"]


def test_exports_and_default_targets() -> None:
    assert SLOEvaluator is DirectSLOEvaluator
    assert SLOTargets is DirectSLOTargets

    defaults = SLOTargets()
    assert defaults.max_p95_latency_ms == 2000.0
    assert defaults.max_error_rate == 0.05
    assert defaults.max_cost_usd == 5.0
    assert defaults.min_events == 1


def test_slotargets_validation() -> None:
    with pytest.raises(ValueError, match="max_p95_latency_ms"):
        SLOTargets(max_p95_latency_ms=-1.0)
    with pytest.raises(ValueError, match="max_error_rate"):
        SLOTargets(max_error_rate=1.5)
    with pytest.raises(ValueError, match="max_error_rate"):
        SLOTargets(max_error_rate=-0.01)
    with pytest.raises(ValueError, match="max_cost_usd"):
        SLOTargets(max_cost_usd=-0.5)
    with pytest.raises(ValueError, match="min_events"):
        SLOTargets(min_events=-1)
    with pytest.raises(ValueError, match="min_events"):
        SLOTargets(min_events=True)  # type: ignore[arg-type]


def test_slo_pass_status_and_structure(tmp_path: Path) -> None:
    db_path = tmp_path / "telemetry.sqlite3"
    with TelemetryRollupEngine(db_path) as engine:
        for i in range(10):
            engine.ingest_event(
                _event(
                    f"evt-{i}",
                    latency_ms=100.0 + i * 10.0,
                    cost_usd=0.05,
                    status="ok",
                )
            )

        evaluator = SLOEvaluator(engine)
        report = evaluator.evaluate(window_label="last_1h")

    _assert_slo_report_structure(report)
    assert report["status"] == "pass"
    assert report["window_label"] == "last_1h"
    assert report["source_repo"] is None
    assert report["metrics"]["total_events"] == 10
    assert report["metrics"]["error_rate"] == 0.0
    assert report["metrics"]["total_cost_usd"] == pytest.approx(0.5)
    assert report["metrics"]["p50_latency_ms"] == pytest.approx(145.0)
    assert report["metrics"]["p95_latency_ms"] == pytest.approx(185.5)
    assert report["breaches"] == []


def test_slo_zero_threshold_with_zero_observed_passes(tmp_path: Path) -> None:
    db_path = tmp_path / "telemetry.sqlite3"
    with TelemetryRollupEngine(db_path) as engine:
        engine.ingest_event(_event("evt-local", latency_ms=50.0, cost_usd=0.0, status="ok"))
        evaluator = SLOEvaluator(engine)
        report = evaluator.evaluate(
            targets=SLOTargets(
                max_p95_latency_ms=1000.0,
                max_error_rate=0.0,
                max_cost_usd=0.0,
                min_events=1,
            )
        )

    _assert_slo_report_structure(report)
    assert report["status"] == "pass"
    assert report["breaches"] == []


def test_slo_warn_at_85_to_100_percent_of_threshold(tmp_path: Path) -> None:
    db_path = tmp_path / "telemetry.sqlite3"
    with TelemetryRollupEngine(db_path) as engine:
        # Exactly 85% of 2000ms = 1700ms
        engine.ingest_event(_event("evt-warn-lat", latency_ms=1700.0, cost_usd=0.1, status="ok"))
        evaluator = SLOEvaluator(engine)
        report = evaluator.evaluate(
            targets=SLOTargets(max_p95_latency_ms=2000.0, max_error_rate=0.05, max_cost_usd=5.0)
        )

    _assert_slo_report_structure(report)
    assert report["status"] == "warn"
    assert len(report["breaches"]) == 1
    assert report["breaches"][0]["metric"] == "p95_latency_ms"
    assert report["breaches"][0]["severity"] == "warn"
    assert report["breaches"][0]["observed"] == 1700.0
    assert report["breaches"][0]["threshold"] == 2000.0

    # Exactly 100% of cost threshold (5.0) without breaching -> still warn
    db_path_cost = tmp_path / "cost_warn.sqlite3"
    with TelemetryRollupEngine(db_path_cost) as engine:
        engine.ingest_event(_event("evt-warn-cost", latency_ms=100.0, cost_usd=5.0, status="ok"))
        report_cost = SLOEvaluator(engine).evaluate(
            targets=SLOTargets(max_p95_latency_ms=2000.0, max_error_rate=0.05, max_cost_usd=5.0)
        )
    _assert_slo_report_structure(report_cost)
    assert report_cost["status"] == "warn"
    assert report_cost["breaches"][0]["metric"] == "total_cost_usd"
    assert report_cost["breaches"][0]["severity"] == "warn"


def test_slo_breach_latency_error_rate_and_cost(tmp_path: Path) -> None:
    # 1. Latency breach
    with TelemetryRollupEngine(tmp_path / "lat.sqlite3") as engine:
        engine.ingest_event(_event("evt-slow", latency_ms=2500.0, cost_usd=0.1, status="ok"))
        rep_lat = SLOEvaluator(engine).evaluate(
            targets=SLOTargets(max_p95_latency_ms=2000.0, max_error_rate=0.05, max_cost_usd=5.0)
        )
    _assert_slo_report_structure(rep_lat)
    assert rep_lat["status"] == "breach"
    assert [b["metric"] for b in rep_lat["breaches"]] == ["p95_latency_ms"]
    assert rep_lat["breaches"][0]["severity"] == "breach"

    # 2. Error rate breach
    with TelemetryRollupEngine(tmp_path / "err.sqlite3") as engine:
        for i in range(9):
            engine.ingest_event(_event(f"ok-{i}", latency_ms=100.0, cost_usd=0.01, status="ok"))
        engine.ingest_event(_event("err-0", latency_ms=100.0, cost_usd=0.01, status="error"))
        rep_err = SLOEvaluator(engine).evaluate(
            targets=SLOTargets(max_p95_latency_ms=2000.0, max_error_rate=0.05, max_cost_usd=5.0)
        )
    _assert_slo_report_structure(rep_err)
    assert rep_err["status"] == "breach"
    assert rep_err["metrics"]["error_rate"] == pytest.approx(0.1)
    assert [b["metric"] for b in rep_err["breaches"]] == ["error_rate"]
    assert rep_err["breaches"][0]["severity"] == "breach"

    # 3. Cost breach + simultaneous latency warn
    with TelemetryRollupEngine(tmp_path / "cost.sqlite3") as engine:
        engine.ingest_event(_event("evt-cost", latency_ms=1800.0, cost_usd=6.25, status="ok"))
        rep_cost = SLOEvaluator(engine).evaluate(
            targets=SLOTargets(max_p95_latency_ms=2000.0, max_error_rate=0.05, max_cost_usd=5.0)
        )
    _assert_slo_report_structure(rep_cost)
    assert rep_cost["status"] == "breach"
    severities = {b["metric"]: b["severity"] for b in rep_cost["breaches"]}
    assert severities == {"p95_latency_ms": "warn", "total_cost_usd": "breach"}


def test_slo_insufficient_data(tmp_path: Path) -> None:
    db_path = tmp_path / "empty.sqlite3"
    with TelemetryRollupEngine(db_path) as engine:
        evaluator = SLOEvaluator(engine)
        empty_report = evaluator.evaluate(targets=SLOTargets(min_events=1))

        engine.ingest_event(_event("evt-1", latency_ms=9999.0, cost_usd=99.0, status="error"))
        below_min_report = evaluator.evaluate(targets=SLOTargets(min_events=5))

    _assert_slo_report_structure(empty_report)
    assert empty_report["status"] == "insufficient_data"
    assert empty_report["metrics"]["total_events"] == 0
    assert empty_report["metrics"]["p50_latency_ms"] is None
    assert empty_report["metrics"]["p95_latency_ms"] is None
    assert empty_report["breaches"] == []

    _assert_slo_report_structure(below_min_report)
    assert below_min_report["status"] == "insufficient_data"
    assert below_min_report["metrics"]["total_events"] == 1
    assert below_min_report["breaches"] == []


def test_slo_per_repo_and_since_filtering(tmp_path: Path) -> None:
    db_path = tmp_path / "multi_repo.sqlite3"
    with TelemetryRollupEngine(db_path) as engine:
        # HarnessWeave: healthy
        engine.ingest_event(
            _event(
                "hw-1",
                source_repo="HarnessWeave",
                latency_ms=120.0,
                cost_usd=0.05,
                timestamp="2026-11-24T01:00:00Z",
            )
        )
        # ModelWeave: old slow event + recent fast event
        engine.ingest_event(
            _event(
                "mw-old",
                source_repo="ModelWeave",
                latency_ms=5000.0,
                cost_usd=10.0,
                timestamp="2026-11-23T01:00:00Z",
            )
        )
        engine.ingest_event(
            _event(
                "mw-new",
                source_repo="ModelWeave",
                latency_ms=150.0,
                cost_usd=0.02,
                timestamp="2026-11-24T02:00:00Z",
            )
        )

        evaluator = SLOEvaluator(engine)
        hw_report = evaluator.evaluate(source_repo="HarnessWeave")
        mw_all = evaluator.evaluate(source_repo="ModelWeave")
        mw_recent = evaluator.evaluate(
            source_repo="ModelWeave",
            since_iso="2026-11-24T00:00:00Z",
            window_label="since_2026-11-24",
        )

    assert hw_report["status"] == "pass"
    assert hw_report["source_repo"] == "HarnessWeave"
    assert hw_report["metrics"]["total_events"] == 1

    assert mw_all["status"] == "breach"
    assert mw_all["source_repo"] == "ModelWeave"
    assert mw_all["metrics"]["total_events"] == 2

    assert mw_recent["status"] == "pass"
    assert mw_recent["window_label"] == "since_2026-11-24"
    assert mw_recent["metrics"]["total_events"] == 1


def test_cli_slo_exit_codes_and_json_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    db_path = tmp_path / "cli_slo.sqlite3"
    with TelemetryRollupEngine(db_path) as engine:
        engine.ingest_event(
            _event(
                "evt-1",
                source_repo="HarnessWeave",
                latency_ms=250.0,
                cost_usd=0.25,
                status="ok",
            )
        )
        engine.ingest_event(
            _event(
                "evt-2",
                source_repo="ModelWeave",
                latency_ms=3500.0,
                cost_usd=8.0,
                status="error",
            )
        )

    # 1. Pass -> exit 0
    rc_pass = cli_main(
        [
            "slo",
            "--db",
            str(db_path),
            "--repo",
            "HarnessWeave",
            "--max-p95-ms",
            "2000",
            "--max-error-rate",
            "0.05",
            "--max-cost-usd",
            "5.0",
            "--json",
        ]
    )
    assert rc_pass == 0
    payload_pass = json.loads(capsys.readouterr().out)
    _assert_slo_report_structure(payload_pass)
    assert payload_pass["status"] == "pass"

    # 2. Warn -> exit 0 (250ms against 280ms threshold is ~89.3%)
    rc_warn = cli_main(
        [
            "slo",
            "--db",
            str(db_path),
            "--repo",
            "HarnessWeave",
            "--max-p95-ms",
            "280",
            "--json",
        ]
    )
    assert rc_warn == 0
    payload_warn = json.loads(capsys.readouterr().out)
    _assert_slo_report_structure(payload_warn)
    assert payload_warn["status"] == "warn"

    # 3. Insufficient data -> exit 0
    rc_insuff = cli_main(
        [
            "slo",
            "--db",
            str(db_path),
            "--repo",
            "NonExistentRepo",
            "--json",
        ]
    )
    assert rc_insuff == 0
    payload_insuff = json.loads(capsys.readouterr().out)
    _assert_slo_report_structure(payload_insuff)
    assert payload_insuff["status"] == "insufficient_data"

    # 4. Breach -> exit 2
    rc_breach = cli_main(
        [
            "slo",
            "--db",
            str(db_path),
            "--repo",
            "ModelWeave",
            "--max-p95-ms",
            "2000",
            "--max-error-rate",
            "0.05",
            "--max-cost-usd",
            "5.0",
            "--json",
        ]
    )
    assert rc_breach == 2
    payload_breach = json.loads(capsys.readouterr().out)
    _assert_slo_report_structure(payload_breach)
    assert payload_breach["status"] == "breach"
    assert len(payload_breach["breaches"]) == 3

    # 5. Human-readable output on breach still exits 2
    rc_human = cli_main(["slo", "--db", str(db_path), "--repo", "ModelWeave"])
    assert rc_human == 2
    human_out = capsys.readouterr().out
    assert "MCP Observatory SLO Report (slo-report-v1)" in human_out
    assert "BREACH" in human_out

    # 6. Missing DB -> exit 1
    rc_missing = cli_main(["slo", "--db", str(tmp_path / "missing.sqlite3"), "--json"])
    assert rc_missing == 1
    assert "not found" in capsys.readouterr().err
