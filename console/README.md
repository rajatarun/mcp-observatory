# Weave Operations Console

A single-file admin portal organised by **the problem you need to solve**, not by
the service underneath. The services are an implementation detail and are named
only where knowing them changes what you do.

| # | Problem | What it abstracts |
|---|---|---|
| 01 | Ship this week's post | ai-content-orchestrator's article lifecycle + S3 publish |
| 02 | Ask what we know | ContextWeave `/query-expertise` and `/feedback` |
| 03 | Write a house rule | DeviceWeave `/policies/author` — LLM compiles, validator decides |
| 04 | See where spend goes | the shared span table, read through `SpanTimelineIndex` |
| 05 | Check it is learning | the router's verdicts and calibration |
| 06 | Find out what ran | TeamWeave runs, async by construction |

## The gate

Consequential actions are not executed on click. They are **proposed**, scored
against the real six-signal risk vector (`grounding`, `self_consistency`,
`numeric_instability`, `tool_mismatch`, `drift`, `verifier`), and **committed
separately** — the same propose/commit split mcp-observatory enforces on tool
calls.

The strip draws all six as threads, and the ones that were **not measured for
that action** as slack. That is deliberate: `signals_defined` matters as much as
the score, because a low composite from one signal is not the evidence a low
composite from six is. An action cleared on fewer than three signals is held for
review however low it scores.

## Two data modes, and the page always says which

- **`window.WEAVE_CONFIG` present** → live. Fetches the deployed APIs.
- **absent** → example data, labelled in the header, never passed off as yours.

Set the config from the resolver that already exists:

```bash
python e2e/platform_env.py --format json   # paste as window.WEAVE_CONFIG
```

### A published Artifact is always example mode

The claude.ai artifact CSP blocks every fetch to an outside host, so the page
**cannot** reach API Gateway from there — no capability grants arbitrary HTTP.
That is a property of where it is hosted, not a limitation of this file.

To run it live, serve it from an origin that can reach the APIs — the artifacts
S3 bucket behind CloudFront, or any static host — and inject the config:

```html
<script>window.WEAVE_CONFIG = { /* paste platform_env.py output */ };</script>
<script src="index.html-inline"></script>
```

The APIs also need CORS for the console's origin. ContextWeave already sets
`AllowOrigins: '*'`; the others do not, and tightening that `*` is worth doing at
the same time as opening the others.

## What Claude does here

Two jobs are genuinely generative and run through the `sample` capability when
the live service is unreachable:

- **Ask** — answers the question, clearly as Claude rather than as a live index.
- **Compile** — turns plain English into the policy DSL, then a deterministic
  check decides. Below the 0.50 confidence floor it is a 422: not retryable,
  because the rule is the problem, not the infrastructure.

Both are labelled. Neither is presented as your platform's own output.
