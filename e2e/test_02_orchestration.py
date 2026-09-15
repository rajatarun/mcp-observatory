"""TeamWeave: is a run actually asynchronous, and does it reach a terminal state?

The contract a client has to get right here is the one a status code hides:

* every write returns **202** with a run_id and nothing has happened yet;
* a **FAILED run is a 200** -- the failure is in the body.

A harness that checks only the HTTP status records every failed run as a pass,
which is worse than having no test, so both halves are asserted explicitly.
"""
from __future__ import annotations

import os

import pytest

from conftest import json_of, poll_until, require

TERMINAL = {"SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED"}
RUN_TIMEOUT = float(os.environ.get("WEAVE_E2E_RUN_TIMEOUT", "300"))


def test_status_endpoint_rejects_an_unknown_run(env, http):
    """A run_id that cannot exist must 404, not 200 with an empty body.

    Read-only, and it is the cheapest possible check that the status route is
    wired to Step Functions rather than to a stub that answers anything.
    """
    base = require(env, "teamweave", "api_base")["api_base"]
    url = f"{base}/team/task/e2e-definitely-not-a-real-run-id"
    r = http.get(url)
    assert r.status_code in (400, 404), (
        f"{url} -> {r.status_code} for a run that cannot exist. "
        f"A 200 here means the status endpoint is not reading the execution."
    )


def test_improve_tasks_is_readable(env, http):
    """GET /improve/tasks is the one synchronous read on the orchestration API."""
    base = require(env, "teamweave", "api_base")["api_base"]
    url = f"{base}/improve/tasks?limit=1"
    r = http.get(url)
    assert r.status_code == 200, f"{url} -> {r.status_code}: {r.text[:200]}"
    body = json_of(r, url)
    assert "items" in body, f"{url} returned {sorted(body)}, with no items key"
    assert isinstance(body["items"], list)


@pytest.mark.writes
@pytest.mark.slow
def test_a_run_is_accepted_asynchronously_and_terminates(env, http):
    """POST /team/task must 202 with a run_id, and that run must reach a terminal state.

    A FAILED run does not fail this test. The claim under test is that the
    pipeline accepts work asynchronously and finishes it -- whether the agents
    produced a good answer is a different question and not one an integration
    test should adjudicate. What would fail: a synchronous 200, a missing
    run_id, or a run still RUNNING past the timeout.
    """
    base = require(env, "teamweave", "api_base")["api_base"]
    team = os.environ.get("WEAVE_E2E_TEAM")
    version = os.environ.get("WEAVE_E2E_TEAM_VERSION")
    if not team or not version:
        pytest.skip(
            "set WEAVE_E2E_TEAM and WEAVE_E2E_TEAM_VERSION to a team config that exists "
            "in the live config bucket. Starting a run against a guessed team name would "
            "either fail meaninglessly or run a real pipeline nobody asked for."
        )

    url = f"{base}/team/task"
    r = http.post(url, json={"team": team, "version": version,
                             "request": {"source": "weave-e2e", "prompt": "health probe"}})
    assert r.status_code == 202, (
        f"{url} -> {r.status_code}, expected 202. A 200 would mean the API had become "
        f"synchronous, and every client that polls a run_id would break."
    )
    accepted = json_of(r, url)
    run_id = accepted.get("run_id")
    assert run_id, f"202 with no run_id: {accepted}. The run cannot be polled."

    status_url = f"{base}/team/task/{run_id}"

    def terminal():
        resp = http.get(status_url)
        if resp.status_code != 200:
            return None
        state = json_of(resp, status_url)
        return state if state.get("status") in TERMINAL else None

    final = poll_until(terminal, timeout=RUN_TIMEOUT, interval=10)
    assert final is not None, (
        f"{run_id} was still non-terminal after {RUN_TIMEOUT}s. "
        f"Raise WEAVE_E2E_RUN_TIMEOUT if this pipeline is legitimately slower."
    )

    # FAILED arrives as a 200 -- assert the body, and surface the cause rather
    # than silently passing on it.
    if final["status"] == "FAILED":
        pytest.xfail(
            f"run {run_id} reached FAILED (a 200, by design): {final.get('error')!r}. "
            f"The orchestration contract held; the pipeline itself did not succeed."
        )
    assert final["status"] == "SUCCEEDED", final
