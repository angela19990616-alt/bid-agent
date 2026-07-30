ALTER TABLE rule_definitions
    DROP CONSTRAINT IF EXISTS rule_definitions_rule_type_check;

ALTER TABLE rule_definitions
    ADD CONSTRAINT rule_definitions_rule_type_check CHECK (
        rule_type IN (
            'extraction', 'classification', 'knowledge',
            'proposal_memory', 'writing', 'compliance'
        )
    );

CREATE TABLE IF NOT EXISTS proposal_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_key TEXT NOT NULL DEFAULT 'default',
    project_type TEXT NOT NULL,
    industry TEXT NOT NULL,
    chapter_title TEXT NOT NULL,
    pattern JSONB NOT NULL,
    source_knowledge_id UUID REFERENCES enterprise_knowledge(id)
        ON DELETE SET NULL,
    permission_scope TEXT NOT NULL DEFAULT 'organization_private'
        CHECK (permission_scope = 'organization_private'),
    quality_score NUMERIC(4,3) NOT NULL CHECK (
        quality_score BETWEEN 0 AND 1
    ),
    review_status TEXT NOT NULL DEFAULT 'approved' CHECK (
        review_status IN ('draft', 'approved', 'retired')
    ),
    checksum TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_key, checksum)
);

CREATE INDEX IF NOT EXISTS idx_proposal_memory_match
    ON proposal_memory(
        organization_key, permission_scope, review_status,
        chapter_title, quality_score DESC
    );

ALTER TABLE section_versions
    ADD COLUMN IF NOT EXISTS memory_snapshot JSONB NOT NULL
        DEFAULT '[]'::jsonb;
