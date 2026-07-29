ALTER TABLE section_versions
    DROP CONSTRAINT IF EXISTS section_versions_origin_check;

ALTER TABLE section_versions
    ADD CONSTRAINT section_versions_origin_check CHECK (
        origin IN ('generated', 'edited', 'auto_fixed')
    );

CREATE TABLE IF NOT EXISTS content_provenance (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    section_version_id UUID NOT NULL REFERENCES section_versions(id)
        ON DELETE CASCADE,
    paragraph_id TEXT NOT NULL,
    paragraph_index INTEGER NOT NULL CHECK (paragraph_index >= 0),
    source_type TEXT NOT NULL CHECK (
        source_type IN (
            'procurement_document', 'requirement', 'scoring_criterion',
            'enterprise_knowledge', 'historical_case',
            'regulation_policy', 'user_confirmed', 'model_inference',
            'unknown'
        )
    ),
    source_id TEXT,
    source_title TEXT NOT NULL,
    source_location TEXT,
    source_excerpt TEXT,
    usage_description TEXT NOT NULL,
    verification_status TEXT NOT NULL CHECK (
        verification_status IN (
            'verified', 'unverified', 'user_confirmed',
            'not_applicable', 'rejected'
        )
    ),
    confidence NUMERIC(5,4) NOT NULL CHECK (
        confidence BETWEEN 0 AND 1
    ),
    generated_section TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (
        section_version_id, paragraph_id, source_type,
        source_title, usage_description
    )
);

CREATE INDEX IF NOT EXISTS idx_content_provenance_version
    ON content_provenance(section_version_id, paragraph_index);

CREATE TABLE IF NOT EXISTS historical_case_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    section_version_id UUID NOT NULL REFERENCES section_versions(id)
        ON DELETE CASCADE,
    knowledge_id UUID REFERENCES enterprise_knowledge(id)
        ON DELETE SET NULL,
    case_title TEXT NOT NULL,
    section_title TEXT NOT NULL,
    content_summary TEXT NOT NULL,
    usage_type TEXT NOT NULL CHECK (
        usage_type IN (
            'direct_quote', 'structure_reference', 'parameter_reference',
            'language_reference'
        )
    ),
    adapted_for_current_project BOOLEAN NOT NULL DEFAULT TRUE,
    contains_enterprise_fact BOOLEAN NOT NULL DEFAULT FALSE,
    enterprise_fact_verified BOOLEAN NOT NULL DEFAULT FALSE,
    allowed_in_final BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_historical_case_usage_version
    ON historical_case_usage(section_version_id);

CREATE TABLE IF NOT EXISTS proposal_reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    phase TEXT NOT NULL CHECK (phase IN ('initial', 'final')),
    status TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
    deliverable BOOLEAN NOT NULL DEFAULT FALSE,
    report JSONB NOT NULL,
    json_storage_key TEXT,
    readable_storage_key TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_proposal_reviews_project
    ON proposal_reviews(project_id, created_at DESC);

ALTER TABLE export_records
    ADD COLUMN IF NOT EXISTS proposal_review_id UUID
        REFERENCES proposal_reviews(id) ON DELETE SET NULL;
