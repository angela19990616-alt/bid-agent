CREATE TABLE IF NOT EXISTS requirements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    requirement_type TEXT NOT NULL CHECK (
        requirement_type IN (
            'technical', 'scoring', 'delivery', 'qualification'
        )
    ),
    title TEXT NOT NULL,
    normalized_text TEXT NOT NULL,
    quote TEXT NOT NULL,
    importance TEXT NOT NULL DEFAULT 'medium' CHECK (
        importance IN ('low', 'medium', 'high')
    ),
    confidence NUMERIC(4, 3) NOT NULL CHECK (
        confidence BETWEEN 0 AND 1
    ),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'confirmed', 'rejected')
    ),
    fingerprint TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (project_id, fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_requirements_project_status
    ON requirements(project_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS requirement_sources (
    requirement_id UUID NOT NULL REFERENCES requirements(id)
        ON DELETE CASCADE,
    source_chunk_id UUID NOT NULL REFERENCES source_chunks(id)
        ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (requirement_id, source_chunk_id)
);

CREATE INDEX IF NOT EXISTS idx_requirement_sources_source
    ON requirement_sources(source_chunk_id);
