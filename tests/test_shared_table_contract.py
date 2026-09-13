"""The shared OBSERVATORY_METRICS table is a cross-repository interface.

Several weave services write span telemetry into one DynamoDB table and two
of them build dashboards by querying it. None of those repositories can
import another's code, so nothing but agreement keeps the rows mutually
legible. ``contracts/observatory_metrics_item.json`` is that agreement, and
this file checks the library's own exporter against it.

The interesting assertion here is not that the exporter emits well-formed
rows -- it does -- but the last one: the namespace it writes has no reader.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contracts.conformance import check_item, load_contract, readers_for  # noqa: E402

from mcp_observatory.aws.dynamodb_exporter import DynamoDBSpanExporter  # noqa: E402
from mcp_observatory.core.context import TraceContext  # noqa: E402


def run(coro):
    return asyncio.run(coro)


class _FakeTable:
    def __init__(self) -> None:
        self.items: list[dict] = []

    def put_item(self, *, Item: dict) -> None:
        self.items.append(Item)


def _emit(**kwargs) -> dict:
    """Export one span through the real exporter and return the item it wrote."""
    exporter = DynamoDBSpanExporter(table_name="unit-test-table")
    table = _FakeTable()
    exporter._table = table  # bypass boto3; we are testing the item, not the client
    run(exporter.export(TraceContext(service="unit-test", **kwargs)))
    assert len(table.items) == 1
    return table.items[0]


def test_exported_item_satisfies_the_shared_contract() -> None:
    """Key spelling, pk grammar, sk ordering and ttl -- invariants I1 to I4."""
    item = _emit(model="claude-haiku", tool_name="transfer_funds")
    assert check_item(item) == []


def test_key_attributes_are_lower_case() -> None:
    """I1, called out on its own because getting it wrong fails silently.

    A writer that spells these 'PK'/'SK' has every PutItem rejected with a
    ValidationException, and every such writer in this portfolio wraps the
    call in a bare except, so the failure is reported as success.
    """
    item = _emit(tool_name="t")
    assert "pk" in item and "sk" in item
    assert "PK" not in item and "SK" not in item


def test_sort_key_orders_by_time_so_range_queries_work() -> None:
    """I3: readers range-query sk as a string, so the timestamp must lead."""
    item = _emit(tool_name="t")
    timestamp, _, trace = item["sk"].partition("#")
    assert trace, "sk must carry the trace id after the timestamp"
    assert timestamp.startswith("20"), f"sk must start with an ISO timestamp, got {item['sk']!r}"


def test_the_namespace_this_exporter_writes_has_no_reader() -> None:
    """A pinned statement of a live platform gap, not an endorsement of it.

    The library exporter writes ``SPAN#{tool or model}``. Both dashboard
    readers in the portfolio (TeamWeave's agent-metrics and unified
    observability handlers, DeployWeave's model selector) query only
    ``OBSERVATORY#{operation}`` partitions. So a service that migrates from
    its vendored copy onto this exporter -- which is exactly what platform
    edge E2 asks every service to do -- keeps paying to write telemetry that
    no dashboard will ever show.

    This test passes today because the contract records the gap honestly
    (status=unread). It fails the moment someone adds a reader without
    updating the registry, or renames the namespace, which is when the
    portfolio needs to notice.
    """
    item = _emit(tool_name="transfer_funds")
    assert item["pk"].startswith("SPAN#")
    assert readers_for(item["pk"]) == []
    assert load_contract()["namespace_registry"]["SPAN"]["status"] == "unread"


@pytest.mark.parametrize(
    "pk,expected_readers",
    [
        ("OBSERVATORY#invoke_model", 3),   # what the vendored copies write: read by all three
        ("OBSERVATORY#invoke_agent", 3),
        ("OBSERVATORY#screenshot", 0),     # ScreenWeave's shape: registered namespace, unread key
        ("SPAN#anything", 0),              # this library's own shape
        ("WRAPPER#call_tool", 0),          # ToolWeave's shape
    ],
)
def test_reader_reachability_is_explicit_per_namespace(pk: str, expected_readers: int) -> None:
    """Which writers are actually visible to a dashboard, stated as data.

    ScreenWeave is the subtle one: it uses the registered OBSERVATORY
    namespace but puts a tool name where readers enumerate a fixed list of
    operations, so its rows land in partitions nothing queries.
    """
    assert len(readers_for(pk)) == expected_readers
