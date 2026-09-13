# Changelog

All notable changes to this package are documented in this file.

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
