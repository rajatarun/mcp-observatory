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
    fallback_reason TEXT,

    request_id TEXT,
    session_id TEXT,
    method TEXT,
    tool_args_hash TEXT,
    tool_criticality TEXT,
    policy_decision TEXT,
    policy_id TEXT,
    policy_version TEXT,

    grounding_risk FLOAT,
    self_consistency_risk FLOAT,
    numeric_instability_risk FLOAT,
    tool_mismatch_risk FLOAT,
    drift_risk FLOAT,
    composite_risk_score FLOAT,
    composite_risk_level TEXT,

    shadow_disagreement_score FLOAT,
    shadow_numeric_variance FLOAT,

    exec_token_id TEXT,
    exec_token_ttl_ms INT,
    exec_token_hash TEXT,
    exec_token_verified BOOLEAN
);

CREATE INDEX IF NOT EXISTS idx_mcp_traces_trace_id ON mcp_traces(trace_id);
CREATE INDEX IF NOT EXISTS idx_mcp_traces_service_start_time ON mcp_traces(service, start_time DESC);
CREATE INDEX IF NOT EXISTS idx_mcp_traces_model_start_time ON mcp_traces(model, start_time DESC);
CREATE INDEX IF NOT EXISTS idx_mcp_traces_prompt_hash ON mcp_traces(prompt_hash);
CREATE INDEX IF NOT EXISTS idx_mcp_traces_normalized_prompt_hash ON mcp_traces(normalized_prompt_hash);
CREATE INDEX IF NOT EXISTS idx_mcp_traces_service_tool_start_time ON mcp_traces(service, tool_name, start_time DESC);
CREATE INDEX IF NOT EXISTS idx_mcp_traces_policy_decision_start_time ON mcp_traces(policy_decision, start_time DESC);
CREATE INDEX IF NOT EXISTS idx_mcp_traces_composite_risk_level_start_time ON mcp_traces(composite_risk_level, start_time DESC);
CREATE INDEX IF NOT EXISTS idx_mcp_traces_prompt_template_start_time ON mcp_traces(prompt_template_id, start_time DESC);
