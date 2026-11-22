"""DeviceWeave and the MCP surfaces: the modalities where an action is irreversible.

DeviceWeave is the case that makes the gate obviously necessary -- turning a
device off has no undo. So this file is strictly read-only: it never executes an
intent, never authors a policy, and never writes presence. It checks that the
surface is up, that it reports which subsystems are actually configured, and
that its "unconfigured" answers are distinguishable from outages.

The MCP servers (ToolWeave, ScreenWeave) are not exercised over HTTP here. They
speak MCP over a single catch-all route, so a bare GET proves nothing; their
coordinates are asserted to exist so a client can be pointed at them.
"""
from __future__ import annotations

import pytest

from conftest import json_of, require


def test_deviceweave_health_reports_subsystem_configuration(env, http):
    """Always 200, so the body is the only place the real state appears.

    `registry_ok: false` with a `registry_error` means the service is up and the
    catalogue is empty -- not the same thing, and invisible in the status code.
    """
    dw = require(env, "deviceweave", "api_base")
    url = f"{dw['api_base']}/health"
    r = http.get(url)
    assert r.status_code == 200, f"{url} -> {r.status_code}: {r.text[:200]}"
    body = json_of(r, url)

    for key in ("status", "devices", "registry_ok", "scenes", "learning_enabled", "graph_enabled"):
        assert key in body, f"{url} missing {key!r}: {sorted(body)}"

    if not body["registry_ok"]:
        pytest.xfail(
            f"DeviceWeave is up but its device registry is unreadable: "
            f"{body.get('registry_error')!r}. Every /devices read will be empty, with a 503."
        )
    assert isinstance(body["devices"], int)


def test_device_catalogue_is_readable(env, http):
    """503 here means unconfigured, not overloaded -- retrying would never help."""
    dw = require(env, "deviceweave", "api_base")
    url = f"{dw['api_base']}/devices"
    r = http.get(url)
    if r.status_code == 503:
        pytest.skip(f"device registry not configured on this stack: {r.text[:200]}")
    assert r.status_code == 200, f"{url} -> {r.status_code}: {r.text[:200]}"
    body = json_of(r, url)
    assert body["count"] == len(body["devices"]), (
        f"count={body['count']} but {len(body['devices'])} devices returned"
    )


def test_creating_a_device_is_refused(env, http):
    """POST /devices is routed and always 405s: devices come from provider ingest.

    Worth a live test precisely because it is routed -- a client that finds the
    path and expects a create needs the 405 to be real, not a 404 that suggests
    the route is missing.
    """
    dw = require(env, "deviceweave", "api_base")
    url = f"{dw['api_base']}/devices"
    r = http.post(url, json={"id": "e2e-should-never-be-created"})
    assert r.status_code == 405, (
        f"{url} POST -> {r.status_code}, expected 405. If this ever becomes a create, "
        f"a device could be added without going through provider ingest."
    )


def test_presence_defaults_are_distinguishable_from_a_write(env, http):
    """GET /presence defaults to is_home true with a null updated_at.

    The null is the only way to tell "nobody has ever set this" from "someone
    set it to true" -- the policy engine reads the same value either way.
    """
    dw = require(env, "deviceweave", "api_base")
    url = f"{dw['api_base']}/presence"
    r = http.get(url)
    if r.status_code == 503:
        pytest.skip(f"presence store not configured: {r.text[:200]}")
    assert r.status_code == 200, f"{url} -> {r.status_code}"
    body = json_of(r, url)
    assert "is_home" in body and "updated_at" in body, sorted(body)
    assert isinstance(body["is_home"], bool), f"is_home is {body['is_home']!r}, not a boolean"


def test_policy_listing_is_readable(env, http):
    """GET /policies is backed by the device-type GSI the stack publishes."""
    dw = require(env, "deviceweave", "api_base")
    url = f"{dw['api_base']}/policies"
    r = http.get(url)
    if r.status_code == 503:
        pytest.skip(f"policy store not configured: {r.text[:200]}")
    assert r.status_code == 200, f"{url} -> {r.status_code}: {r.text[:200]}"
    body = json_of(r, url)
    assert body["count"] == len(body["policies"]), (
        f"count={body['count']} but {len(body['policies'])} policies returned"
    )


def test_mcp_surfaces_publish_their_coordinates(env):
    """ToolWeave and ScreenWeave speak MCP, so discovery is the thing to assert.

    A bare HTTP GET against a catch-all MCP route proves nothing about whether
    the server works, and MCP has its own handshake. What a client genuinely
    needs is the endpoint and the tables behind it, from the stack.
    """
    found = []
    for service, keys in (("toolweave", ("api_base", "catalog_table", "proposals_table")),
                          ("screenweave", ("mcp_endpoint", "sessions_table"))):
        if env.has(service, *keys):
            found.append(service)
    if not found:
        pytest.skip(
            "neither MCP stack resolved: "
            + env.why_missing("toolweave", "api_base")
            + " / " + env.why_missing("screenweave", "mcp_endpoint")
        )
    for service in found:
        for key, value in env.services[service].items():
            assert value, f"{service}.{key} resolved to an empty value"
