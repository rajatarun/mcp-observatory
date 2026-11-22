"""ContextWeave: does the knowledge layer answer, and can the answer be rated?

The platform's claim is not "there is a RAG endpoint". It is that the router
learns from outcomes -- so the loop that has to work end to end is:

    POST /query-expertise  ->  an answer carrying a queryId
    POST /feedback         ->  that queryId, rated
    GET  /routing-decisions->  the rating is in the decision log

That whole loop was dead until recently. `POST /feedback` had a handler and no
API Gateway route, so nothing could reach it and the table had never recorded a
single human rating. An endpoint that exists in the code and not in the gateway
is exactly the kind of thing only a live test catches: every unit test passed.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from conftest import json_of, require

CONTRACT = json.loads(
    (Path(__file__).parent / "contracts" / "contextweave_http_api.json").read_text(encoding="utf-8")
)


def _required(endpoint: str, key: str = "required_top_level_keys") -> list:
    return CONTRACT["endpoints"][endpoint][key]


def test_health_reports_routing_graph_health(env, http):
    """GET /health carries the router's learning-loop verdict.

    `starved` is the signature of a router that has stopped exploring -- one
    strategy heavily observed while its siblings have none. A frozen router and
    a converged one log identically, so this verdict is the only thing that
    distinguishes them, and it is worth checking it is actually being computed
    on the live graph rather than defaulting.
    """
    base = require(env, "contextweave", "api_base")["api_base"]
    url = f"{base}/health"
    r = http.get(url)
    assert r.status_code == 200, f"{url} -> {r.status_code}: {r.text[:200]}"
    body = json_of(r, url)

    for key in _required("GET /health"):
        assert key in body, f"{url} is missing contracted key {key!r}; got {sorted(body)}"

    health = (body.get("routingGraph") or {}).get("health")
    if not health:
        pytest.skip("routingGraph.health absent -- routing graph not seeded on this stack")

    verdicts = {qt: v.get("verdict") for qt, v in (health.get("questionTypes") or {}).items()}
    assert verdicts, "routingGraph.health.questionTypes is empty -- the router has no arms at all"
    legal = {"learning", "converged", "starved"}
    bad = {qt: v for qt, v in verdicts.items() if v not in legal}
    assert not bad, f"unknown verdicts {bad}; the contract allows {sorted(legal)}"

    starved = [qt for qt, v in verdicts.items() if v == "starved"]
    if starved:
        pytest.xfail(
            f"router is starved for {starved} -- one arm is being selected while its "
            f"siblings have no observations. Not an E2E defect; it is the live "
            f"condition this verdict exists to surface."
        )


def test_routing_decisions_summary_is_readable_and_calibrated(env, http):
    """The decision log answers: does self-assessed confidence track real ratings?

    `meanAbsDiff` is AVG(ABS(confidence - rating)) over decisions carrying both.
    Near 0 the model's opinion of its own answer tracks what people think and is
    worth using as the cheap always-available reward; near 0.5 the router has
    been learning from a proxy that measures nothing.

    The assertion here is deliberately about *shape and semantics*, not about
    the number being good -- a live platform is allowed to be badly calibrated,
    and a test that failed on that would be measuring the model, not the wiring.
    """
    base = require(env, "contextweave", "api_base")["api_base"]
    url = f"{base}/routing-decisions?mode=summary"
    r = http.get(url)
    assert r.status_code == 200, f"{url} -> {r.status_code}: {r.text[:200]}"
    body = json_of(r, url)

    for key in _required("GET /routing-decisions?mode=summary"):
        assert key in body, f"{url} is missing contracted key {key!r}; got {sorted(body)}"

    group_keys = CONTRACT["endpoints"]["GET /routing-decisions?mode=summary"]["required_group_keys"]
    for group in body["groups"]:
        missing = [k for k in group_keys if k not in group]
        assert not missing, f"group {group.get('strategy')} missing {missing}"

        # null, never 0.0, for a group nobody has rated: a zero would read as
        # perfect agreement on exactly the groups where nothing is known.
        if group["ratedCount"] == 0:
            assert group["avgRating"] is None, (
                f"group {group.get('questionType')}/{group.get('strategy')} has "
                f"ratedCount 0 but avgRating {group['avgRating']!r}, not null"
            )
            assert group["meanAbsDiff"] is None, (
                f"same group reports meanAbsDiff {group['meanAbsDiff']!r} with nothing rated"
            )

    if body["totalRated"] == 0:
        pytest.skip(
            "no answer on this stack has ever been rated, so calibration cannot be "
            "checked. Run with WEAVE_E2E_ALLOW_WRITES=1 to contribute one."
        )


@pytest.mark.writes
@pytest.mark.slow
def test_query_then_feedback_then_the_rating_is_logged(env, http):
    """The whole learning loop, in one pass, against the live stack.

    This is the test the platform's central claim rests on. It writes: one
    question and one rating. Both are additive and small; nothing is deleted.
    """
    base = require(env, "contextweave", "api_base")["api_base"]
    marker = uuid.uuid4().hex[:8]

    # --- ask -------------------------------------------------------------
    q_url = f"{base}/query-expertise"
    r = http.post(q_url, json={"question": f"What does the routing graph learn from? (e2e {marker})"},
                  timeout=120)
    assert r.status_code == 200, f"{q_url} -> {r.status_code}: {r.text[:300]}"
    answer = json_of(r, q_url)

    for key in _required("POST /query-expertise"):
        assert key in answer, f"{q_url} is missing contracted key {key!r}; got {sorted(answer)}"

    query_id = answer["queryId"]
    assert query_id, "queryId is empty -- without it this answer can never be rated"

    for source in answer["sources"]:
        missing = [k for k in CONTRACT["endpoints"]["POST /query-expertise"]["required_source_keys"]
                   if k not in source]
        assert not missing, f"a source is missing {missing}: {source}"

    # --- rate ------------------------------------------------------------
    f_url = f"{base}/feedback"
    r = http.post(f_url, json={"queryId": query_id, "rating": "up"})
    assert r.status_code == 200, (
        f"{f_url} -> {r.status_code}: {r.text[:300]}\n"
        f"A 404 here with a queryId this fresh means the decision was never recorded; "
        f"a 403/404 from the gateway means the route is missing again."
    )
    feedback = json_of(r, f_url)
    for key in _required("POST /feedback"):
        assert key in feedback, f"{f_url} is missing contracted key {key!r}; got {sorted(feedback)}"
    assert feedback["queryId"] == query_id

    # --- rating is idempotent per queryId --------------------------------
    again = http.post(f_url, json={"queryId": query_id, "rating": "up"})
    assert again.status_code == 409, (
        f"a second rating for {query_id} returned {again.status_code}, not 409. "
        f"One rating per query is what stops a single opinion being counted twice "
        f"into the posterior."
    )

    # --- and it reaches the decision log ----------------------------------
    l_url = f"{base}/routing-decisions?mode=list&limit=100"
    r = http.get(l_url)
    assert r.status_code == 200, f"{l_url} -> {r.status_code}"
    items = json_of(r, l_url)["items"]
    ours = [i for i in items if i.get("queryId") == query_id]
    assert ours, (
        f"{query_id} was answered and rated but does not appear in the decision log. "
        f"The reward has nowhere to be attributed from."
    )
    assert ours[0]["rating"] is not None, (
        f"{query_id} is logged with rating null after a successful POST /feedback -- "
        f"the rating was accepted but not persisted against the decision."
    )
