-- MCP Observatory Schema for PostgreSQL

-- Proposals table: stores proposal records with status and expiration
CREATE TABLE IF NOT EXISTS proposals (
  id UUID PRIMARY KEY,
  tool_name VARCHAR(255) NOT NULL,
  tool_args_hash VARCHAR(64) NOT NULL,
  status VARCHAR(20) NOT NULL CHECK (status IN ('allowed', 'blocked', 'review')),
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMP NOT NULL,
  INDEX idx_proposals_expires_at (expires_at)
);

-- Commits table: tracks execution of proposals
CREATE TABLE IF NOT EXISTS commits (
  id UUID PRIMARY KEY,
  proposal_id UUID NOT NULL REFERENCES proposals(id),
  executed BOOLEAN NOT NULL DEFAULT FALSE,
  executed_at TIMESTAMP,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  INDEX idx_commits_proposal_id (proposal_id),
  INDEX idx_commits_executed (executed)
);

-- Nonces table: tracks used nonces to prevent replay attacks
CREATE TABLE IF NOT EXISTS nonces (
  nonce VARCHAR(64) PRIMARY KEY,
  used_at TIMESTAMP NOT NULL DEFAULT NOW(),
  INDEX idx_nonces_used_at (used_at)
);

-- Tool prompt baselines table: stores baseline prompts for drift detection
CREATE TABLE IF NOT EXISTS tool_prompt_baselines (
  id UUID PRIMARY KEY,
  tool_name VARCHAR(255) NOT NULL UNIQUE,
  baseline_prompt_hash VARCHAR(64) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
  INDEX idx_baselines_tool_name (tool_name)
);

-- Traces table: stores execution traces for observability
CREATE TABLE IF NOT EXISTS traces (
  trace_id UUID PRIMARY KEY,
  span_id UUID NOT NULL,
  parent_span_id UUID,
  service VARCHAR(255) NOT NULL,
  model VARCHAR(255),
  tool_name VARCHAR(255),
  start_time TIMESTAMP NOT NULL,
  end_time TIMESTAMP,
  input_hash VARCHAR(64),
  output_hash VARCHAR(64),
  input_tokens INTEGER,
  output_tokens INTEGER,
  total_tokens INTEGER,
  cost_usd DECIMAL(10, 6),
  status_code INTEGER,
  tags JSONB,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  INDEX idx_traces_trace_id (trace_id),
  INDEX idx_traces_service (service),
  INDEX idx_traces_created_at (created_at)
);

-- Clean up expired proposals periodically
CREATE OR REPLACE FUNCTION cleanup_expired_proposals()
RETURNS void AS $$
BEGIN
  DELETE FROM proposals WHERE expires_at < NOW();
  DELETE FROM nonces WHERE used_at < NOW() - INTERVAL '1 hour';
END;
$$ LANGUAGE plpgsql;
