"""The shared telemetry sink: do spans actually arrive, and can they be read?

This is the seam the integration audit found broken twice over (F1, F2). Five
services write to one DynamoDB table; the table was shared but the *item shape*
was not. One writer used `PK`/`SK` against a table keyed `pk`/`sk`, so every
write was rejected and swallowed by a bare `except`. Readers queried a
partition-key prefix grammar each writer had to guess identically.

The contract now pins the shape and reads go through `SpanTimelineIndex`. The
failure mode that makes a live test necessary: a span missing either index key
is not in the index, so no query returns it, and nothing anywhere reports an
error. The telemetry is durable, billable and invisible.

This test reads the table through the same index the readers use, and checks
live rows against the vendored contract.
"""
from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path

import pytest

from conftest import json_of, require

CONTRACT_PATH = Path(__file__).resolve().parents[1] / "contracts" / "observatory_metrics_item.json"
CONTRACT = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _gsi() -> dict:
    gsi = CONTRACT.get("gsi")
    if not gsi:
        pytest.fail(f"{CONTRACT_PATH} has no gsi block; contract v2 defines one")
    return gsi


def test_the_stack_publishes_the_index_the_contract_names(env):
    """The output and the contract must agree on the index name.

    They are maintained in different repositories. If they disagree, a reader
    built from one and a table built from the other silently return nothing.
    """
    tw = require(env, "teamweave", "observatory_table", "span_timeline_index")
    contract_name = _gsi()["name"]
    assert tw["span_timeline_index"] == contract_name, (
        f"the stack publishes index {tw['span_timeline_index']!r} but the contract "
        f"names {contract_name!r}. One of them is wrong and queries will come back empty."
    )


def test_live_spans_conform_to_the_shared_contract(env):
    """Read real rows through the index and validate them.

    Uses today's and yesterday's partitions: span_date is a UTC day bucket, so a
    run just after midnight UTC lands in a partition 'today' does not cover.
    """
    boto3 = pytest.importorskip("boto3")
    tw = require(env, "teamweave", "observatory_table", "span_timeline_index")

    import sys
    sys.path.insert(0, str(CONTRACT_PATH.parent))
    try:
        from conformance import check_item  # type: ignore  # noqa: PLC0415
    except ImportError:
        pytest.skip("contracts/conformance.py not importable; cannot validate item shape")

    ddb = boto3.client("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    gsi = _gsi()
    today = dt.datetime.now(dt.timezone.utc).date()
    days = [(today - dt.timedelta(days=d)).isoformat() for d in (0, 1)]

    items = []
    for day in days:
        resp = ddb.query(
            TableName=tw["observatory_table"],
            IndexName=tw["span_timeline_index"],
            KeyConditionExpression="#p = :d",
            ExpressionAttributeNames={"#p": gsi["partition_key"]},
            ExpressionAttributeValues={":d": {"S": day}},
            Limit=25,
            ScanIndexForward=False,
        )
        items.extend(resp.get("Items", []))

    if not items:
        pytest.skip(
            f"no spans in {tw['span_timeline_index']} for {days}. Either nothing ran, or "
            f"writers are emitting rows without both index keys -- which is invisible "
            f"by construction. Run a pipeline and re-check before believing 'nothing ran'."
        )

    problems = {}
    for item in items[:25]:
        found = check_item(item)
        if found:
            key = (item.get("pk", {}).get("S"), item.get("sk", {}).get("S"))
            problems[key] = found
    assert not problems, (
        f"{len(problems)} of {len(items[:25])} live spans violate "
        f"{CONTRACT_PATH.name} v{CONTRACT.get('version')}:\n"
        + "\n".join(f"  {k}: {v}" for k, v in list(problems.items())[:5])
    )


def test_the_api_reads_the_same_spans_the_table_holds(env, http):
    """GET /observability/agent-metrics must go through the index, not scan.

    A reader that scans still returns rows, so this cannot be proved from the
    response alone. What it does check is that the endpoint answers with the
    documented shape and that its counts are self-consistent -- a truncated
    aggregate reporting more aggregated rows than it scanned would be the
    visible symptom of the scan-limit bug.
    """
    base = require(env, "teamweave", "api_base")["api_base"]
    url = f"{base}/observability/agent-metrics?aggregate=by_operation"
    r = http.get(url)
    assert r.status_code == 200, f"{url} -> {r.status_code}: {r.text[:200]}"
    body = json_of(r, url)

    for key in ("aggregate", "groups", "total_count", "scanned_count"):
        assert key in body, f"{url} missing {key!r}: {sorted(body)}"
    assert body["scanned_count"] >= body["total_count"], (
        f"scanned {body['scanned_count']} but aggregated {body['total_count']} -- "
        f"you cannot aggregate more rows than you read."
    )

    list_url = f"{base}/observability/agent-metrics?limit=5"
    r = http.get(list_url)
    assert r.status_code == 200, f"{list_url} -> {r.status_code}"
    listed = json_of(r, list_url)
    assert listed["count"] == len(listed["items"]), (
        f"count={listed['count']} but {len(listed['items'])} items returned"
    )
    assert listed["count"] <= 5, f"limit=5 returned {listed['count']} items"


def test_an_unknown_operation_is_rejected_not_silently_empty(env, http):
    """A typo must be a 400 naming the accepted values, not an empty result set.

    An empty list for a misspelled filter reads as "there is no such telemetry",
    which is the most expensive possible way to be wrong about a dashboard.
    """
    base = require(env, "teamweave", "api_base")["api_base"]
    url = f"{base}/observability/agent-metrics?operation=invoke_modelz"
    r = http.get(url)
    assert r.status_code == 400, (
        f"{url} -> {r.status_code}. An unknown operation must be rejected; returning "
        f"an empty list would read as 'no such spans'."
    )
