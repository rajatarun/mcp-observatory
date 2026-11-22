# Live platform E2E suite

Tests the **seams** between the weave services against deployed stacks — the
claims in `ContextWeave/docs/weave-platform.md` §2 that no repository's own test
suite can check, because a seam has two sides and neither repo can import the
other.

Every coordinate is resolved from CloudFormation outputs. There is no URL, table
name or index name written down here; if a service does not publish something,
the suite says so and skips rather than guessing.

## Running

```bash
pip install -r e2e/requirements-e2e.txt

./e2e/run_e2e.sh --check     # what resolves, run nothing
./e2e/run_e2e.sh             # read-only (safe against production)
./e2e/run_e2e.sh --writes    # also the write tests
```

## What it covers

| File | The claim under test |
|---|---|
| `test_01_knowledge_loop.py` | ContextWeave answers, the answer carries a `queryId`, that id can be rated, and the rating reaches the decision log — the full learning loop |
| `test_02_orchestration.py` | TeamWeave accepts work **asynchronously** (202 + `run_id`) and runs reach a terminal state |
| `test_03_unified_observability.py` | `GET /observability` joins TeamWeave's spans with ContextWeave's router, degrades per-section, and forwards the *live* graph |
| `test_04_shared_telemetry.py` | Spans reach the shared table through `SpanTimelineIndex` and conform to the pinned contract |
| `test_05_content_pipeline.py` | ai-content-orchestrator serves published articles, and the bucket it reads is the one the stack publishes |
| `test_06_action_surfaces.py` | DeviceWeave is up and reports which subsystems are configured; the MCP stacks publish their coordinates |

## Three rules the suite enforces on itself

**Read-mostly.** Write tests carry `@pytest.mark.writes` and are deselected
unless `WEAVE_E2E_ALLOW_WRITES=1`. The writes are additive and small: one
question, one rating, optionally one pipeline run. **Nothing deletes.**

`POST /admin/newsletter/actions/send` has no test and never will — it mails the
live subscriber list through SES with no dry run. A suite aimed at production
must not be one `pytest` away from sending real email.

**Skip, never fail, on absence.** A stack that is not deployed, or an output a
service does not publish, produces a skip naming exactly what was missing. A
skipped integration test and a broken integration are different facts and must
never look alike in a report. Run with `-rs` (the runner does) to see every skip
reason.

**No secret is ever read.** Secret ARNs are resolved so a test can assert they
exist; their contents are not fetched, so no password reaches a shell
environment, a process list or a log. The two credentials the admin API needs
are supplied by the operator, never derived.

## `xfail` means the platform is degraded, not that the test is broken

Several checks `xfail` on a real live condition rather than failing: a starved
router, a FAILED pipeline run, an unreachable ContextWeave behind a configured
URL, unparseable article objects. In each case the *integration* held and the
*system* is in a state worth seeing. These are findings, not noise — read them.

## Proving the suite bites

An E2E suite nobody can run is a liability: it looks like coverage and asserts
nothing. `e2e/selftest.py` serves a fake platform that is correct by
construction, checks the suite passes against it, then breaks the fake one way
at a time and checks the suite catches each break — naming which test should
catch it.

```bash
python3 e2e/selftest.py
# 13/13 mutations caught
```

It needs no AWS and no network. Run it after changing any assertion here; two
of the mutations were unfalsifiable on the first attempt (the tests that should
have caught them were being skipped for missing credentials, and excluded along
with a file), which is exactly the failure this catches.

## Running against something CloudFormation cannot describe

`WEAVE_E2E_ENV_FILE=coords.json` skips AWS entirely and reads the coordinates
from a file — for a staging deployment behind different credentials, a local
stand-in, or the selftest above:

```json
{"services": {"contextweave": {"api_base": "https://localhost:8443"}}}
```

Keys are the friendly names in `platform_env.WANTED`, not Output names; an
unknown service name is rejected rather than silently ignored.

## Configuration

| Variable | Purpose |
|---|---|
| `AWS_REGION` | default `us-east-1` |
| `WEAVE_E2E_ENV_FILE` | read coordinates from JSON instead of CloudFormation |
| `WEAVE_STACK_*` | override a stack name (`_SHARED`, `_CONTEXTWEAVE`, `_TEAMWEAVE`, `_ACO`, `_DEVICEWEAVE`, `_TOOLWEAVE`, `_SCREENWEAVE`) |
| `WEAVE_E2E_ALLOW_WRITES` | `1` enables the write tests |
| `WEAVE_E2E_TEAM`, `WEAVE_E2E_TEAM_VERSION` | a team config that exists in the live bucket; without it the pipeline-run test skips rather than starting a run against a guessed name |
| `WEAVE_E2E_ACO_API_KEY`, `WEAVE_E2E_ACO_JWT` | both required for the admin-API tests |
| `WEAVE_E2E_TIMEOUT`, `WEAVE_E2E_RUN_TIMEOUT` | per-request (30s) and per-run (300s) budgets |

## Why it lives here

`mcp-observatory` is where the cross-repo artefacts already are: the shared-table
contract, `docs/integration-audit.md` and `docs/stack-outputs-audit.md`. Nothing
in `e2e/` ships in the package — setuptools picks up `mcp_observatory*` only.
