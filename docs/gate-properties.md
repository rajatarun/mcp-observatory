# Properties of the propose/commit gate

This document states what the gate guarantees, proves each statement from the
code as written, and records the two places where the implementation did not
satisfy the property it was described as having until the accompanying change.
Every numbered property has a test of the same number in
`tests/test_gate_properties.py`.

Notation. A candidate call is `(τ, a)`: tool name and argument mapping.
`H(a) = SHA-256(canonical_json(a))`. Signals `r_i ∈ [0,1]` with weights
`w_i > 0`; `D = {i : r_i is defined}`; `W_D = Σ_{i∈D} w_i`. The composite is

    s(r) = clamp₀¹( Σ_{i∈D} w_i · clamp₀¹(r_i) / W_D )         if D ≠ ∅
    s(r) = undefined                                           if D = ∅

---

## P1 — Monotonicity and bounded influence (fixed D)

**Proposition.** For a fixed defined set `D` and any `i ∈ D`, `s` is
non-decreasing in `r_i`, and for any change `δ` to `r_i`,
`|s(r') − s(r)| ≤ (w_i / W_D) · |δ|`.

*Proof.* Inside the clamp, `s` is an affine function of `clamp₀¹(r_i)` with
coefficient `w_i / W_D > 0`; `clamp₀¹` is non-decreasing and 1-Lipschitz; the
composition of non-decreasing functions is non-decreasing and Lipschitz
constants multiply. The outer clamp is also non-decreasing and 1-Lipschitz. ∎

**What P1 does not say.** It says nothing about two scores computed over
different `D`. Adding a signal can move `s` up or down (test
`test_p1_defined_set_change_is_not_comparable_and_count_is_exposed`), so a
score is only interpretable together with `|D|`. That is why `RiskVector`
now carries `signals_defined` and why the policy engine takes it.

---

## P2 — No allowance from no evidence

**Proposition.** No decision of ALLOW for a MEDIUM- or HIGH-criticality tool
is produced unless (a) a composite score exists and (b) at least
`min_signals_{medium,high}` signals informed it.

*Proof.* `composite_risk_score` returns `(None, "unknown")` when `W_D = 0`
(the loop accumulates weight only for non-`None` components, so `W_D = 0`
iff `D = ∅`). `PolicyEngine.evaluate` for HIGH and MEDIUM tests `s is None`
first and then `signals_defined < min_signals_*`, returning REVIEW in both
cases before any threshold comparison; only after both tests fall through
does a threshold produce ALLOW. LOW-criticality tools are allowed
unconditionally, as before; for them the control is blast radius, not the
score. ∎

### The defect this closes

The paper describing this system claims that renormalising by `W_D` rather
than by `Σ w_i` is the fail-safe: under a fixed denominator an undefined
signal contributes zero to the numerator and full weight to the denominator,
so *missing evidence looks like evidence of safety*. The claim is true of the
formula. It was false of the system, for two reasons.

1. **The empty case returned 0.0.** Both `composite_risk_score` and
   `composite_score` returned `0.0` when `D = ∅`. That is the fixed-denominator
   failure in its purest form: no signal at all was scored as the safest
   possible call. In the orchestrated paths `D` is never empty (the verifier
   signal and, in the proposer, output instability are always computed), so
   this was reachable only through direct use of the public function; it is
   fixed regardless.

2. **Two signals encoded "no input" as 0.0 risk.** `drift_risk` returned `0.0`
   when there was no previous prompt hash, and `tool_mismatch_risk` returned
   `0.0` when there was no tool result. Both belonged in `D` with value 0,
   which is exactly what renormalisation is supposed to prevent — the zeros
   were *inside* the numerator, not excluded from it. Concretely, for a call
   with no retrieval, no resample, no tool result and no prior prompt, the
   vector was `{verifier ≈ 0, tool_mismatch = 0, drift = 0}`, the composite
   was ≈ 0, the level was `low`, and a HIGH-criticality tool was **ALLOWED**.
   This path is reachable from the ordinary API and is the fail-open the
   paper says does not exist. Both signals now return `None` when their input
   is absent, leaving `D = {verifier}`, and P2(b) sends the call to review.

Test `test_p2_bare_confident_answer_no_longer_clears_a_high_criticality_tool`
fails against the previous code and passes now.

**Cost of the fix.** Calls that previously cleared HIGH tools on the verifier
signal alone now go to review. That is the intended behaviour: a lexical scan
for hedging words in the answer text is not evidence about the side effect.
Operators who disagree can set `PolicyConfig.min_signals_high = 1`; they
cannot set it to 0 and get ALLOW from `None`, because P2(a) is unconditional.

---

## P3 — Token integrity

**Proposition.** For a commit token `b64(P) . b64(HMAC_k(P))`, any change to
any field of `P` (including adding or removing a field), any change to the
signature, or verification under a different key is rejected with
`bad_signature`, assuming HMAC-SHA256 is a secure MAC.

*Proof.* The MAC is computed over the exact serialised payload bytes.
`verify` recomputes it over the received bytes and compares with
`hmac.compare_digest`. Any change to the payload bytes changes the MAC input,
so acceptance would be a MAC forgery; any change to the signature is rejected
by comparison; a different key produces a different MAC. Canonical
serialisation (`sort_keys`, compact separators) ensures the issuer and the
verifier agree on the bytes, so a legitimate token is not rejected for
formatting. ∎

The test enumerates every field of the payload by reading them from an
issued token, so a field added later is covered automatically.

### The defect the test found

P3 as first stated covered the payload *bytes* and the signature *bytes*. It
did not cover the token *string*, and the string was malleable: Python's
base64 decoder ignores characters after the padding, so `token + "x"`
decoded to identical bytes and verified. `test_p4_no_side_effect_without_a_passing_verification`
found this — the demo server **committed a transfer against a mangled
token**. The nonce still prevented replay, so no double execution was
possible, but a token had unboundedly many accepted spellings, and the v2
path records `sha256(token string)` on the span as the token hash: one
authorisation could appear under arbitrarily many hashes in the audit log.
Both verifiers now decode each segment and require that re-encoding
reproduces the input exactly, which makes the token string canonical.
P3 therefore holds for the string, not only for the bytes.

---

## P4 — Commit soundness

**Proposition.** If `verify_commit(proposal_id, token, τ', a')` returns `ok`,
then all of the following hold:

1. a proposal with id `proposal_id` exists and its recorded decision is `allow`;
2. `token` is authentic (P3) and unexpired;
3. `token.proposal_id = proposal_id`;
4. `token.tool_name = τ'`;
5. `token.tool_args_hash = H(a')`, i.e. the arguments presented at commit
   canonicalise to exactly the arguments scored at proposal;
6. `token.nonce` has not been accepted before within the token's validity.

Consequently the only call that can execute is the call that was scored and
allowed, and it can execute once.

*Proof.* `verify_commit` is a sequence of guards each of which returns a
non-`ok` result on failure; `ok` is returned only after every guard has
passed, and each guard is exactly one of (1)–(6). For (5), the hash is
recomputed from `a'` at commit time and compared to the value under the
signature, so any argument whose canonical form differs — value, type, added
key, removed key, at any nesting depth — produces a different digest; key
order is not part of the canonical form and is therefore accepted. For (6),
`nonce_seen` stores the nonce on first sight and reports it on any later
sight, so a second identical commit is refused. The demo server invokes the
side effect only in the branch where `verification.ok` is true. ∎

**Corollary (forgery does not help).** A token correctly signed by the
issuer's own key for a proposal whose recorded decision is `block` is
rejected by guard (1). The recorded decision, not the token, is authoritative.

### Replay window under clock skew

Property (6) holds only while a spent nonce is remembered for at least as
long as its token can verify. Token expiry is judged on the application clock
(`time()`); the Postgres backend garbage-collected with `NOW()`. If the
database clock ran ahead of the application clock by `δ`, a nonce could be
deleted while its token was still valid for `δ` seconds, and a replay in that
window would succeed. The in-memory backend uses one clock and has no such
window. The Postgres backend now retains nonces for `NONCE_GC_GRACE_SECONDS`
(300 s) past expiry, so (6) holds for any skew below the grace. This is a
bound, not an elimination: skew above 300 s reopens the window, and no
grace closes it if the application clock itself runs backwards.

---

## P6 — Channel binding

**Proposition.** If commit verification returns `ok` and the token carries a
`required_cipher_profile`, then the channel the executor presented is at least
as strong as that profile on the order
`CHEAP < BALANCED < HARDENED < QUANTUM_SAFE`. The requirement may be raised
between propose and commit but never lowered.

*Proof.* The field is inside the signed payload, so by P3 any edit — changing
the value or removing the field — is a MAC forgery and rejects with
`bad_signature`. The verifier's guard compares the presented channel against
the signed value and returns `channel_below_required_profile` unless the
channel places at least as high on the lattice; a channel it cannot place at
all satisfies nothing, and a requirement it cannot place is enforced at maximum.
The only other way the requirement can change is a verifier re-evaluating and
enforcing the join of the signed value with a fresh one, and a join over a
totally ordered lattice returns a least upper bound — something at least as
strong. ∎

**Placement.** The guard sits after the argument-hash check and *before*
`nonce_seen`. That call marks the nonce spent on first sight, so a guard after
it would burn the token on a rejection and make the correct retry impossible.
`test_a_refused_channel_does_not_burn_the_nonce` pins this.

**What P6 does not say.** It binds the executor's *claim* about its channel,
not the wire. Nothing in this library measures transport strength, so a lying
executor is outside the model in the same way key compromise is outside P3.
This is a real limitation, not a formality: the property is only as good as the
honesty of whatever calls `verify_commit`.

### Why the profile is injected, not imported

The profile is produced by a separate policy service — CipherWeave is the one
this was designed against. The proposer takes an optional async
`channel_profile_provider` rather than importing that service, because this
library is a dependency of several unrelated products and most of them run no
channel policy. Importing the producer would make every consumer depend on it,
and an `ImportError` inside the gate would fail *closed* for a deployment that
never asked for the feature. The four profile names and their order are
therefore a contract between the two systems, duplicated deliberately in
`proposal_commit/channel.py`; changing it needs a version field in the token,
not a shared import.

A deployment with no provider binds no requirement and behaves exactly as
before — and cannot be forged into that state, since removing the field breaks
the signature. `CommitVerifier(require_channel_binding=True)` refuses tokens
that carry no requirement, for deployments where every token should have one.

---

## P5 — Cost

Let `|a|` be the serialised argument size and `|t|` the length of a text
input (answer, resample, context).

| Step | Cost | Note |
|---|---|---|
| `canonical_json(a)` | `O(|a| log k)` | `k` = keys per object, from `sort_keys` |
| `H(a)` | `O(|a|)` | SHA-256 is linear |
| token issue / verify | `O(|P|)` | payload is a fixed set of short fields plus `τ`; effectively constant |
| nonce check | `O(1)` in memory; one indexed lookup + insert in Postgres | |
| Jaccard signals | `O(|t₁| + |t₂|)` | regex tokenisation, set ops |
| numeric instability | `O(|t|)` | |
| tool mismatch / verifier | `O(|t|)` | substring scans |
| composite | `O(6)` | |

The full path is linear in the total size of its text inputs and arguments,
with no step super-linear beyond key sorting. Measured with
`scripts/bench_gate.py` (100 iterations per point, one core, Python 3.11;
median ms; the last column is the least-squares exponent of cost against
input size, where 1.0 is linear):

| Step | 100 B | 1 KB | 10 KB | 100 KB | 1 MB | exponent |
|---|---:|---:|---:|---:|---:|---:|
| args hash (canonical JSON + SHA-256) | 0.003 | 0.010 | 0.075 | 0.83 | 11.2 | 0.90 |
| token issue + verify (`tool_name` = N) | 0.028 | 0.045 | 0.19 | 1.60 | 18.7 | 0.72 |
| output instability (Jaccard) | 0.007 | 0.059 | 0.85 | 9.3 | 111 | 1.06 |
| numeric variance | 0.024 | 0.16 | 1.31 | 12.6 | 128 | 0.93 |
| grounding risk (Jaccard) | 0.014 | 0.12 | 1.43 | 14.0 | 174 | 1.03 |
| **full propose/commit path** | **0.076** | 0.30 | 2.3 | 22 | 261 | 0.89 |
| **full six-signal risk vector** | **0.077** | 0.52 | 4.9 | 48 | 551 | 0.97 |

Two readings. First, the 100-byte column reproduces the paper's 0.0996 ms
figure for the typical case. Second, the gate cannot bound its own latency:
at 1 MB of text the six-signal vector costs half a second, and every step
scales as the table says it should. The operational guard is therefore an
input-size limit *upstream* of the gate. 10 KB (≈2–5 ms) is a defensible
default for argument mappings and answers alike; anything larger should be
refused or summarised before scoring, since there is nothing the gate can do
about a 1 MB argument except hash it.

That limit is implemented, not just recommended: `MCP_OBSERVATORY_MAX_INPUT_BYTES`
(default 10240) is checked in `core/interceptor.py`'s v2 path before
`compute_risk_vector` runs, and in `proposal_commit/proposer.py` before
hashing or scoring, against the canonical JSON of `tool_args` and every text
input (answer, secondary answer, retrieved context, tool result summary,
prompt, candidate outputs). Over the limit, the call is refused with reason
`input_too_large` — routed to the fallback in the v2 path, returned as a
blocked proposal in the propose path — without ever reaching a scorer.

### Semantics of `s`

`s` is a weighted mean of lexical risk indicators. It is not a probability
of harm, its thresholds have never been fit to outcomes, and it is comparable
across calls only at equal `|D|`. What that means for anyone who wants to
combine `s` with a confidence from another system is set out in
`ContextWeave/docs/confidence-semantics.md`, which inventories the scores of
all three weave systems and states the rules under which they may be
combined (in short: only after calibration against an outcome, which for
`s` requires recording what happened after each REVIEW and ALLOW).

---

## What is *not* claimed

- Nothing here says the composite score separates unsafe calls from safe
  ones. P1 says the score moves in the right direction with each signal; it
  does not say the signals measure safety. That requires a labelled corpus
  the project does not have.
- P3/P4 assume the commit secret is uncompromised and the proposal store is
  not writable by the caller. A caller who can write `decision = allow` into
  the store, or who holds the key, is outside the model.
- P2 makes "insufficient evidence" a review, not a block. A deployment with
  no human in the loop will see those calls fail closed via the fallback
  router, which is the correct degradation.
