-- PostgreSQL schema for MCP Observatory.

CREATE TABLE IF NOT EXISTS mcp_traces (
    trace_id UUID,
    span_id UUID,
    parent_span_id UUID,
    service TEXT,
    model TEXT,
    tool_name TEXT,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    prompt_tokens INT,
    completion_tokens INT,
    cost_usd FLOAT,
    retries INT,
    fallback_used BOOLEAN,
    confidence FLOAT,
    risk_tier TEXT,
    prompt_template_id TEXT,
    prompt_hash TEXT,
    normalized_prompt_hash TEXT,
    answer_hash TEXT,
    grounding_score FLOAT,
    verifier_score FLOAT,
    self_consistency_score FLOAT,
    numeric_variance_score FLOAT,
    tool_claim_mismatch BOOLEAN,
    hallucination_risk_score FLOAT,
    hallucination_risk_level TEXT,
    prompt_size_chars INT,
    is_shadow BOOLEAN,
    shadow_parent_trace_id UUID,
    gate_blocked BOOLEAN,
    fallback_type TEXT,
    fallback_reason TEXT
);

CREATE INDEX IF NOT EXISTS idx_mcp_traces_trace_id ON mcp_traces(trace_id);
CREATE INDEX IF NOT EXISTS idx_mcp_traces_service_start_time ON mcp_traces(service, start_time DESC);
CREATE INDEX IF NOT EXISTS idx_mcp_traces_model_start_time ON mcp_traces(model, start_time DESC);
CREATE INDEX IF NOT EXISTS idx_mcp_traces_prompt_hash ON mcp_traces(prompt_hash);
CREATE INDEX IF NOT EXISTS idx_mcp_traces_normalized_prompt_hash ON mcp_traces(normalized_prompt_hash);
