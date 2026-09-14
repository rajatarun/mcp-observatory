# Stack-outputs and API-description audit

**Date:** 2026-09-14 · **Scope:** every weave repository that deploys a
CloudFormation stack, except AuthChain (excluded by request).

The question: can an automation harness discover everything it needs to call
these APIs and inspect their data, from `describe-stacks` alone — no hardcoded
URLs, no table names copied out of a console, no bucket literals?

It could not. Base URLs were well covered; almost nothing else was. This audit
records what was missing, what changed, and what deliberately did not.

---

## The finding that repeats

**A table name is not enough to query a table.**

Six of the eight GSIs across the portfolio back the primary read path of their
service, and not one index name was published. That matters more than a missing
table name does, because of how DynamoDB fails:

| What is wrong | How it fails |
|---|---|
| Table name wrong | `ResourceNotFoundException` — loud, immediate |
| Table name right, index name unknown | A **scan**. Correct-looking results, wrong cost, and on an aggregate query a truncated answer that reads as data |

The second is the one that reaches production. A harness that scans
`ObservatoryMetricsTable` instead of querying `SpanTimelineIndex` returns rows,
so nothing looks broken; it just returns the wrong ones, capped by a scan limit,
and the dashboard built on it is quietly wrong.

Every index is now a stack output, and in each repository a test asserts that
the output names an index the template actually defines. An output pointing at a
nonexistent index is worse than no output: it fails at query time rather than at
deploy time.

---

## Per repository

### ContextWeave — `contextweave-rag-{env}`

| Gap | Resolution |
|---|---|
| No Postgres port, database name or instance identifier | `PostgresPort`, `PostgresDbName`, `PostgresInstanceIdentifier` |
| No API description | `openapi/contextweave.yaml` (4 paths) |

The instance identifier is the sharpest of these. The deploy workflow needed it
to start the stopped RDS instance before an update, and dug it out with
`describe-stack-resource --logical-resource-id PostgresRDS` — which only works
if you already know the logical id. It is an output now.

The spec is explicitly **not** the source of truth for response shapes:
`contracts/contextweave_http_api.json` is, because TeamWeave validates its
client against that same file. `tests/test_openapi_contract.py` drives its
assertions from the contract's own key lists rather than retyping them, and
checks both directions — the spec's `required:` arrays must equal the
contract's, and the contract's samples must validate against the spec's
schemas.

### TeamWeave — `teamweave`

| Gap | Resolution |
|---|---|
| Neither Observatory GSI name | `ObservatoryMetricsSpanTimelineIndex`, `ObservatoryMetricsAgentIdTimestampIndex` |
| No way to tell "ContextWeave unconfigured" from "unreachable" | `ContextWeaveUrl` (empty when unset) |
| No API description | `openapi/teamweave.yaml` (17 paths, 27 operations) |

`GET /observability` returns `null` for its `routingGraph` when ContextWeave is
not configured and an `{error: …}` object when it is configured but unreachable.
Both are 200s. Without the URL output a harness cannot distinguish "optional
dependency absent" from "dependency down", which are opposite conclusions.

Writing the spec surfaced a routing mismatch: the trigger handler's
`_is_agent_mgmt_route` accepts `DELETE` on every management path, but the
template routes `DELETE` only on `/agents` and `/teams/{team_name}`. A
documented `DELETE /roles/{role_id}` would have been a route no client could
reach. The test compares spec to template **method by method**, in both
directions, which is what catches this class.

It also pins two things the status code hides: the async routes must document
202 and not 200 (a 200 tells a harness the work finished when it has not
started), and the run-status 200 must admit `status: FAILED` (a harness checking
only the HTTP code scores every failed run as a pass).

**Also fixed here:** an order-dependent failure in
`tests/test_status_handler.py`. Its boto3 stub was installed only
`if "boto3" not in sys.modules`, so when another module got there first,
`status_handler` imported that stand-in and its module-level `sfn` came out as
`None`. The file passed alone and failed in the suite, with an error that reads
like a handler bug. That fix is what made it possible to run `pytest` in CI —
which the workflow had never done, despite `CLAUDE.md` saying "run pytest before
any PR" for as long as the suite has existed.

### ai-content-orchestrator — `tarun-admin-content`

| Gap | Resolution |
|---|---|
| Neither GSI name | `ContentTableStatusUpdatedIndex`, `ContentTableStatusPublishedIndex` |
| Articles bucket hardcoded in five places, account id baked in | `ArticlesBucket`/`ArticlesPrefix` parameters + outputs |
| Deployed Gemini model not observable | `GeminiModelId` |
| No API description | `openapi/content-orchestrator.yaml` (13 paths) |

`GeminiModelId` exists for a specific reason. `sam deploy` sends
`UsePreviousValue=true` for any parameter absent from `--parameter-overrides`,
so the deployed value can differ from the template default with nothing in the
repository showing it. That is exactly how the admin API came to serve a stale
model id. The output answers "what is actually running" without guessing.

The documented endpoint table in `CLAUDE.md` listed four routes and described
`/admin` as "List / create articles". It is a liveness probe; articles are under
`/admin/articles`; the handler serves thirteen paths. That table was wrong for
as long as it existed because nothing compared it to the code — which is what a
second hand-written description of an API invites. The spec is now checked
against the route literals in `src/*.py` in both directions.

### DeviceWeave — `deviceweave`

| Gap | Resolution |
|---|---|
| Neither GSI name | `DeviceRegistryProviderStatusIndex`, `PolicyTableDeviceTypeCreatedIndex` |
| Two of five tables unpublished | `SceneTableName`, `ConversationTableName` |
| No API description | `openapi/deviceweave.yaml` (14 paths, 20 operations) |

Both of this service's interesting access patterns run through an index rather
than the table key: the registry is keyed `(device_id, provider)` so "every
active device from this provider" needs `provider-status-index`, and the policy
table is keyed `(rule_id, version)` so `?device_type=` needs
`device-type-created-index`.

Three behaviours the status code hides, now pinned by tests:

- `POST /devices` is routed and **always** 405s. Devices come from ingestion.
- `POST /ingest` answers Ring's two-factor challenge with a **200**. A harness
  checking only for 2xx reads "we texted you a code" as a completed sync, then
  asserts against a registry nothing was written to.
- `503` on the learning, presence and policy routes means the table's
  environment variable is unset — **unconfigured, not down**. Retrying never
  succeeds.

### ToolWeave — MCP server

Two of three DynamoDB tables were unpublished (`ApiMetaTable`,
`ProposalsTable`). Deriving them from the `${AWS::StackName}-Suffix` convention
fails in the worst way available: reading a table that does not exist raises,
but reading the **wrong** table succeeds and returns nothing, which a test reads
as "the write did not happen". Both are outputs now, and a test asserts every
table and bucket in the template is named by some output.

**No OpenAPI spec, deliberately.** This is an MCP server behind
`ANY /{proxy+}`. MCP has its own protocol and its own discovery; a Swagger
document describing a single catch-all route would describe nothing.

### ScreenWeave — MCP server

The perceptual-hash cache table had no output, and it is the table that decides
whether a Bedrock vision call happens at all — a dHash hit serves a previous
interpretation for 72 hours. A harness that cannot name it cannot clear it
between runs, so a test can be asserting against a cached answer from an earlier
run and pass for the wrong reason, with nothing in the response saying so.

**No OpenAPI spec**, same reasoning as ToolWeave. `McpClientConfig` already
carries what a client needs to connect, and the one REST surface
(`VisualQAEndpoint`) is a single endpoint with its own output.

---

## The shape that was applied everywhere

Each repository with a spec now has the same three artefacts, because the spec
is only worth having if something stops it drifting:

1. **`openapi/<service>.yaml`** — `servers` templated on a stack output, never a
   hardcoded URL.
2. **`scripts/stack_env.py`** — maps outputs to environment variables in one
   place. `build_env()` is pure, so the naming contract is testable without an
   AWS account. **None of them resolve credentials**: they hand back a Secrets
   Manager ARN, so a password never lands in a shell environment, a process
   list, or a CI log.
3. **`tests/test_openapi_contract.py`** — checks the spec against things that
   cannot lie (the template's routes, the handlers' route literals and
   validation sets, the indexes the tables define), and asserts every output
   `stack_env.py` reads still exists.

Every one of these tests was mutation-verified: a deliberate break was
introduced for each assertion and the run was confirmed to fail in the expected
test. Three mutations across the session turned out to be **invalid** — the
replacement string never matched, so the test "passed" against unmodified code.
Each was redone and confirmed. A mutation that does not change the file proves
nothing, and it looks exactly like a passing test.

---

## What this does not cover

- **AuthChain** — excluded by request. Its stack publishes `ApiBaseUrl` and the
  nonce table but not `DATABASE_URL`, which is consumed by `src/index.mjs` and
  declared nowhere. That was already a known gap; it is unchanged.
- **Credential discovery.** Every `/admin` route on ai-content-orchestrator
  needs both an API key and a SIWE bearer token, and neither is a stack output.
  A harness still has to be handed them. That is the correct design.
- **Behavioural tests against a deployed stack.** Everything here runs offline.
  These artefacts make such a harness possible; none of them is one.
