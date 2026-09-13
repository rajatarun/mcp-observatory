# Cross-repository integration audit

**Date:** 2026-09-13 · **Scope:** every weave repository except AuthChain (excluded by request).

The portfolio is thirteen repositories that depend on each other through four
kinds of seam: a shared DynamoDB table, an HTTP API, an S3 prefix handoff, and
a published library (PyPI and npm). Every repository has its own test suite and
all of them pass. None of those suites tests a seam, because a seam by
definition has two sides and no repository can import the other one's code.

This audit looked at the seams. What follows is what it found, with the
evidence, ordered by how badly the thing is broken rather than by how
interesting it is.

---

## F1 — ToolWeave's telemetry has never been written. Not once.

**Severity: high. Silent total data loss.**

`ToolWeave/src/toolweave/observatory.py` writes span rows like this:

```python
_metrics_table.put_item(Item={"PK": f"WRAPPER#{...}", "SK": ts, ...})
except Exception:
    pass  # never let metrics writes crash the main flow
```

The shared table declares its key schema in `TeamWeave/infra/shared.yaml` as
`AttributeName: pk` (HASH) and `AttributeName: sk` (RANGE) — lower case.
DynamoDB attribute names are case sensitive. An item carrying `PK`/`SK` and no
`pk`/`sk` is rejected by `PutItem` with `ValidationException: Missing the key
pk in the item`.

That exception lands in the bare `except: pass` directly beneath it. So every
ToolWeave telemetry write has been rejected by DynamoDB and reported to
ToolWeave as success, for the entire life of the integration. There is no
alarm, no log line, and no row.

The bare except is not itself wrong — telemetry genuinely should not crash the
call it observes — but combined with a key-spelling bug it converts a hard,
immediate, obvious failure into permanent silence.

---

## F2 — Four incompatible partition-key schemes in one "unified" table

**Severity: high. Design-level; needs a decision, not a patch.**

`docs/weave-platform.md` states that "the data plane is already unified (one
metrics table, five writers) even though the reading of it is not". The first
half is not true. The writers agree on the table and on nothing else:

| Component | `pk` written | Reachable by a dashboard? |
|---|---|---|
| `mcp_observatory.aws.DynamoDBSpanExporter` (the shared library) | `SPAN#{tool_name or model}` | **no** |
| TeamWeave `src/orchestrator/mcp_observatory.py` | `OBSERVATORY#{operation}` | yes |
| DeviceWeave `src/observatory_wrapper.py` | `OBSERVATORY#{operation}` | yes |
| ContextWeave `src/shared/mcp_observatory.py` | `OBSERVATORY#{operation}` | yes |
| ScreenWeave `src/lambda/mcpServer/observatory.mjs` | `OBSERVATORY#{toolName}` | **no** (see below) |
| ToolWeave `src/toolweave/observatory.py` | `WRAPPER#{method}` / `INVOCATION#` | **no** (and see F1) |

The readers are `TeamWeave/src/orchestrator/agent_metrics_handler.py` and the
unified `/observability` handler that reuses its query logic, plus
`DeployWeave/observatory_metrics.py`. All of them query whole partitions by
exact `pk`, over a fixed list of operation names:
`invoke_agent`, `invoke_model`, `classify_question`, `synthesize_answer`.

Three consequences, in increasing order of awkwardness:

1. **ScreenWeave's rows are unreachable.** It uses the right namespace but puts
   a *tool* name where readers enumerate *operation* names, so its spans land
   in partitions like `OBSERVATORY#screenshot` that nothing ever queries.

2. **The library exporter's rows are unreachable.** It writes `SPAN#…`, which no
   reader queries at all.

3. **Therefore platform edge E2 — "one `observatory_wrapper` module inside
   mcp-observatory replacing the four vendored copies" — currently makes things
   worse, not better.** Migrating a service off its vendored copy onto the
   shared exporter is precisely the action that removes it from every
   dashboard, silently. The four vendored copies E2 wants to delete are, right
   now, the only reason any telemetry is visible.

**This is a decision, not a bug.** Either the readers learn to query `SPAN#`
and the tool-name partitions, or the library exporter adopts
`OBSERVATORY#{operation}`, or the table gains a GSI on `service`/`operation` so
reads stop depending on partition-key prefix conventions at all. Each has a
different migration cost for rows already written. It is recorded in
`contracts/observatory_metrics_item.json` under `namespace_registry`, where
unread namespaces are marked `status: unread` so the gap is machine-readable
rather than folklore.

---

## F3 — ScreenWeave is pinned to the pre-hardening gate

**Severity: high.**

`ScreenWeave/src/lambda/mcpServer/package.json` pins
`"@weaveaijs/mcp-observatory": "^0.3.0"`, and its lockfile resolves `0.3.0`.
A caret range on a `0.x` version admits only patch bumps — `^0.3.0` means
`>=0.3.0 <0.4.0` — so it can never reach the current `0.4.1`.

ScreenWeave is therefore still running the build with all four defects that
0.3.1/0.4.0 fixed: the `finally`-block bug that replaces a wrapped call's real
error with a crypto `TypeError`, no canonical-token check, fail-open scoring
(a proposal with no signals scored 0 and came back `allowed` with a usable
commit token), and no input-size ceiling before hashing.

This is the same defect class already found and fixed in RoutineWeave. The
caret-on-`0.x` trap is worth stating plainly because it silently defeats the
intent of "we pinned everyone to the hardened release".

---

## F4 — E8's channel binding has no caller

**Severity: medium.**

`mcp_observatory/proposal_commit/channel.py` and the
`channel_profile_provider` parameter on `ToolProposer` exist, are documented in
`docs/gate-properties.md` as property P6, and are covered by fourteen tests.
Nothing uses them: `channel_profile_provider` and `required_cipher_profile`
appear nowhere in CipherWeave or ToolWeave.

Edge E8's stated purpose was to give CipherWeave its first caller and the gate
a second dimension. The library half shipped; the integration did not. The gate
can bind a required channel profile into a commit token, but no deployment
supplies one and no executor enforces one.

---

## F5 — The gate is used by two of six services

**Severity: medium (scope observation).**

Only `ToolWeave/src/toolweave/observatory.py` and
`DataDictionary/src/data_dictionary/observatory.py` import `proposal_commit` at
all. DeviceWeave, ContextWeave, TeamWeave and ScreenWeave use only the
telemetry wrapper. The portfolio's headline claim — that every side effect
passes through one gate — describes two of its action surfaces.

---

## F6 — Both sides of the ContextWeave HTTP seam tested against their own fiction

**Severity: medium. Fixed by this work.**

`TeamWeave/tests/test_unified_observability_handler.py` hard-coded literal
dicts of what TeamWeave believed ContextWeave returns.
`ContextWeave/tests/test_routing_decisions_api.py` asserted its handlers
against an sqlite-backed fake. Both suites were green. Nothing compared them,
so any field rename on either side would keep both green and break production
— which is exactly the failure mode the E10 work was one field-rename away
from, since the two halves were built in parallel from a contract that lived
only in a prompt.

`ContextWeave/contracts/contextweave_http_api.json` now pins the samples and
both repositories validate against that one file.

---

## F7 — A stale duplicate clone

**Severity: low (hygiene), but it distorts audits.**

`/home/user/contextweave` (lower case) is a second working copy of
`github.com/rajatarun/ContextWeave.git`, on the same branch name, HEAD parked
on an old commit, with stale `mcp-observatory>=0.1.0` pins. It is not a
separate project. It shows up in portfolio-wide greps and reports version pins
that no deployed thing uses. Nothing here deleted it — it is the user's
workspace — but work done in it would never reach the real branch.

---

## F8 — The flywheel's S3 seam is convention, not contract

**Severity: low.**

`TeamWeave/src/orchestrator/dpo_collector.py` writes DPO records at
`{project}/{team}/{step_id}/{run_id}/dpo_{ts}.json`.
`TrainWeave/src/orchestrator/app.py` takes `bucket` and `prefix` as
caller-supplied input and lists whatever is under them. There is no hard-coded
mismatch, so nothing is broken — but nothing pins the layout either. If
TeamWeave reorganises its key structure, TrainWeave's callers silently start
listing zero records and the failure surfaces as "no DPO records found".

---

## What the tests added alongside this audit do and do not cover

Added: a vendored contract plus a conformance test in each participating
repository, so every writer checks its own emitted item and every reader checks
its own query against one shared definition
(`contracts/observatory_metrics_item.json`, canonical home: this repository);
and producer/consumer contract tests on both sides of the ContextWeave HTTP
seam driven from `contracts/contextweave_http_api.json`.

These catch drift — a renamed field, a changed key spelling, a writer inventing
a namespace, a reader dropping an operation. They do not and cannot catch a
live integration failure: nothing here talks to real DynamoDB, real API
Gateway or real S3. An end-to-end test against deployed infrastructure remains
absent, and the contract tests are not a substitute for one.

Explicitly *not* fixed here, because each is a decision rather than a defect:
F2 (which key scheme wins), F4 (whether to wire E8 or drop it), F5 (whether the
gate should cover more surfaces).
