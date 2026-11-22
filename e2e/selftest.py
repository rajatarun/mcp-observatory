#!/usr/bin/env python3
"""Prove the E2E assertions bite, without a live platform.

An end-to-end suite nobody can run is a liability: it looks like coverage and
asserts nothing. This serves a fake platform that is correct by construction,
checks the suite passes against it, then breaks the fake one way at a time and
checks the suite catches each break -- and names which test should catch it.

    python3 e2e/selftest.py

Not named test_*.py on purpose: it must not be collected by the live run.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# ---------------------------------------------------------------- fake bodies
GOOD = {
    "cw/health": {
        "status": "healthy", "environment": "selftest",
        "routingGraph": {"health": {"exploration": 1.0, "priorStrength": 2.0,
            "questionTypes": {"skill_depth": {"verdict": "converged", "leader": "graph_first",
                "leaderPBest": 0.97, "starvedArms": [], "arms": {}}}}},
    },
    "cw/routing-decisions-summary": {
        "groups": [
            {"questionType": "skill_depth", "strategy": "graph_first", "count": 10,
             "ratedCount": 3, "avgConfidence": 0.8, "avgRating": 0.7, "meanAbsDiff": 0.2},
            {"questionType": "general", "strategy": "semantic_search", "count": 2,
             "ratedCount": 0, "avgConfidence": 0.6, "avgRating": None, "meanAbsDiff": None},
        ],
        "totalCount": 12, "totalRated": 3,
    },
    "tw/observability": {
        "generatedAt": "2026-09-15T00:00:00+00:00",
        "observatoryMetrics": {"aggregate": "by_operation", "groups": [],
                               "total_count": 4, "scanned_count": 9},
        "routingGraph": {"health": {"questionTypes": {"skill_depth": {"verdict": "converged"}}}},
        "routingDecisions": {"groups": [], "totalCount": 0, "totalRated": 0},
    },
    "tw/agent-metrics-agg": {"aggregate": "by_operation", "groups": [],
                             "total_count": 4, "scanned_count": 9},
    "tw/agent-metrics-list": {"items": [{"pk": "a", "sk": "b"}], "count": 1, "scanned_count": 1},
    "tw/improve-tasks": {"items": []},
    "aco/site-posts": {"items": [{"id": "abc", "title": "t", "status": "PUBLISHED"}],
                       "count": 1, "errors": 0,
                       "bucket": "selftest-articles", "prefix": "docs/articles"},
    "aco/site-post": {"id": "abc", "title": "t"},
    "aco/admin": {"ok": True},
    "dw/health": {"status": "healthy", "devices": 2, "registry_ok": True, "scenes": 1,
                  "learning_enabled": True, "graph_enabled": True},
    "dw/devices": {"devices": [{"id": "d1"}, {"id": "d2"}], "count": 2},
    "dw/presence": {"is_home": True, "updated_at": None},
    "dw/policies": {"policies": [], "count": 0},
}

STATUS = {"aco/admin-noauth": 403, "dw/devices-post": 405,
          "tw/run-unknown": 404, "aco/admin-bad-status": 400,
          "tw/agent-metrics-bad-op": 400}

state = {"bodies": copy.deepcopy(GOOD), "status": dict(STATUS)}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def _send(self, code, payload):
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        p, b, st = self.path, state["bodies"], state["status"]
        authed = "x-api-key" in {k.lower() for k in self.headers}
        if p.startswith("/cw/health"):
            return self._send(200, b["cw/health"])
        if p.startswith("/cw/routing-decisions"):
            return self._send(200, b["cw/routing-decisions-summary"] if "summary" in p
                              else {"items": [], "count": 0})
        if p.startswith("/tw/observability/agent-metrics"):
            if "operation=invoke_modelz" in p:
                return self._send(st["tw/agent-metrics-bad-op"], {"error": "operation must be one of [...]"})
            return self._send(200, b["tw/agent-metrics-agg"] if "aggregate=" in p
                              else b["tw/agent-metrics-list"])
        if p.startswith("/tw/observability"):
            return self._send(200, b["tw/observability"])
        if p.startswith("/tw/improve/tasks"):
            return self._send(200, b["tw/improve-tasks"])
        if p.startswith("/tw/team/task/"):
            return self._send(st["tw/run-unknown"], {"error": "run_id not found"})
        if p.startswith("/aco/site/posts/"):
            return self._send(200, b["aco/site-post"])
        if p.startswith("/aco/site/posts"):
            return self._send(200, b["aco/site-posts"])
        if p.startswith("/aco/admin/articles"):
            if not authed:
                return self._send(st["aco/admin-noauth"], {"error": "forbidden"})
            if "NOT_A_STATUS" in p:
                return self._send(st["aco/admin-bad-status"], {"error": "invalid status"})
            return self._send(200, {"items": []})
        if p.startswith("/aco/admin"):
            return self._send(200, b["aco/admin"])
        if p.startswith("/dw/health"):
            return self._send(200, b["dw/health"])
        if p.startswith("/dw/devices"):
            return self._send(200, b["dw/devices"])
        if p.startswith("/dw/presence"):
            return self._send(200, b["dw/presence"])
        if p.startswith("/dw/policies"):
            return self._send(200, b["dw/policies"])
        return self._send(404, {"error": "no route"})

    def do_POST(self):  # noqa: N802
        if self.path.startswith("/dw/devices"):
            return self._send(state["status"]["dw/devices-post"],
                              {"error": "Devices are managed via provider ingest."})
        return self._send(404, {"error": "no route"})


def serve() -> str:
    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{srv.server_port}"


def write_fake_env(base: str) -> Path:
    """Point the suite at the fake platform via the documented env-file seam."""
    path = HERE / "_selftest_env.json"
    path.write_text(json.dumps({"services": {
        "contextweave": {"api_base": f"{base}/cw"},
        "teamweave": {"api_base": f"{base}/tw",
                      "observatory_table": "selftest-spans",
                      "span_timeline_index": "SpanTimelineIndex",
                      "contextweave_url": f"{base}/cw"},
        "aco": {"api_base": f"{base}/aco", "articles_bucket": "selftest-articles",
                "articles_prefix": "docs/articles", "gemini_model": "gemini-3.8-flash"},
        "deviceweave": {"api_base": f"{base}/dw"},
    }}, indent=2), encoding="utf-8")
    return path


def run_suite(extra=()) -> tuple[int, str]:
    cmd = [sys.executable, "-m", "pytest", str(HERE),
           "-q", "--no-header", "-rf",
           # Only the one test that talks to real DynamoDB is deselected -- the
           # rest of test_04 is HTTP against /observability/agent-metrics and is
           # exercised here. Deselecting the whole file would have quietly made
           # two of the mutations below unfalsifiable.
           "--deselect",
           "e2e/test_04_shared_telemetry.py::test_live_spans_conform_to_the_shared_contract",
           *extra]
    # The fake server runs in THIS process, so mutating `state` changes what the
    # subprocess sees over the socket.
    import os
    child_env = dict(os.environ)
    child_env["WEAVE_E2E_ENV_FILE"] = str(HERE / "_selftest_env.json")
    child_env["WEAVE_E2E_ALLOW_WRITES"] = "0"
    # The admin tests skip without both credentials, which would have made the
    # "admin stops requiring credentials" mutation unfalsifiable. The fake
    # server only checks that the header is present.
    child_env["WEAVE_E2E_ACO_API_KEY"] = "selftest-key"
    child_env["WEAVE_E2E_ACO_JWT"] = "selftest-jwt"
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE.parent, env=child_env)
    return proc.returncode, proc.stdout + proc.stderr


def main() -> int:
    base = serve()
    plugin = write_fake_env(base)
    try:
        print("=== baseline: suite against a correct fake platform ===")
        code, out = run_suite()
        tail = [l for l in out.splitlines() if l.strip()][-1:]
        print("   ", *tail)
        if code != 0:
            print("\nBASELINE FAILED -- the suite rejects a correct platform:\n", out)
            return 1

        mutations = [
            ("/health loses routingGraph",
             lambda b: b["cw/health"].pop("routingGraph"),
             "test_health_reports_routing_graph_health"),
            ("an unrated group reports avgRating 0.0 instead of null",
             lambda b: b["cw/routing-decisions-summary"]["groups"][1].update({"avgRating": 0.0}),
             "test_routing_decisions_summary_is_readable_and_calibrated"),
            ("/observability drops a section",
             lambda b: b["tw/observability"].pop("routingDecisions"),
             "test_unified_view_returns_every_section"),
            ("observatoryMetrics aggregates more rows than it scanned",
             lambda b: b["tw/observability"]["observatoryMetrics"].update({"total_count": 99}),
             "test_observatory_metrics_section_is_data_not_an_error"),
            ("the unified graph disagrees with ContextWeave's own",
             lambda b: b["tw/observability"]["routingGraph"]["health"]["questionTypes"]
                        .update({"invented": {"verdict": "converged"}}),
             "test_the_joined_routing_graph_is_contextweaves_own"),
            ("agent-metrics count disagrees with the items returned",
             lambda b: b["tw/agent-metrics-list"].update({"count": 7}),
             "test_the_api_reads_the_same_spans_the_table_holds"),
            ("/site/posts reads a different bucket than the stack publishes",
             lambda b: b["aco/site-posts"].update({"bucket": "some-other-bucket"}),
             "test_published_articles_are_servable"),
            ("DeviceWeave health omits registry_ok",
             lambda b: b["dw/health"].pop("registry_ok"),
             "test_deviceweave_health_reports_subsystem_configuration"),
        ]
        status_mutations = [
            ("POST /devices starts creating devices",
             "dw/devices-post", 201, "test_creating_a_device_is_refused"),
            ("the admin API stops requiring credentials",
             "aco/admin-noauth", 200, "test_admin_requires_credentials"),
            ("an unknown status returns an empty list instead of 400",
             "aco/admin-bad-status", 200, "test_admin_rejects_an_unknown_article_status"),
            ("an unknown run_id returns 200",
             "tw/run-unknown", 200, "test_status_endpoint_rejects_an_unknown_run"),
            ("an unknown operation returns an empty list instead of 400",
             "tw/agent-metrics-bad-op", 200, "test_an_unknown_operation_is_rejected_not_silently_empty"),
        ]

        print(f"\n=== mutations: each must be caught by its named test ===")
        failures = 0
        for label, mutate, expected in mutations:
            state["bodies"] = copy.deepcopy(GOOD)
            mutate(state["bodies"])
            code, out = run_suite()
            caught = code != 0 and expected in out
            print(f"    {'CAUGHT ' if caught else 'MISSED '} {label}")
            if not caught:
                failures += 1
                print(f"             expected {expected} to fail; got rc={code}")
        state["bodies"] = copy.deepcopy(GOOD)

        for label, key, value, expected in status_mutations:
            state["status"] = dict(STATUS)
            state["status"][key] = value
            code, out = run_suite(extra=("-k", expected))
            caught = code != 0 and expected in out
            print(f"    {'CAUGHT ' if caught else 'MISSED '} {label}")
            if not caught:
                failures += 1
                print(f"             expected {expected} to fail; got rc={code}")
        state["status"] = dict(STATUS)

        total = len(mutations) + len(status_mutations)
        print(f"\n{total - failures}/{total} mutations caught")
        return 1 if failures else 0
    finally:
        plugin.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
