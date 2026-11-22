# Vendored contracts

Copies, not sources. Each file's canonical home is named in its own
`canonical_home` field; this directory exists so the E2E suite asserts against
the same published shape its owning repository does, instead of a key list
retyped into a test.

| File | Canonical home |
|---|---|
| `contextweave_http_api.json` | `rajatarun/ContextWeave` → `contracts/contextweave_http_api.json` |
| `../../contracts/observatory_metrics_item.json` | this repository (not vendored — it is the source) |

Re-vendor by copying unmodified. If a copy drifts from its source, the E2E
suite is checking the live platform against a shape nobody publishes.
