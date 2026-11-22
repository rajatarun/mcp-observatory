"""Tests for SQLite proposal/commit storage and SQLite span exporter."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from contracts.conformance import check_item
from mcp_observatory.core.context import TraceContext
from mcp_observatory.exporters import SQLiteSpanExporter
from mcp_observatory.proposal_commit import (
    CommitTokenManager,
    CommitVerifier,
    ProposalConfig,
    SQLiteProposalCommitStorage,
    ToolProposer,
    create_storage_from_env,
)


def test_sqlite_proposal_commit_survives_restart_and_blocks_replay(tmp_path: Path):
    db_path = tmp_path / "gate.sqlite3"
    secret = "test-sqlite-hmac-secret-key"

    async def _run():
        storage1 = SQLiteProposalCommitStorage(db_path)
        token_mgr = CommitTokenManager(secret=secret, ttl_seconds=60)
        proposer = ToolProposer(
            storage=storage1,
            token_manager=token_mgr,
            config=ProposalConfig(block_threshold=0.45),
        )
        proposal = await proposer.propose(
            tool_name="close_garage",
            tool_args={"door": "main"},
            prompt="close the main garage door",
            candidate_output_a="close main garage door",
            candidate_output_b="close main garage door",
        )
        assert proposal["status"] == "allowed"
        assert proposal["commit_token"] is not None
        proposal_id = proposal["proposal_id"]
        commit_token = proposal["commit_token"]

        listed = await storage1.list_proposals(decision="allow")
        assert len(listed) == 1
        assert listed[0]["proposal_id"] == proposal_id
        storage1.close()

        # Simulate process restart with a brand-new storage connection on the same file.
        storage2 = SQLiteProposalCommitStorage(db_path)
        verifier = CommitVerifier(storage=storage2, token_manager=CommitTokenManager(secret=secret))
        first = await verifier.verify_commit(
            proposal_id=proposal_id,
            commit_token=commit_token,
            tool_name="close_garage",
            tool_args={"door": "main"},
        )
        assert first.ok is True

        # Replaying the exact same commit token must fail even across restarts.
        storage2.close()
        storage3 = SQLiteProposalCommitStorage(db_path)
        verifier3 = CommitVerifier(storage=storage3, token_manager=CommitTokenManager(secret=secret))
        replay = await verifier3.verify_commit(
            proposal_id=proposal_id,
            commit_token=commit_token,
            tool_name="close_garage",
            tool_args={"door": "main"},
        )
        assert replay.ok is False
        assert replay.reason == "nonce_replay"
        storage3.close()

    asyncio.run(_run())


def test_create_storage_from_env_prefers_sqlite(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "env_gate.sqlite3"
    monkeypatch.setenv("MCP_OBSERVATORY_SQLITE_PATH", str(db_path))
    monkeypatch.delenv("MCP_OBSERVATORY_PG_DSN", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    storage = create_storage_from_env()
    assert isinstance(storage, SQLiteProposalCommitStorage)
    storage.close()


def test_sqlite_span_exporter_conforms_to_contract_and_flushes(tmp_path: Path):
    db_path = tmp_path / "spans.sqlite3"
    exporter = SQLiteSpanExporter(db_path)

    async def _run():
        ctx = TraceContext(
            service="weaveos-test",
            model="qwen2.5-3b",
            tool_name="deviceweave:get_status",
            operation="invoke_tool",
            start_time=datetime.now(timezone.utc),
            prompt_tokens=42,
            completion_tokens=18,
            cost_usd=0.0,
        )
        await exporter.export(ctx)

        recent = exporter.recent(limit=10)
        assert len(recent) == 1
        item = recent[0]
        violations = check_item(item)
        assert violations == [], f"Contract violations: {violations}"
        assert item["pk"] == "OBSERVATORY#invoke_tool"
        assert item["service"] == "weaveos-test"

        pending = exporter.pending()
        assert len(pending) == 1
        row_id, _ = pending[0]
        exporter.mark_flushed([row_id])
        assert exporter.pending() == []

        # Pruning with far-future timestamp removes expired spans.
        removed = exporter.prune_expired(now_epoch=int(time.time()) + 365 * 86400)
        assert removed == 1
        assert exporter.recent() == []

    asyncio.run(_run())
    exporter.close()


def test_sqlite_baseline_prompt_hash_roundtrip(tmp_path: Path):
    storage = SQLiteProposalCommitStorage(tmp_path / "baseline.sqlite3")

    async def _run():
        assert await storage.get_baseline_prompt_hash("unlock") is None
        await storage.set_baseline_prompt_hash("unlock", "hash-v1")
        assert await storage.get_baseline_prompt_hash("unlock") == "hash-v1"
        await storage.set_baseline_prompt_hash("unlock", "hash-v2")
        assert await storage.get_baseline_prompt_hash("unlock") == "hash-v2"

    asyncio.run(_run())
    storage.close()
