CREATE TABLE IF NOT EXISTS export_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    section_id UUID NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
    section_version_id UUID NOT NULL REFERENCES section_versions(id)
        ON DELETE CASCADE,
    format TEXT NOT NULL CHECK (format = 'docx'),
    status TEXT NOT NULL CHECK (
        status IN ('running', 'succeeded', 'failed')
    ),
    storage_key TEXT,
    filename TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_export_records_project
    ON export_records(project_id, created_at DESC);
