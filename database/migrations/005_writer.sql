CREATE TABLE IF NOT EXISTS sections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'drafting' CHECK (
        status IN (
            'drafting', 'generated', 'generation_failed',
            'edited', 'approved'
        )
    ),
    current_version_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sections_project
    ON sections(project_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS section_requirements (
    section_id UUID NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
    requirement_id UUID NOT NULL REFERENCES requirements(id)
        ON DELETE RESTRICT,
    PRIMARY KEY (section_id, requirement_id)
);

CREATE TABLE IF NOT EXISTS section_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    section_id UUID NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
    version_no INTEGER NOT NULL,
    content TEXT NOT NULL,
    origin TEXT NOT NULL CHECK (origin IN ('generated', 'edited')),
    input_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (section_id, version_no)
);

ALTER TABLE sections
    ADD CONSTRAINT fk_sections_current_version
    FOREIGN KEY (current_version_id) REFERENCES section_versions(id)
    DEFERRABLE INITIALLY DEFERRED;

CREATE TABLE IF NOT EXISTS review_findings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    section_version_id UUID NOT NULL REFERENCES section_versions(id)
        ON DELETE CASCADE,
    finding_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (
        severity IN ('info', 'warning', 'blocking')
    ),
    message TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
