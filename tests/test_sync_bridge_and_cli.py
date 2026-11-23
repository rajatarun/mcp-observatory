"""Tests for EncryptedSyncBridge (AES-256-GCM) and local SQLite inspector CLI."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.exceptions import InvalidTag

from mcp_observatory.cli import compute_sqlite_stats
from mcp_observatory.cli import main as cli_main
from mcp_observatory.core.context import TraceContext
from mcp_observatory.exporters import (
    EncryptedSyncBridge,
    SQLiteSpanExporter,
    decrypt_envelope,
    encrypt_spans,
)


def _make_span(
    *,
    service: str = "weaveos",
    tool_name: str = "deviceweave:status",
    latency_ms: float = 50.0,
    gate_blocked: bool = False,
    policy_decision: str | None = "allow",
    fallback_reason: str | None = None,
) -> TraceContext:
    start = datetime(2026, 11, 23, 12, 0, 0, tzinfo=UTC)
    end = start + timedelta(milliseconds=latency_ms)
    return TraceContext(
        service=service,
        operation="invoke_tool",
        tool_name=tool_name,
        start_time=start,
        end_time=end,
        gate_blocked=gate_blocked,
        policy_decision=policy_decision,
        fallback_reason=fallback_reason,
    )


def test_aes_256_gcm_roundtrip_and_tamper_rejection() -> None:
    key = os.urandom(32)
    spans = [
        {"trace_id": "t-1", "service": "weaveos", "operation": "invoke_tool"},
        {"trace_id": "t-2", "service": "deviceweave", "operation": "invoke_tool"},
    ]

    envelope = encrypt_spans(spans, key)
    assert envelope["version"] == 1
    assert envelope["alg"] == "AES-256-GCM"
    assert envelope["span_count"] == 2
    assert len(base64.b64decode(envelope["nonce_b64"])) == 12

    recovered = decrypt_envelope(envelope, key)
    assert recovered == spans

    # Tampering with ciphertext must fail GCM authentication.
    raw_ct = bytearray(base64.b64decode(envelope["ciphertext_b64"]))
    raw_ct[0] ^= 0xFF
    tampered = {**envelope, "ciphertext_b64": base64.b64encode(bytes(raw_ct)).decode("ascii")}
    with pytest.raises(InvalidTag):
        decrypt_envelope(tampered, key)

    # Wrong key must also fail.
    with pytest.raises(InvalidTag):
        decrypt_envelope(envelope, os.urandom(32))

    # Invalid key length rejected.
    with pytest.raises(ValueError, match="32 bytes"):
        encrypt_spans(spans, b"short-key")


def test_sync_bridge_failed_transport_leaves_spans_unflushed(tmp_path: Path) -> None:
    db_path = tmp_path / "sync_fail.sqlite3"
    exporter = SQLiteSpanExporter(db_path)
    key = os.urandom(32)

    async def _seed() -> None:
        await exporter.export(_make_span(latency_ms=25.0))
        await exporter.export(_make_span(latency_ms=40.0))

    asyncio.run(_seed())
    assert len(exporter.pending()) == 2

    # Non-2xx status leaves spans pending.
    bridge_503 = EncryptedSyncBridge(exporter, key=key, transport=lambda _env: 503)
    res_503 = bridge_503.sync_once(limit=10)
    assert res_503.ok is False
    assert res_503.status_code == 503
    assert res_503.flushed_count == 0
    assert len(exporter.pending()) == 2

    # Transport exception also leaves spans pending.
    def _boom(_env: dict) -> int:
        raise ConnectionError("offline")

    bridge_err = EncryptedSyncBridge(exporter, key=key, transport=_boom)
    res_err = bridge_err.sync_once(limit=10)
    assert res_err.ok is False
    assert res_err.flushed_count == 0
    assert res_err.error is not None and "ConnectionError" in res_err.error
    assert len(exporter.pending()) == 2

    exporter.close()


def test_sync_bridge_successful_transport_flushes_and_receiver_decrypts(tmp_path: Path) -> None:
    db_path = tmp_path / "sync_ok.sqlite3"
    exporter = SQLiteSpanExporter(db_path)
    key = os.urandom(32)

    async def _seed() -> None:
        await exporter.export(_make_span(tool_name="tool_a", latency_ms=15.0))
        await exporter.export(_make_span(tool_name="tool_b", latency_ms=30.0))
        await exporter.export(_make_span(tool_name="tool_c", latency_ms=45.0))

    asyncio.run(_seed())

    received_envelopes: list[dict] = []

    def _ok_transport(envelope: dict) -> int:
        received_envelopes.append(envelope)
        return 202

    bridge = EncryptedSyncBridge(exporter, key=key, transport=_ok_transport)
    results = bridge.sync_all(batch_size=2)
    assert len(results) == 2
    assert all(r.ok for r in results)
    assert [r.flushed_count for r in results] == [2, 1]
    assert exporter.pending() == []

    # Receiver decrypts every batch and recovers all 3 tool names.
    recovered_tools: list[str] = []
    for env in received_envelopes:
        batch = EncryptedSyncBridge.decrypt_envelope(env, key)
        recovered_tools.extend(item["tool_name"] for item in batch)
    assert recovered_tools == ["tool_a", "tool_b", "tool_c"]

    exporter.close()


def test_cli_stats_json_and_human_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = tmp_path / "stats.sqlite3"
    exporter = SQLiteSpanExporter(db_path)

    async def _seed() -> None:
        # 5 spans with known latencies: 10, 20, 30, 40, 100 ms
        await exporter.export(_make_span(latency_ms=10.0, policy_decision="allow"))
        await exporter.export(_make_span(latency_ms=20.0, policy_decision="allow"))
        await exporter.export(_make_span(latency_ms=30.0, gate_blocked=True, policy_decision="block"))
        await exporter.export(_make_span(latency_ms=40.0, policy_decision="error"))
        await exporter.export(_make_span(latency_ms=100.0, policy_decision="allow"))

    asyncio.run(_seed())
    # Mark first 2 spans as flushed.
    pending = exporter.pending(limit=2)
    exporter.mark_flushed([row_id for row_id, _ in pending])
    exporter.close()

    # Verify JSON output via CLI main().
    rc = cli_main(["stats", "--db", str(db_path), "--json"])
    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)

    assert payload["total_spans"] == 5
    assert payload["flushed_spans"] == 2
    assert payload["pending_spans"] == 3
    assert payload["error_count"] == 1
    assert payload["error_rate"] == pytest.approx(0.2)
    assert payload["blocked_count"] == 1
    assert payload["block_rate"] == pytest.approx(0.2)
    assert payload["latency_samples"] == 5
    # Sorted: [10, 20, 30, 40, 100] -> p50 = 30.0, p95 = 40 + 0.8*(100-40) = 88.0
    assert payload["p50_latency_ms"] == pytest.approx(30.0)
    assert payload["p95_latency_ms"] == pytest.approx(88.0)

    # Verify human-readable output works too.
    rc_human = cli_main(["stats", "--db", str(db_path)])
    assert rc_human == 0
    human_out = capsys.readouterr().out
    assert "total_spans" in human_out
    assert "p95_latency" in human_out

    # Direct API check on empty DB.
    empty_db = tmp_path / "empty.sqlite3"
    empty_exp = SQLiteSpanExporter(empty_db)
    empty_exp.close()
    empty_stats = compute_sqlite_stats(empty_db)
    assert empty_stats["total_spans"] == 0
    assert empty_stats["p50_latency_ms"] is None
    assert empty_stats["p95_latency_ms"] is None
