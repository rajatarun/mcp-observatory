"""Tests for AuditQueryEngine, tamper-evident audit-bundle-v1 export, and CLI."""

from __future__ import annotations

import asyncio
import csv
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mcp_observatory.cli import main as cli_main
from mcp_observatory.core.context import TraceContext
from mcp_observatory.exporters import (
    AuditQueryEngine,
    SQLiteSpanExporter,
    verify_audit_bundle,
)


def _seed_db(db_path: Path) -> None:
    exporter = SQLiteSpanExporter(db_path)
    base = datetime(2026, 11, 23, 10, 0, 0, tzinfo=UTC)

    spans = [
        TraceContext(
            service="weaveos",
            operation="invoke_tool",
            tool_name="deviceweave:status",
            start_time=base,
            end_time=base + timedelta(milliseconds=15),
            policy_decision="allow",
            composite_risk_score=0.1,
        ),
        TraceContext(
            service="weaveos",
            operation="invoke_tool",
            tool_name="deviceweave:unlock",
            start_time=base + timedelta(minutes=10),
            end_time=base + timedelta(minutes=10, milliseconds=30),
            gate_blocked=True,
            policy_decision="block",
            composite_risk_score=0.92,
        ),
        TraceContext(
            service="weaveos",
            operation="invoke_tool",
            tool_name="contextweave:search",
            start_time=base + timedelta(minutes=20),
            end_time=base + timedelta(minutes=20, milliseconds=25),
            policy_decision="error",
            composite_risk_score=0.65,
        ),
        TraceContext(
            service="weaveos",
            operation="invoke_tool",
            tool_name="deviceweave:status",
            start_time=base + timedelta(minutes=30),
            end_time=base + timedelta(minutes=30, milliseconds=12),
            policy_decision="allow",
            hallucination_risk_score=0.45,
        ),
    ]

    async def _run() -> None:
        for span in spans:
            await exporter.export(span)

    asyncio.run(_run())
    exporter.close()


def test_query_spans_filters_by_tool_status_risk_and_time_window(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"
    _seed_db(db_path)
    engine = AuditQueryEngine(db_path)

    all_spans = engine.query_spans()
    assert len(all_spans) == 4

    by_tool = engine.query_spans(tool_name="deviceweave:status")
    assert len(by_tool) == 2
    assert all(s["tool_name"] == "deviceweave:status" for s in by_tool)

    blocked = engine.query_spans(status="blocked")
    assert len(blocked) == 1
    assert blocked[0]["tool_name"] == "deviceweave:unlock"

    errored = engine.query_spans(status="error")
    assert len(errored) == 1
    assert errored[0]["tool_name"] == "contextweave:search"

    high_risk = engine.query_spans(min_risk=0.6)
    assert len(high_risk) == 2
    assert {s["tool_name"] for s in high_risk} == {"deviceweave:unlock", "contextweave:search"}

    windowed = engine.query_spans(
        since_iso="2026-11-23T10:05:00Z",
        until_iso="2026-11-23T10:25:00Z",
    )
    assert len(windowed) == 2
    assert [s["tool_name"] for s in windowed] == ["deviceweave:unlock", "contextweave:search"]

    limited = engine.query_spans(limit=2)
    assert len(limited) == 2


def test_export_jsonl_bundle_manifest_and_tamper_detection(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"
    _seed_db(db_path)
    engine = AuditQueryEngine(db_path)

    out_path = tmp_path / "exports" / "audit.jsonl"
    manifest = engine.export_audit_bundle(out_path, fmt="jsonl", min_risk=0.4)

    # Strict audit-bundle-v1 contract fields.
    assert set(manifest.keys()) == {
        "schema",
        "record_count",
        "chain_head_sha256",
        "exported_at",
        "format",
        "filters",
    }
    assert manifest["schema"] == "audit-bundle-v1"
    assert manifest["record_count"] == 3
    assert len(manifest["chain_head_sha256"]) == 64
    assert manifest["format"] == "jsonl"
    assert manifest["filters"] == {"min_risk": 0.4}

    ok, errors = verify_audit_bundle(out_path)
    assert ok is True
    assert errors == []

    original_lines = out_path.read_text(encoding="utf-8").splitlines()
    assert len(original_lines) == 3

    # 1. Tamper a single field inside line 1 -> must fail verification.
    tampered_byte_path = tmp_path / "tampered_byte.jsonl"
    tampered_lines = list(original_lines)
    tampered_lines[1] = tampered_lines[1].replace("contextweave:search", "contextweave:tamper")
    tampered_byte_path.write_text("\n".join(tampered_lines) + "\n", encoding="utf-8")
    Path(f"{tampered_byte_path}.manifest.json").write_text(
        Path(f"{out_path}.manifest.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    ok_byte, errs_byte = verify_audit_bundle(tampered_byte_path)
    assert ok_byte is False
    assert errs_byte

    # 2. Reorder two lines -> must fail verification.
    reordered_path = tmp_path / "reordered.jsonl"
    reordered_lines = [original_lines[1], original_lines[0], original_lines[2]]
    reordered_path.write_text("\n".join(reordered_lines) + "\n", encoding="utf-8")
    Path(f"{reordered_path}.manifest.json").write_text(
        Path(f"{out_path}.manifest.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    ok_order, errs_order = verify_audit_bundle(reordered_path)
    assert ok_order is False
    assert errs_order

    # 3. Delete last line (truncation) -> must fail verification via manifest check.
    truncated_path = tmp_path / "truncated.jsonl"
    truncated_path.write_text("\n".join(original_lines[:-1]) + "\n", encoding="utf-8")
    Path(f"{truncated_path}.manifest.json").write_text(
        Path(f"{out_path}.manifest.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    ok_trunc, errs_trunc = verify_audit_bundle(truncated_path)
    assert ok_trunc is False
    assert any("record_count" in e or "chain_head_sha256" in e for e in errs_trunc)


def test_export_csv_bundle_and_tamper_detection(tmp_path: Path) -> None:
    db_path = tmp_path / "audit.sqlite3"
    _seed_db(db_path)
    engine = AuditQueryEngine(db_path)

    out_path = tmp_path / "audit.csv"
    manifest = engine.export_audit_bundle(out_path, fmt="csv")
    assert manifest["schema"] == "audit-bundle-v1"
    assert manifest["format"] == "csv"
    assert manifest["record_count"] == 4

    ok, errors = verify_audit_bundle(out_path)
    assert ok is True
    assert errors == []

    # Tamper a denormalized CSV column -> must fail verification.
    with out_path.open("r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
        fieldnames = list(rows[0].keys())
    rows[0]["status"] = "blocked"
    with out_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    ok_after, errs_after = verify_audit_bundle(out_path)
    assert ok_after is False
    assert errs_after


def test_cli_export_and_verify_bundle_exit_codes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = tmp_path / "cli_audit.sqlite3"
    _seed_db(db_path)
    out_path = tmp_path / "cli_bundle.jsonl"

    rc_export = cli_main(
        [
            "export",
            "--db",
            str(db_path),
            "--out",
            str(out_path),
            "--format",
            "jsonl",
            "--min-risk",
            "0.5",
            "--json",
        ]
    )
    assert rc_export == 0
    export_manifest = json.loads(capsys.readouterr().out)
    assert export_manifest["schema"] == "audit-bundle-v1"
    assert export_manifest["record_count"] == 2

    rc_verify = cli_main(["verify-bundle", str(out_path), "--json"])
    assert rc_verify == 0
    verify_result = json.loads(capsys.readouterr().out)
    assert verify_result["valid"] is True
    assert verify_result["errors"] == []

    # Tamper bundle and verify CLI exits non-zero.
    raw = out_path.read_text(encoding="utf-8")
    out_path.write_text(raw.replace("deviceweave:unlock", "deviceweave:hacked"), encoding="utf-8")

    rc_verify_bad = cli_main(["verify-bundle", str(out_path)])
    assert rc_verify_bad == 1
    captured = capsys.readouterr()
    assert "INVALID" in captured.err
