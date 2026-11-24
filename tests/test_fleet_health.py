"""Tests for Cycle 5 multi-node fleet health & SLO rollup aggregator (fleet-health-v1)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mcp_observatory import FleetHealthAggregator, FleetNodeInput
from mcp_observatory.cli import main as cli_main


def test_empty_fleet_is_healthy() -> None:
    now = datetime(2026, 11, 24, 12, 0, 0, tzinfo=UTC)
    agg = FleetHealthAggregator(fleet_id="home-fleet", stale_after_seconds=300)
    report = agg.aggregate([], now=now)

    assert report["schema"] == "fleet-health-v1"
    assert report["fleet_id"] == "home-fleet"
    assert report["generated_at"] == "2026-11-24T12:00:00Z"
    assert report["nodes"] == []
    assert report["summary"] == {
        "total_nodes": 0,
        "healthy": 0,
        "degraded": 0,
        "offline": 0,
        "overall_status": "healthy",
    }


def test_healthy_fleet_classification() -> None:
    now = datetime(2026, 11, 24, 12, 0, 0, tzinfo=UTC)
    nodes = [
        FleetNodeInput(
            node_id="pi-01",
            last_seen_at=now - timedelta(seconds=30),
            slo_report={"schema": "slo-report-v1", "status": "pass", "breaches": []},
            budget_mode="normal",
            active_wapps=3,
            device_unhealthy_count=0,
        ),
        FleetNodeInput(
            node_id="laptop-01",
            last_seen_at=now - timedelta(seconds=60),
            slo_report={"schema": "slo-report-v1", "status": "warn", "breaches": []},
            budget_mode="prefer_local",
            active_wapps=1,
            device_unhealthy_count=0,
        ),
    ]
    report = FleetHealthAggregator("edge-fleet").aggregate(nodes, now=now)
    assert report["summary"] == {
        "total_nodes": 2,
        "healthy": 2,
        "degraded": 0,
        "offline": 0,
        "overall_status": "healthy",
    }
    assert all(n["status"] == "healthy" and n["slo_passed"] is True for n in report["nodes"])


def test_degraded_nodes_from_slo_budget_and_devices() -> None:
    now = datetime(2026, 11, 24, 12, 0, 0, tzinfo=UTC)
    nodes = [
        FleetNodeInput(
            node_id="pi-healthy-1",
            last_seen_at=now - timedelta(seconds=10),
            slo_report={"status": "pass"},
        ),
        FleetNodeInput(
            node_id="pi-healthy-2",
            last_seen_at=now - timedelta(seconds=10),
            slo_report={"status": "pass"},
        ),
        FleetNodeInput(
            node_id="pi-slo-breach",
            last_seen_at=now - timedelta(seconds=20),
            slo_report={
                "status": "breach",
                "breaches": [{"severity": "breach", "message": "p95_latency_ms exceeded"}],
            },
            budget_mode="local_only",
            device_unhealthy_count=2,
        ),
    ]
    report = FleetHealthAggregator("edge-fleet").aggregate(nodes, now=now)
    # 1 degraded out of 3 (<= 50%), 0 offline => overall_status == "degraded"
    assert report["summary"] == {
        "total_nodes": 3,
        "healthy": 2,
        "degraded": 1,
        "offline": 0,
        "overall_status": "degraded",
    }
    degraded_node = next(n for n in report["nodes"] if n["node_id"] == "pi-slo-breach")
    assert degraded_node["status"] == "degraded"
    assert degraded_node["slo_passed"] is False
    assert any("slo breach" in r for r in degraded_node["reasons"])
    assert any("budget_mode=local_only" in r for r in degraded_node["reasons"])
    assert any("unhealthy_devices=2" in r for r in degraded_node["reasons"])


def test_offline_stale_node_triggers_critical_overall_status() -> None:
    now = datetime(2026, 11, 24, 12, 0, 0, tzinfo=UTC)
    nodes = [
        FleetNodeInput(node_id="pi-online", last_seen_at=now - timedelta(seconds=10)),
        FleetNodeInput(node_id="pi-stale", last_seen_at=now - timedelta(seconds=301)),
    ]
    report = FleetHealthAggregator("edge-fleet", stale_after_seconds=300).aggregate(nodes, now=now)
    assert report["summary"]["offline"] == 1
    assert report["summary"]["overall_status"] == "critical"
    stale = next(n for n in report["nodes"] if n["node_id"] == "pi-stale")
    assert stale["status"] == "offline"
    assert any("heartbeat stale" in r for r in stale["reasons"])


def test_critical_when_majority_degraded() -> None:
    now = datetime(2026, 11, 24, 12, 0, 0, tzinfo=UTC)
    nodes = [
        FleetNodeInput(node_id="n1", last_seen_at=now, budget_mode="normal"),
        FleetNodeInput(node_id="n2", last_seen_at=now, budget_mode="halt"),
        FleetNodeInput(node_id="n3", last_seen_at=now, device_unhealthy_count=1),
    ]
    report = FleetHealthAggregator("edge-fleet").aggregate(nodes, now=now)
    assert report["summary"] == {
        "total_nodes": 3,
        "healthy": 1,
        "degraded": 2,
        "offline": 0,
        "overall_status": "critical",
    }


def test_cli_fleet_summary_json_and_jsonl(tmp_path: Path, capsys) -> None:
    now_str = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    stale_str = (datetime.now(UTC) - timedelta(seconds=600)).isoformat().replace("+00:00", "Z")

    # JSON input
    json_path = tmp_path / "fleet.json"
    json_path.write_text(
        json.dumps(
            [
                {
                    "node_id": "pi-alpha",
                    "last_seen_at": now_str,
                    "slo_report": {"status": "pass"},
                    "budget_mode": "normal",
                    "active_wapps": 2,
                }
            ]
        ),
        encoding="utf-8",
    )
    rc = cli_main(["fleet-summary", "--input", str(json_path), "--fleet-id", "prod-edge"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["schema"] == "fleet-health-v1"
    assert out["fleet_id"] == "prod-edge"
    assert out["summary"]["overall_status"] == "healthy"

    # JSONL input with stale node
    jsonl_path = tmp_path / "fleet.jsonl"
    jsonl_path.write_text(
        "\n".join(
            [
                json.dumps({"node_id": "pi-alpha", "last_seen_at": now_str}),
                json.dumps({"node_id": "pi-beta", "last_seen_at": stale_str}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    rc2 = cli_main(
        [
            "fleet-summary",
            "--input",
            str(jsonl_path),
            "--fleet-id",
            "prod-edge",
            "--stale-after",
            "120",
        ]
    )
    assert rc2 == 0
    out2 = json.loads(capsys.readouterr().out)
    assert out2["summary"]["total_nodes"] == 2
    assert out2["summary"]["offline"] == 1
    assert out2["summary"]["overall_status"] == "critical"
