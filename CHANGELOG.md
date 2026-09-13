# Changelog

All notable changes to `mcp-observatory` are documented here. This file
starts at 0.3.0; earlier history is in `git log`.

## 0.3.0

**This is the first release where the propose/commit gate's documented
properties (`docs/gate-properties.md`) hold as written.** Two defects fixed
on this branch were shipped in 0.2.1 and earlier; this release is the
version bump that reflects them, plus two new fail-closed defaults.

### Fixed (carried up from unreleased commits on this branch)

- **P2 — no allowance from no evidence.** `composite_risk_score` and
  `composite_score` returned `0.0` (not `None`/`"unknown"`) when no signal
  was defined, and `drift_risk`/`tool_mismatch_risk` returned `0.0` — not
  `None` — when their input (a previous prompt hash, a tool result) was
  simply absent. Both zeros sat inside the renormalised composite as if
  they were evidence, which is exactly what renormalising over the defined
  set is supposed to prevent. Concretely: a call with no retrieval, no
  resample, no tool result and no prior prompt scored a composite of ~0,
  was rated `"low"`, and a HIGH-criticality tool was **ALLOWED** on the
  verifier's lexical scan of the answer text alone. `drift_risk` and
  `tool_mismatch_risk` now return `None` when their input is absent;
  `composite_risk_score`/`composite_score` return `None`/`"unknown"` for an
  empty defined-signal set; `RiskVector` carries `signals_defined`; and
  `PolicyEngine` (`min_signals_high=2`, `min_signals_medium=1`) sends a
  HIGH or MEDIUM tool to **REVIEW**, not ALLOW, whenever the score is
  `None` or built on fewer signals than the minimum. The proposer blocks a
  `None` composite score with reason `no_signals` instead of treating it as
  zero risk.

  **Behaviour change:** a HIGH-criticality call that previously cleared on
  the verifier signal alone (the only signal defined when there is no
  retrieval, resample, or tool result) now goes to **REVIEW** instead of
  ALLOW. This is the fix, not a regression — see `docs/gate-properties.md`
  P2 for the proof and the reachability argument.

- **P3 — canonical token strings.** Python's base64 decoder ignores bytes
  after padding, so `commit_token + "x"` decoded to the same bytes and
  verified. Replay was still caught (the nonce lives in the signed
  payload), but the token string had unboundedly many accepted spellings,
  and the v2 control plane records `sha256(token string)` as the audit
  hash — so one authorisation could appear under arbitrarily many hashes.
  `token/verifier.py` and `proposal_commit/token.py` now decode each
  base64url segment and require that re-encoding reproduces the input
  exactly.

- Postgres nonce garbage collection now retains a spent nonce for
  `NONCE_GC_GRACE_SECONDS` (300s) past its token's expiry, closing the
  replay window opened by database/application clock skew up to that
  grace period.

- `PolicyResult.policy_version` is now `2.1.0`, reflecting the P2 policy
  change above.

### Added

- **Fail closed on default secrets.** `token/issuer.py`, `token/verifier.py`
  and `proposal_commit/token.py` previously fell back to hardcoded
  development secrets (`dev-secret`, `dev-commit-secret`) whenever
  `MCP_OBSERVATORY_TOKEN_SECRET` / `MCP_OBSERVATORY_COMMIT_SECRET` were
  unset. An unset or known-default secret now raises
  `InsecureDefaultSecretError` at construction time. Set
  `MCP_OBSERVATORY_ALLOW_DEV_SECRET=1` to opt back into the development
  secret for local runs, demos, and tests — the bundled demo
  (`mcp_observatory.demo.server`, `mcp_observatory.demo.real_world_server`)
  sets it automatically with a loud warning so `python -m
  mcp_observatory.demo.run_demo` still runs with no configuration.

- **Input-size limit ahead of scoring**
  (`MCP_OBSERVATORY_MAX_INPUT_BYTES`, default 10240). Per
  `docs/gate-properties.md` P5, every scoring step is linear in input size
  and the gate has no latency bound of its own without an upstream limit.
  `core/interceptor.py`'s v2 path now checks the canonical JSON of
  `tool_args` and every text input (`model_answer`, `secondary_answer`,
  `retrieved_context`, `tool_result_summary`, `prompt`) *before* calling
  `compute_risk_vector`; over the limit, the call is routed to the
  fallback with reason `input_too_large` instead of being scored.
  `proposal_commit/proposer.py` performs the same check (over `tool_args`,
  `prompt`, and both candidate outputs) before hashing or scoring, and
  returns a blocked response with reason `input_too_large`.

- **Shared AWS wrapper module (`mcp_observatory/aws/`).** Four sibling
  repos (ToolWeave, DataDictionary, TeamWeave, DeviceWeave) had
  independently vendored near-identical Bedrock/DynamoDB wiring around
  this library. The common parts are now in the library itself, behind the
  optional `aws` extra (`pip install mcp-observatory[aws]`; boto3 is
  imported lazily and is not a hard dependency):
  - `DynamoDBSpanExporter` — writes `TraceContext` span/decision fields to
    a DynamoDB table (name from `OBSERVATORY_METRICS_TABLE`) with a
    configurable TTL.
  - `build_gate(secret_env=..., block_threshold_env=...)` — a factory
    returning a wired `(proposer, verifier, token_manager)` triple, using
    `InMemoryStorage` by default and Postgres storage when
    `MCP_OBSERVATORY_PG_DSN` is set.

  An `observe_model_request`-style convenience helper was considered but
  left out: the four vendored copies do not agree on its shape (two wrap
  `ToolProposer`/`CommitVerifier` directly with no such helper at all; one
  is bound tightly to Bedrock agent/model invocation with dual-invoke
  shadow lanes and Prometheus export; one is a Bedrock-Converse decorator
  that does not call `InvocationWrapperAPI.invoke` at all). Standardising
  that shape is future work, not a mechanical extraction.

### Migration

Consumers pinned to `mcp-observatory==0.2.0` or `mcp-observatory>=0.1.0`
should move to `mcp-observatory>=0.3.0`. Before upgrading:

1. Set `MCP_OBSERVATORY_TOKEN_SECRET` and `MCP_OBSERVATORY_COMMIT_SECRET`
   in every environment that issues or verifies tokens (construction now
   raises without them, unless `MCP_OBSERVATORY_ALLOW_DEV_SECRET=1` is set
   for local development or tests).
2. Expect HIGH-criticality tool calls backed only by the verifier signal
   (no retrieval, no resample, no tool result, no prior prompt) to move
   from ALLOW to REVIEW. If your deployment has no human in the loop for
   REVIEW, those calls now fail closed via the fallback router.
3. If any tool call's arguments or text inputs can exceed 10 KB, set
   `MCP_OBSERVATORY_MAX_INPUT_BYTES` deliberately rather than discovering
   the default via an unexpected `input_too_large` fallback.
