CREATE TABLE IF NOT EXISTS requirement_normalization_events (
    id BIGSERIAL PRIMARY KEY,
    workflow_run_id UUID REFERENCES workflow_runs(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_chunk_id UUID NOT NULL REFERENCES source_chunks(id)
        ON DELETE CASCADE,
    operation TEXT NOT NULL CHECK (
        operation IN ('unchanged', 'standardize', 'split', 'merge')
    ),
    input_text TEXT NOT NULL,
    output_texts JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_requirement_normalization_project
    ON requirement_normalization_events(project_id, created_at);

CREATE INDEX IF NOT EXISTS idx_requirement_normalization_workflow
    ON requirement_normalization_events(workflow_run_id);
