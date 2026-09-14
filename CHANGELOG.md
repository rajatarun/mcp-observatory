# Changelog

All notable changes to this package are documented in this file.

## [0.5.0] - 2026-09-14

Closes the gap between this package and the Python line. The JS package had
fallen behind on two things that mattered and one that was quietly causing
damage.

### Added

- **A DynamoDB span exporter (`DynamoDBSpanExporter`).** There was none, so
  every Node consumer hand-rolled its own writer for the shared
  OBSERVATORY_METRICS table — which is exactly how that table ended up with
  several mutually incompatible row shapes, one of them rejected outright by
  DynamoDB for the life of the integration while reporting success. The item
  shape is a cross-repository interface, now vendored here as
  `contracts/observatory_metrics_item.json` (v2.0.0) and shipped in the
  package, so consumers can delete their copies instead of re-deriving it.
  The exporter emits `span_date`/`timestamp`/`operation` (the SpanTimelineIndex
  keys, contract invariants I6-I8) from a single clock reading — two readings
  can straddle midnight and file a row under a day it did not happen on.
  `@aws-sdk/client-dynamodb` is an **optional** peer dependency, loaded lazily
  through a non-literal specifier, so consumers that never write to DynamoDB
  neither install it nor pay for it.

- **Channel binding (gate property P6).** The commit token can now carry the
  channel strength a call must run over, so an executor cannot quietly
  downgrade the transport for a call authorised on the assumption of a strong
  one. `ToolProposer` takes an optional `channelProfileProvider`; absent, no
  requirement is bound and nothing changes; present but throwing, the call is
  bound to `QUANTUM_SAFE`, because a policy service that could not be reached
  has not said "unconstrained". `CommitVerifier` enforces it **before** the
  nonce is inspected or burned, so a refusal over a weak channel stays
  retryable over a strong one rather than becoming a permanently dead
  authorisation. The profile is inside the signed payload, so it cannot be
  stripped or downgraded without invalidating the MAC, and it is omitted
  entirely — not set to null — when no policy ran, so existing deployments
  emit byte-identical tokens.

  Note a divergence from the Python line that had to be handled here: in this
  package a `review` verdict also returns a usable commit token, where in
  Python only `allow` mints one. Both mint sites bind the requirement. An
  unbound review token would be a way around P6, not a lesser form of it.

- **`operation` on the span** (`TraceContext`/`TraceSpan`). Every consumer had
  invented its own copy of this concept in its hand-rolled exporter, which is
  much of why the table fragmented. It belongs on the span.

### Notes

- Nothing here is a breaking change: the new constructor arguments are
  optional, the new payload field is omitted when unused, and the exporter is
  opt-in.

## [0.4.1] - 2026-09-13

Republished. `0.4.1` and `0.4.0` (below) carry identical code — verified
byte-for-byte identical `dist/` output between the two published tarballs.

**Publish history**, for anyone reconciling registry/repo state: the first
`npm publish` for this release failed partway through (the workflow's
`GITHUB_TOKEN` initially lacked `contents: write`, so the post-publish
release step failed after the npm upload had already staged `0.4.0`). That
looked like `0.4.0` was permanently stuck, so the version was bumped to
`0.4.1` as a workaround. In fact two separate workflow runs each completed
a real publish — one for the original `0.4.0`, one for `0.4.1` — so both
versions are genuinely live on the registry; `0.4.1` is `latest`. This
package's version is kept at `0.4.1` to match.

## [0.4.0] - 2026-09-13

Three hardening changes brought over from the Python package's 0.3.0. Two are
**breaking**: construction can now throw, and calls that were previously
allowed can now be refused.

### Security

- **`TokenManager` no longer invents a secret.** It previously fell back to
  `randomBytes(32)` when none was supplied, so every process signed with a
  different key: a restarted or scaled-out instance could not verify tokens it
  had issued moments earlier, and the failure surfaced as an ordinary
  verification failure with nothing pointing at configuration. The secret is
  now resolved explicitly from `MCP_OBSERVATORY_COMMIT_SECRET`, and
  construction throws when it is unset. Set `MCP_OBSERVATORY_ALLOW_DEV_SECRET=1`
  to sign with a fixed, public development secret instead — it warns loudly and
  must never be used outside a demo.

- **A token string now has exactly one accepted spelling.** The HMAC covers the
  payload's values, not the token string, and both encoding layers were
  lenient: Node's base64 decoder silently drops characters outside the
  alphabet, and the signature was recomputed from the re-serialised payload
  object rather than the received bytes. So `token + "!"`, `token + "=="`, a
  trailing newline, injected whitespace and any equivalent JSON spelling all
  verified. Replay was still caught — the nonce is inside the signed payload —
  but anything keyed on the token string was affected: `sha256(token)` on an
  audit row filed one authorisation under arbitrarily many hashes, and a nonce
  cache keyed on the string rather than `payload.nonce` would not have caught a
  replay at all. `verifyToken` now requires both round-trips and reports
  `non_canonical_token`.

- **A proposal with no signals is refused instead of allowed.** All three
  scoring signals are optional parameters, and each was read as `value || 0`
  and divided by a fixed denominator of 1.0 — so an absent signal contributed
  no risk at full weight, and a proposal carrying none at all scored 0 and was
  returned as `allowed` with a usable commit token. Missing evidence read as
  evidence of safety, which is exactly what the weighting was meant to prevent.
  The composite is now renormalised over the signals actually supplied and is
  `undefined` when there are none, which `propose()` refuses with reason
  `no_signals`. It refuses rather than returning `review`, because a `review`
  result still issues a commit token here and so is not a refusal. A genuine
  signal of `0` remains an observation and still scores — `|| 0` had conflated
  it with absence.

### Added

- **`MCP_OBSERVATORY_MAX_INPUT_BYTES`** (default `10240`). Every step of the
  gate is linear in input size, so the gate cannot bound its own latency;
  oversized argument mappings are now refused with reason `input_too_large`
  *before* hashing rather than after. An argument mapping that cannot be
  serialised at all (circular reference, `BigInt`) is treated as over the
  limit, since the gate cannot hash what it cannot serialise.

### Migration

- Set `MCP_OBSERVATORY_COMMIT_SECRET` in every environment, or construction
  throws. Use the same value across instances that must verify each other's
  tokens.
- Callers that relied on `propose()` succeeding without supplying any signal
  will now receive `blocked` / `no_signals`. Supply at least one signal, or
  treat the refusal as the fail-secure default it is.
- Deployments with payloads legitimately over 10 KB should set
  `MCP_OBSERVATORY_MAX_INPUT_BYTES` deliberately.

## [0.3.1] - 2026-09-13

### Fixed

- **`InvocationWrapper.invoke()` no longer swallows the real error from a
  failed wrapped call.** When `options.call()` rejected, the `finally` block
  unconditionally ran `hashText(JSON.stringify(output))` to record span
  telemetry — but `output` is never assigned on the failure path, and
  `JSON.stringify(undefined)` returns the *value* `undefined` rather than a
  string, so `hashText(undefined)` threw a `TypeError` (`The "data" argument
  must be of type string or an instance of Buffer...`). Because that throw
  happened inside a `finally`, it replaced the original error being
  propagated out of the `catch` block. Every caller that let a tool error
  bubble up through `invoke()` — including `RoutineWeave`'s
  `GeminiClient`/`NovaStructurer` integrations — saw an unrelated crypto
  `TypeError` instead of the actual failure reason, making failed tool calls
  impossible to diagnose from the caller's error message alone.

  The span is still finished and exported on the failure path (telemetry for
  failed calls is the point of the wrapper), now with `statusCode: 500`,
  `outputTokens: 0`, and no `outputHash`, instead of a thrown hash. Span
  finalisation is also now wrapped so that it can never throw — any
  unexpected error while computing output hash/tokens/cost (for example, a
  successful call whose output contains a `BigInt` or a circular reference,
  which also makes `JSON.stringify` throw) is logged and swallowed rather
  than replacing the call's real outcome.

  See `src/core/wrapper.ts` (`InvocationWrapper.invoke()`) and the new
  regression tests in `src/tests/wrapper.test.ts`.

## [0.3.0] - prior release

See git history for changes prior to the changelog being introduced.
