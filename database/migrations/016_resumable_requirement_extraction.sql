ALTER TABLE workflow_runs
    ADD COLUMN IF NOT EXISTS model_call_limit INTEGER
        CHECK (model_call_limit IS NULL OR model_call_limit > 0),
    ADD COLUMN IF NOT EXISTS model_token_limit INTEGER
        CHECK (model_token_limit IS NULL OR model_token_limit >= 1000);

CREATE TABLE IF NOT EXISTS requirement_extraction_batches (
    id BIGSERIAL PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    batch_fingerprint TEXT NOT NULL,
    rule_checksum TEXT NOT NULL,
    result JSONB NOT NULL,
    item_count INTEGER NOT NULL CHECK (item_count >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (project_id, batch_fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_requirement_extraction_batches_project
    ON requirement_extraction_batches(project_id, created_at);
