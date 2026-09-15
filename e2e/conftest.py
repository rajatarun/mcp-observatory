"""Fixtures for the live platform E2E suite.

Three rules this file enforces, because a suite that runs against production
can do real damage and can also lie about what it proved.

1. **Read-mostly by default.** Tests that write are marked `@pytest.mark.writes`
   and are deselected unless WEAVE_E2E_ALLOW_WRITES=1. The writes that exist are
   deliberately small and additive (a question, a rating). Nothing in this suite
   deletes, and nothing calls an endpoint that sends real email --
   `POST /admin/newsletter/actions/send` mails the live subscriber list with no
   dry run, so it is never called here and has no test.

2. **Skip, never fail, on absence.** A stack that is not deployed, or an output
   a service does not publish, produces a skip naming exactly what was missing.
   A skipped integration test and a broken integration are different facts and
   must not look alike in a report.

3. **No secret ever loaded.** Secret ARNs are resolved so a test can assert they
   exist; their contents are not read.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import platform_env as pe  # noqa: E402

DEFAULT_TIMEOUT = float(os.environ.get("WEAVE_E2E_TIMEOUT", "30"))


def pytest_configure(config):
    config.addinivalue_line("markers", "writes: mutates live state; needs WEAVE_E2E_ALLOW_WRITES=1")
    config.addinivalue_line("markers", "slow: polls a live async pipeline")


def pytest_collection_modifyitems(config, items):
    if os.environ.get("WEAVE_E2E_ALLOW_WRITES") == "1":
        return
    skip = pytest.mark.skip(reason="write test; set WEAVE_E2E_ALLOW_WRITES=1 to run it")
    for item in items:
        if "writes" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def env() -> pe.PlatformEnv:
    """Every live coordinate, resolved once from CloudFormation."""
    if not os.environ.get("WEAVE_E2E_ENV_FILE"):
        try:
            import boto3  # noqa: F401,PLC0415
        except ImportError:
            pytest.skip("boto3 is not installed; pip install -r e2e/requirements-e2e.txt")
    resolved = pe.resolve(os.environ.get("AWS_REGION", "us-east-1"))
    if not resolved.services:
        pytest.skip(
            "no stack was readable -- check AWS credentials and region. "
            f"Tried: {', '.join(sorted(pe.STACKS.values()))}"
        )
    return resolved


@pytest.fixture(scope="session")
def http():
    """A requests session with a default timeout and no retries.

    No retries on purpose: this suite is measuring whether the live platform
    answers, and a retry turns "answered on the third try" into "answered",
    which is the thing you most want to know about a production endpoint.
    """
    requests = pytest.importorskip("requests")

    class _Client:
        def __init__(self):
            self.s = requests.Session()
            self.s.headers["User-Agent"] = "weave-e2e/1.0"

        def request(self, method, url, **kw):
            kw.setdefault("timeout", DEFAULT_TIMEOUT)
            return self.s.request(method, url, **kw)

        def get(self, url, **kw):
            return self.request("GET", url, **kw)

        def post(self, url, **kw):
            return self.request("POST", url, **kw)

    return _Client()


def require(env: pe.PlatformEnv, service: str, *keys: str) -> dict:
    """Return the service's coordinates, or skip with the precise reason."""
    if not env.has(service, *keys):
        pytest.skip(env.why_missing(service, *keys))
    return env.services[service]


def json_of(response, url: str):
    """Parse a JSON body, failing with the status and a snippet if it is not JSON."""
    try:
        return response.json()
    except ValueError:
        pytest.fail(
            f"{url} returned {response.status_code} with a non-JSON body: "
            f"{response.text[:300]!r}"
        )


def poll_until(predicate, timeout: float, interval: float = 5.0, describe: str = ""):
    """Poll a live async pipeline until predicate returns a truthy value.

    Returns the value, or None on timeout -- the caller decides whether a
    timeout is a failure, because for some pipelines "still running after N
    seconds" is a legitimate outcome rather than a defect.
    """
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    return None
