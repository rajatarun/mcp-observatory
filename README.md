# MCP Observatory

MCP Observatory now includes a **two-phase execution pattern** for high-risk MCP tool calls, with a generic proposer/verifier wrapper that can be reused by any tool:

1. **PROPOSE**: plan/simulate, evaluate uncertainty/integrity, no side effects.
2. **COMMIT**: execute side effects only when a signed commit token is valid.

## Two-Phase Sequence (Text Diagram)

```text
Client
  -> transfer_funds_propose(amount,to)
      -> scoring(output_instability, numeric_variance, prompt_drift)
      -> decision:
          - blocked: deterministic fallback (create_draft), no side effects
          - allowed: issue signed commit_token bound to tool args hash
  <- {proposal_id, commit_token?}

Client
  -> transfer_funds_commit(proposal_id, commit_token, amount, to)
      -> verify signature + expiry + proposal existence + args_hash binding + nonce replay
      -> if valid: perform side effect (funds transfer)
      -> else: block with explicit reason
  <- commit outcome
```

## New Modules

- `mcp_observatory/proposal_commit/hashing.py`
  - canonical JSON hashing for stable `tool_args_hash`
  - normalized `prompt_hash`
- `mcp_observatory/proposal_commit/scoring.py`
  - `output_instability = 1 - jaccard_similarity`
  - `numeric_variance` from extracted numbers
  - `prompt_drift` from prompt hash vs baseline
  - weighted renormalized `composite_score`
  - demo `model_generate(prompt, temperature)` stub
- `mcp_observatory/proposal_commit/token.py`
  - HMAC-SHA256 token issue/verify
  - payload fields: `token_id, proposal_id, tool_name, tool_args_hash, issued_at, expires_at, nonce, composite_score`
- `mcp_observatory/proposal_commit/proposer.py`
  - generic `ToolProposer.propose(...)` for any tool name/args
  - deterministic blocked fallback
- `mcp_observatory/proposal_commit/verifier.py`
  - commit verification and nonce replay protection
- `mcp_observatory/proposal_commit/storage.py`
  - in-memory storage fallback
  - optional Postgres storage via `asyncpg`
- `mcp_observatory/demo/server.py`
  - MCP-like tools:
    - `transfer_funds_propose`
    - `transfer_funds_commit`
- `mcp_observatory/demo/run_demo.py`
  - propose -> commit -> replay-attempt demo
- `sql/schema.sql`
  - Postgres tables: `proposals`, `commits`, `nonces`, `tool_prompt_baselines`

## Security / Verification Rules

Commit verifies all of the following:

- token signature is valid (`bad_signature` on failure)
- token not expired (`expired`)
- proposal exists and was allowed (`unknown_proposal`)
- commit args hash equals token payload args hash (`args_hash_mismatch`)
- nonce has not already been used (`nonce_replay`)

## Deterministic Fallback on Proposal Block

Blocked proposal response is deterministic and side-effect free:

```json
{
  "status": "blocked",
  "action": "create_draft",
  "reason": "low_integrity",
  "draft": {"tool": "transfer_funds", "amount": 100, "to": "acct_123"}
}
```

## Running the Demo

### Without Postgres (default)

No env vars needed; in-memory store is used.

```bash
python -m mcp_observatory.demo.run_demo
```

### With Postgres

1. Set DSN:

```bash
export MCP_OBSERVATORY_PG_DSN='postgresql://user:pass@localhost:5432/postgres'
```

2. Apply schema:

```bash
psql "$MCP_OBSERVATORY_PG_DSN" -f sql/schema.sql
```

3. Run demo:

```bash
python -m mcp_observatory.demo.run_demo
```

## Testing

```bash
PYTHONPATH=. pytest -q
```

The suite includes tests for token verification, hash stability, replay protection, and expired-token rejection.

## Real-World MCP Scenario Demo (10 End-to-End Flows)

A realistic MCP server example is available at:

- `mcp_observatory/demo/real_world_server.py`
- executable shim: `examples/real_world_mcp_server.py`
- executable client: `examples/real_world_mcp_client.py`
- prompt-to-invocation MVP: `examples/prompt_to_mcp_invocation_mvp.py`

It includes:

- 10 distinct prompts mapped to 10 different MCP tool handlers
- per-invocation annotations (e.g. `destructiveHint`, `idempotentHint`, `openWorldHint`)
- **proposal/commit** execution for HIGH-risk tools (no secondary-response gating)
- irreversible actions never pass a secondary LLM response
- simulated LLM responses and grounding summaries for standard-risk tools
- deterministic fallback routing for blocked/review-required scenarios

Run server demo:

```bash
python examples/real_world_mcp_server.py
```

Run client demo (client interacting with server):

```bash
python examples/real_world_mcp_client.py
```

Run prompt -> LLM planner -> server invocation MVP:

```bash
python examples/prompt_to_mcp_invocation_mvp.py
```
