-- Two-phase proposal/commit schema for MCP Observatory demo.

CREATE TABLE IF NOT EXISTS tool_prompt_baselines (
    tool_name TEXT PRIMARY KEY,
    prompt_hash TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS proposals (
    proposal_id TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    args_json JSONB NOT NULL,
    prompt_hash TEXT NOT NULL,
    composite_score DOUBLE PRECISION NOT NULL,
    decision TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS commits (
    commit_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    token_id TEXT,
    decision TEXT NOT NULL,
    verification_reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS nonces (
    nonce TEXT PRIMARY KEY,
    token_id TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_proposals_tool_created_at ON proposals(tool_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_commits_proposal_created_at ON commits(proposal_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_nonces_expires_at ON nonces(expires_at);
