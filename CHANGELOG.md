# Changelog

All notable changes to this package are documented in this file.

## [0.4.1] - 2026-09-13

Republished as 0.4.1. `0.4.0` was never published: an earlier `npm publish`
attempt failed on the registry's authentication check partway through the
upload, leaving an orphaned staged version behind. npm has no self-service
way to clear a stuck stage, so `0.4.0` cannot be used for any release of
this package; `0.4.1` carries the identical changes described below. No
code differs between what was intended as 0.4.0 and this release.

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
