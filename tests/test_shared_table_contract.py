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


def test_rows_are_reachable_without_anyone_agreeing_on_the_pk_prefix() -> None:
    """The v2 property, and the whole point of moving reads onto a GSI.

    Under v1 a reader queried whole partitions by exact pk, so this exporter's
    ``SPAN#`` rows were invisible to every dashboard -- and a service migrating
    onto this exporter (platform edge E2) silently vanished from them. The fix
    was not to make this writer guess the readers' prefix grammar, but to stop
    reads depending on the prefix at all: SpanTimelineIndex is keyed on
    ``span_date`` and ``timestamp``, which this exporter sets, so the row is
    reachable whatever its pk says.
    """
    item = _emit(tool_name="transfer_funds")
    contract = load_contract()
    gsi = contract["gsi"]

    assert item["pk"].startswith("SPAN#"), "pk is still the writer's own business"
    for key in (gsi["partition_key"], gsi["sort_key"]):
        assert key in item, f"{key} missing: the row would not be in {gsi['name']}"
    assert item["span_date"] == item["timestamp"][:10]
    assert check_item(item) == []


def test_omitting_an_index_attribute_is_caught_rather_than_silent() -> None:
    """Invisibility must fail a test, not merely happen.

    A GSI indexes only items carrying both of its keys, so a writer that drops
    one is exactly as invisible as the v1 prefix mismatches were. The only
    difference worth having is that this one is noisy.
    """
    item = _emit(tool_name="t")
    for missing in ("span_date", "timestamp", "operation"):
        broken = {k: v for k, v in item.items() if k != missing}
        problems = check_item(broken)
        assert problems, f"dropping {missing} produced no contract violation"
        assert any(missing in p for p in problems)


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
    """Historical, kept for rows written before v2.

    ``readers_for`` answers "which dashboard would have found this row by its
    partition key", which under v1 was the only way a row was ever found. Rows
    written before the SpanTimelineIndex migration have no ``span_date`` and so
    are not in the index; this is still how they are reached. New rows do not
    depend on any of it.
    """
    assert len(readers_for(pk)) == expected_readers
