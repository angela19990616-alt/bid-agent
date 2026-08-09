CREATE TABLE IF NOT EXISTS model_usage_events (
    id BIGSERIAL PRIMARY KEY,
    workflow_run_id UUID NOT NULL REFERENCES workflow_runs(id)
        ON DELETE CASCADE,
    task TEXT NOT NULL,
    model TEXT NOT NULL,
    reserved_tokens INTEGER NOT NULL CHECK (reserved_tokens > 0),
    actual_tokens INTEGER CHECK (
        actual_tokens IS NULL OR actual_tokens >= 0
    ),
    status TEXT NOT NULL DEFAULT 'reserved' CHECK (
        status IN ('reserved', 'succeeded', 'failed')
    ),
    error_type TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_model_usage_events_workflow
    ON model_usage_events(workflow_run_id, created_at);
