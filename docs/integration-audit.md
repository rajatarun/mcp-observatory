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

**Corrected after the fix (this audit undercounted it).** There were *two*
writers with the identical bug, not one: `DynamoDBSpanExporter.export()`
(`WRAPPER#`) and `_write_invocation_metric()` (`INVOCATION#`), the latter
wrapping all four MCP tools. The items also violated two further invariants
the key rename alone did not resolve — `sk` was a bare timestamp rather than
`{iso8601}#{trace_id}` (I3), and there was no `ttl` (I4). The missing trace id
carried its own latent bug: two spans for the same method in the same
microsecond shared a pk+sk and silently overwrote each other. All of it is
fixed, with a warn-once logger so the next systemic write failure is visible.

**Status: fixed** (ToolWeave `b60d5ca`), with a regression test verified to
fail when the bug is reintroduced.

Two consequences of the fix worth stating plainly: ToolWeave now actually
writes, so it starts paying PutItem and storage costs it was never really
paying (bounded by a 90-day TTL); and because `WRAPPER#`/`INVOCATION#` still
have no reader, it now pays for durable telemetry nothing displays. That
second part is F2's decision, not a defect in the fix.

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
| RoutineWeave `src/storage/ObservatoryMetricsStore.ts` | `OBSERVATORY#invoke_model` | yes |

(DataDictionary appears in no row: it has no shared-table writer at all. Its
`put_item` calls target its own tables and its observatory module uses the
gate only. That was confirmed while adding its conformance test, which pins
the absence so that a future exporter has to target a read namespace.)

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

**This was a decision, not a bug, and the decision has been taken: the GSI.**

Three options were on the table — teach the readers the other namespaces, make
the library exporter adopt `OBSERVATORY#{operation}`, or stop reads depending
on the partition key at all. The first two leave the portfolio one careless
writer away from the same silence; only the third removes the class of defect.

**What was built.** `SpanTimelineIndex` on the shared table, keyed `span_date`
(a UTC `YYYY-MM-DD` bucket) + `timestamp` (ISO 8601 UTC), projection ALL. A
reader queries the days it wants and filters in memory; it never needs to know
what prefix a writer chose. The base-table `pk` becomes each writer's own
business.

**Why a date bucket rather than keying on `operation`.** Keying the index on
`operation` — the obvious candidate — would have traded a pk-prefix convention
for an operation-name convention: a reader wanting everything still has to
enumerate the values, and a writer inventing `invoke_tool` is invisible again.
A date bucket requires no shared vocabulary at all. It also matches what both
readers already do, which is query one partition over a time range and
aggregate in memory.

**The trap this does not remove, and how it is held closed.** A GSI indexes
only items carrying *both* key attributes, so a writer that omits `span_date`
or `timestamp` is exactly as invisible as it was before. That is why contract
v2.0.0 promotes `span_date`, `timestamp` and `operation` from recommended to
required (invariants I6–I8), and why every writer's repository has a
conformance test asserting them. The difference worth having is not that
invisibility became impossible — it is that it became a test failure instead of
a silence.

**Deployment order matters and no test can enforce it:**

1. Deploy the shared stack and wait for `SpanTimelineIndex` to reach `ACTIVE`.
   AWS creates at most one GSI per `UpdateTable`, so it must go out as its own
   change, and the backfill is not instant.
2. Deploy the writers, which must emit the three required attributes.
3. Switch the readers onto the index.

Readers were given a fallback to the legacy `pk` queries, triggered only by
index-absence, so step 3 is not order-sensitive in practice.

**Not retroactive.** Rows written before `span_date` existed carry no index key
and will never appear in `SpanTimelineIndex`. They remain reachable only by
their original `pk`, which is why `namespace_registry` and `readers_for()` are
kept — demoted to `legacy-informational`, answering a historical question.
Backfilling those rows is a separate migration and is not attempted here.

**Hot partition, stated honestly.** One index partition per day means the
current day takes every write. At this portfolio's volume that sits well inside
what on-demand adaptive capacity absorbs; if write rates grow, bucket by hour
rather than reintroducing a category-based partition key.

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

**Status: fixed** (ScreenWeave `c85825d`, repinned `^0.4.0`, lockfile resolves
`0.4.1`). The repin was verified safe before being made: ScreenWeave uses only
`InvocationWrapper` and never constructs a `TokenManager` or calls `propose()`,
so neither of 0.4.0's breaking changes (construction throws without a commit
secret; no-signal proposals now refuse) applies to it.

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

## F9 — DeployWeave's CI has never run its test files

**Severity: medium. Found while adding the tests; fixed.**

Two collection gaps that cancelled out badly. `unit_tests.py` does not match
pytest's default `python_files` glob, so a bare `pytest` collected 30 tests and
silently skipped its 85. Both CI workflows named that one file explicitly
(`pytest unit_tests.py -v`), so CI ran those 85 and silently skipped every
`test_*.py` file — including `test_observatory_metrics.py`, which had never run
in CI at all.

This matters more than an ordinary coverage gap because of what was being
added: a contract test exists to catch drift between repositories
automatically, and one that CI never runs catches drift only when somebody
remembers to look, which is the practice it was meant to replace.

**Status: fixed** (DeployWeave `9603c1d`). A `pytest.ini` names both patterns so
a bare `pytest` collects everything and the next test file added is picked up
without editing a workflow; both workflows now run plain `pytest -v`. All 115
tests pass together, so widening the run did not turn CI red.

---

## What the tests added alongside this audit do and do not cover

Added, across nine repositories: a vendored contract plus a conformance test in
each participating repository, so every writer checks its own emitted item and every reader checks
its own query against one shared definition
(`contracts/observatory_metrics_item.json`, canonical home: this repository);
and producer/consumer contract tests on both sides of the ContextWeave HTTP
seam driven from `contracts/contextweave_http_api.json`.

Each coupling was mutation-tested rather than assumed: renaming a field in a
contract, respelling a partition key, dropping an operation from a reader's
list, or marking an unread namespace read all make the relevant repository's
suite fail. One honest limit surfaced that way and is worth recording —
renaming `avgRating`/`meanAbsDiff` does *not* fail TeamWeave, because TeamWeave
passes the routing-decisions payload through verbatim and reads no key of it by
name. Those field names are pinned on ContextWeave's producer side instead;
asserting them on the consumer side would have been theatre.

These catch drift — a renamed field, a changed key spelling, a writer inventing
a namespace, a reader dropping an operation. They do not and cannot catch a
live integration failure: nothing here talks to real DynamoDB, real API
Gateway or real S3. An end-to-end test against deployed infrastructure remains
absent, and the contract tests are not a substitute for one.

Explicitly *not* fixed here, because each is a decision rather than a defect:
F2 (which key scheme wins), F4 (whether to wire E8 or drop it), F5 (whether the
gate should cover more surfaces).
