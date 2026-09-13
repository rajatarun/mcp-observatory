"""mcp_observatory.aws: DynamoDBSpanExporter and build_gate, with boto3 stubbed.

The autouse fixture in conftest.py sets MCP_OBSERVATORY_ALLOW_DEV_SECRET=1
for the whole suite, so build_gate() here resolves to the library's known
development commit secret unless a test says otherwise.
"""

from __future__ import annotations

import asyncio
import importlib
import sys
from decimal import Decimal

import pytest

from mcp_observatory.core.context import TraceContext
from mcp_observatory.proposal_commit.storage import InMemoryStorage
from mcp_observatory.utils.secrets import InsecureDefaultSecretError


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Importability without boto3
# ---------------------------------------------------------------------------


def test_aws_package_imports_without_boto3(monkeypatch: pytest.MonkeyPatch) -> None:
    """`import mcp_observatory.aws` must not require boto3 to be installed."""
    for name in list(sys.modules):
        if name == "boto3" or name.startswith("boto3."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setitem(sys.modules, "boto3", None)  # makes `import boto3` raise ImportError

    for name in list(sys.modules):
        if name.startswith("mcp_observatory.aws"):
            monkeypatch.delitem(sys.modules, name, raising=False)

    module = importlib.import_module("mcp_observatory.aws")
    assert hasattr(module, "DynamoDBSpanExporter")
    assert hasattr(module, "build_gate")


# ---------------------------------------------------------------------------
# DynamoDBSpanExporter
# ---------------------------------------------------------------------------


class _FakeTable:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def put_item(self, *, Item: dict) -> None:
        self.items.append(Item)


class _FakeResource:
    def __init__(self) -> None:
        self.table = _FakeTable()

    def Table(self, name: str) -> _FakeTable:
        self.table.name = name
        return self.table


def _make_span(**overrides) -> TraceContext:
    span = TraceContext(service="unit-test", model="gpt-4o-mini", tool_name="transfer_funds")
    span.prompt_tokens = 12
    span.completion_tokens = 5
    span.cost_usd = 0.0123
    span.composite_risk_score = 0.42
    span.policy_decision = "ALLOW"
    span.fallback_reason = None
    for key, value in overrides.items():
        setattr(span, key, value)
    span.finish()
    return span


def test_dynamodb_exporter_requires_a_table_name(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_observatory.aws import DynamoDBSpanExporter

    monkeypatch.delenv("OBSERVATORY_METRICS_TABLE", raising=False)
    with pytest.raises(ValueError):
        DynamoDBSpanExporter()


def test_dynamodb_exporter_reads_table_name_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_observatory.aws import DynamoDBSpanExporter

    monkeypatch.setenv("OBSERVATORY_METRICS_TABLE", "from-env-table")
    resource = _FakeResource()
    exporter = DynamoDBSpanExporter(resource=resource)
    assert exporter._table_name == "from-env-table"


def test_dynamodb_exporter_writes_pk_sk_ttl_and_converts_floats() -> None:
    from mcp_observatory.aws import DynamoDBSpanExporter

    resource = _FakeResource()
    exporter = DynamoDBSpanExporter(table_name="metrics", ttl_seconds=60, resource=resource)
    span = _make_span()

    run(exporter.export(span))

    assert len(resource.table.items) == 1
    item = resource.table.items[0]

    assert item["pk"] == "SPAN#transfer_funds"
    assert item["sk"] == f"{span.start_time.isoformat()}#{span.trace_id}"
    assert isinstance(item["ttl"], int)
    assert item["ttl"] > 0

    # Floats must be Decimal (boto3's Table resource rejects float).
    assert item["cost_usd"] == Decimal("0.0123")
    assert isinstance(item["cost_usd"], Decimal)
    assert item["composite_risk_score"] == Decimal("0.42")

    # None-valued fields are omitted, not written as null.
    assert "fallback_reason" not in item
    assert item["policy_decision"] == "ALLOW"
    assert item["tool_name"] == "transfer_funds"


def test_dynamodb_exporter_export_is_best_effort_on_failure() -> None:
    """A broken table (or missing boto3) must not raise out of export()."""
    from mcp_observatory.aws import DynamoDBSpanExporter

    class _BoomTable:
        def put_item(self, *, Item: dict) -> None:
            raise RuntimeError("dynamodb is down")

    class _BoomResource:
        def Table(self, name: str) -> _BoomTable:
            return _BoomTable()

    exporter = DynamoDBSpanExporter(table_name="metrics", resource=_BoomResource())
    run(exporter.export(_make_span()))  # must not raise


def test_dynamodb_exporter_get_table_raises_clearly_without_boto3(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_observatory.aws import DynamoDBSpanExporter

    monkeypatch.setitem(sys.modules, "boto3", None)
    exporter = DynamoDBSpanExporter(table_name="metrics")
    with pytest.raises(RuntimeError, match="boto3"):
        exporter._get_table()


# ---------------------------------------------------------------------------
# build_gate
# ---------------------------------------------------------------------------


def test_build_gate_wires_a_working_propose_commit_flow() -> None:
    from mcp_observatory.aws import build_gate

    proposer, verifier, token_manager = build_gate(storage=InMemoryStorage())

    proposed = run(
        proposer.propose(
            tool_name="transfer_funds",
            tool_args={"amount": 10, "to": "acct_1"},
            prompt="transfer",
            candidate_output_a="ok",
            candidate_output_b="ok",
        )
    )
    assert proposed["status"] == "allowed"

    verification = run(
        verifier.verify_commit(
            proposal_id=proposed["proposal_id"],
            commit_token=proposed["commit_token"],
            tool_name="transfer_funds",
            tool_args={"amount": 10, "to": "acct_1"},
        )
    )
    assert verification.ok is True

    # Same token manager instance backs both sides.
    assert token_manager.verify(proposed["commit_token"]).valid is True


def test_build_gate_uses_the_named_secret_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_observatory.aws import build_gate

    monkeypatch.delenv("MCP_OBSERVATORY_ALLOW_DEV_SECRET", raising=False)
    monkeypatch.setenv("OBSERVATORY_SECRET_KEY", "a-real-secret")

    _, _, token_manager = build_gate(secret_env="OBSERVATORY_SECRET_KEY", storage=InMemoryStorage())
    assert token_manager.secret == b"a-real-secret"


def test_build_gate_fails_closed_without_a_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_observatory.aws import build_gate

    monkeypatch.delenv("MCP_OBSERVATORY_ALLOW_DEV_SECRET", raising=False)
    monkeypatch.delenv("OBSERVATORY_SECRET_KEY", raising=False)

    with pytest.raises(InsecureDefaultSecretError):
        build_gate(secret_env="OBSERVATORY_SECRET_KEY", storage=InMemoryStorage())


def test_build_gate_respects_block_threshold_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from mcp_observatory.aws import build_gate

    monkeypatch.setenv("OBSERVATORY_BLOCK_THRESHOLD", "0.0")
    proposer, _, _ = build_gate(block_threshold_env="OBSERVATORY_BLOCK_THRESHOLD", storage=InMemoryStorage())

    proposed = run(
        proposer.propose(
            tool_name="transfer_funds",
            tool_args={"amount": 10},
            prompt="transfer",
            candidate_output_a="alpha response",
            candidate_output_b="totally different beta response",
        )
    )
    # Any nonzero instability now exceeds a 0.0 threshold, so it blocks.
    assert proposed["status"] == "blocked"
