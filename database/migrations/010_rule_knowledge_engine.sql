CREATE TABLE IF NOT EXISTS rule_definitions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_key TEXT NOT NULL DEFAULT 'default',
    rule_type TEXT NOT NULL CHECK (
        rule_type IN ('extraction', 'writing', 'compliance')
    ),
    rule_key TEXT NOT NULL,
    name TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (
        status IN ('draft', 'active', 'retired')
    ),
    source TEXT NOT NULL DEFAULT 'manual' CHECK (
        source IN ('system', 'manual', 'ai_generated')
    ),
    content JSONB NOT NULL,
    checksum TEXT NOT NULL,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    activated_at TIMESTAMPTZ,
    UNIQUE (organization_key, rule_type, rule_key, version)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_active_rule_per_type
    ON rule_definitions(organization_key, rule_type)
    WHERE status = 'active';

CREATE TABLE IF NOT EXISTS enterprise_knowledge (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_key TEXT NOT NULL DEFAULT 'default',
    category TEXT NOT NULL CHECK (
        category IN (
            'company_profile', 'qualification', 'product_capability',
            'technical_capability', 'case_study', 'standard_template',
            'expert_experience', 'historical_bid', 'common_chapter'
        )
    ),
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_document_id BIGINT REFERENCES documents(id) ON DELETE SET NULL,
    permission_scope TEXT NOT NULL DEFAULT 'organization_private' CHECK (
        permission_scope = 'organization_private'
    ),
    status TEXT NOT NULL DEFAULT 'active' CHECK (
        status IN ('draft', 'active', 'retired')
    ),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    checksum TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_enterprise_knowledge_lookup
    ON enterprise_knowledge(organization_key, status, category);

CREATE TABLE IF NOT EXISTS workflow_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'running' CHECK (
        status IN ('running', 'succeeded', 'failed')
    ),
    current_stage TEXT NOT NULL,
    rule_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    knowledge_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    stage_trace JSONB NOT NULL DEFAULT '[]'::jsonb,
    error_code TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_workflow_runs_project
    ON workflow_runs(project_id, created_at DESC);

CREATE TABLE IF NOT EXISTS knowledge_matches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workflow_run_id UUID NOT NULL REFERENCES workflow_runs(id)
        ON DELETE CASCADE,
    section_id UUID REFERENCES sections(id) ON DELETE CASCADE,
    requirement_id UUID REFERENCES requirements(id) ON DELETE CASCADE,
    knowledge_id UUID NOT NULL REFERENCES enterprise_knowledge(id)
        ON DELETE RESTRICT,
    score NUMERIC(5,4) NOT NULL CHECK (score BETWEEN 0 AND 1),
    rationale TEXT NOT NULL,
    selected BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (
        workflow_run_id, section_id, requirement_id, knowledge_id
    )
);

ALTER TABLE section_versions
    ADD COLUMN IF NOT EXISTS rule_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS knowledge_snapshot JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE processing_jobs
    ADD COLUMN IF NOT EXISTS workflow_run_id UUID REFERENCES workflow_runs(id)
        ON DELETE SET NULL;

ALTER TABLE export_records
    ALTER COLUMN section_id DROP NOT NULL,
    ALTER COLUMN section_version_id DROP NOT NULL,
    ADD COLUMN IF NOT EXISTS export_scope TEXT NOT NULL DEFAULT 'section'
        CHECK (export_scope IN ('section', 'full_proposal'));
