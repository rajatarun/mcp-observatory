"""The E10 claim: one view spanning TeamWeave's spans and ContextWeave's router.

`GET /observability` joins two services. Its interesting property is how it
degrades: three sections, each of which can fail independently *without*
failing the request, and each of which is either its data or an `{error: ...}`
object. The status is always 200.

That makes two live conditions indistinguishable from the body alone -- a
ContextWeave that is not configured, and one that is configured but
unreachable. The `ContextWeaveUrl` stack output exists precisely to tell them
apart, and this suite uses it to decide which assertion is the right one.
"""
from __future__ import annotations

import pytest

from conftest import json_of, require

SECTIONS = ("observatoryMetrics", "routingGraph", "routingDecisions")


def test_unified_view_returns_every_section(env, http):
    base = require(env, "teamweave", "api_base")["api_base"]
    url = f"{base}/observability"
    r = http.get(url)
    assert r.status_code == 200, f"{url} -> {r.status_code}: {r.text[:300]}"
    body = json_of(r, url)

    assert "generatedAt" in body, f"{url} returned {sorted(body)} with no generatedAt"
    for section in SECTIONS:
        assert section in body, (
            f"{url} omits the {section!r} section entirely. Absent is not the same as "
            f"null: null means 'not configured', and a missing key means the handler "
            f"changed shape."
        )


def test_observatory_metrics_section_is_data_not_an_error(env, http):
    """The one section that must work: it reads TeamWeave's own table."""
    base = require(env, "teamweave", "api_base")["api_base"]
    url = f"{base}/observability"
    body = json_of(http.get(url), url)
    metrics = body["observatoryMetrics"]

    assert isinstance(metrics, dict), f"observatoryMetrics is {type(metrics).__name__}"
    if "error" in metrics:
        pytest.fail(
            f"observatoryMetrics reports an error against a table this stack owns: "
            f"{metrics['error']!r}. This section does not depend on any other service."
        )
    for key in ("aggregate", "groups", "total_count", "scanned_count"):
        assert key in metrics, f"observatoryMetrics missing {key!r}: {sorted(metrics)}"
    assert metrics["aggregate"] == "by_operation"
    assert metrics["scanned_count"] >= metrics["total_count"], (
        "scanned_count is below total_count, which cannot happen: you cannot "
        "aggregate more rows than you read."
    )


def test_contextweave_sections_match_whether_it_is_configured(env, http):
    """null when unconfigured, data or an error object when configured.

    Reading ContextWeaveUrl is what makes this assertable at all -- without it,
    `routingGraph: null` is ambiguous between "optional dependency absent" and
    "dependency down", which are opposite conclusions.
    """
    tw = require(env, "teamweave", "api_base")
    url = f"{tw['api_base']}/observability"
    body = json_of(http.get(url), url)
    configured = bool(tw.get("contextweave_url"))

    for section in ("routingGraph", "routingDecisions"):
        value = body[section]
        if not configured:
            assert value is None, (
                f"ContextWeaveUrl is empty on this stack, so {section} should be null "
                f"(not configured), but it is {type(value).__name__}."
            )
            continue
        assert value is not None, (
            f"ContextWeaveUrl is set to {tw['contextweave_url']!r}, so {section} must be "
            f"either its data or an error object -- null means the handler thinks "
            f"ContextWeave is unconfigured while the stack says it is."
        )
        if isinstance(value, dict) and set(value) == {"error"}:
            pytest.xfail(
                f"ContextWeave is configured at {tw['contextweave_url']} but {section} "
                f"reports {value['error']!r}. The join degraded exactly as designed; "
                f"the dependency is down."
            )


def test_the_joined_routing_graph_is_contextweaves_own(env, http):
    """The join must forward ContextWeave's answer, not a stale or invented copy.

    Both are queried directly and the question-type sets compared. Anything else
    means the unified view is showing something ContextWeave does not say.
    """
    tw = require(env, "teamweave", "api_base")
    cw = require(env, "contextweave", "api_base")
    if not tw.get("contextweave_url"):
        pytest.skip("TeamWeave has no ContextWeaveUrl configured; nothing is being joined")

    unified_url = f"{tw['api_base']}/observability"
    unified = json_of(http.get(unified_url), unified_url)["routingGraph"]
    if not isinstance(unified, dict) or set(unified) == {"error"}:
        pytest.skip(f"unified routingGraph unavailable: {unified}")

    direct_url = f"{cw['api_base']}/health"
    direct = json_of(http.get(direct_url), direct_url).get("routingGraph")
    if not direct:
        pytest.skip("ContextWeave /health returned no routingGraph to compare against")

    joined_types = set((unified.get("health") or {}).get("questionTypes") or {})
    direct_types = set((direct.get("health") or {}).get("questionTypes") or {})
    if not joined_types and not direct_types:
        pytest.skip("neither side reports question types yet")

    assert joined_types == direct_types, (
        f"the unified view reports question types {sorted(joined_types)} while "
        f"ContextWeave itself reports {sorted(direct_types)}. The join is not "
        f"forwarding the live graph."
    )
