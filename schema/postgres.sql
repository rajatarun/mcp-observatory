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
    confidence FLOAT
);

CREATE INDEX IF NOT EXISTS idx_mcp_traces_trace_id ON mcp_traces(trace_id);
CREATE INDEX IF NOT EXISTS idx_mcp_traces_service_start_time ON mcp_traces(service, start_time DESC);
CREATE INDEX IF NOT EXISTS idx_mcp_traces_model_start_time ON mcp_traces(model, start_time DESC);
