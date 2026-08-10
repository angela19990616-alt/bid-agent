ALTER TABLE rule_definitions
    DROP CONSTRAINT IF EXISTS rule_definitions_rule_type_check;

ALTER TABLE rule_definitions
    ADD CONSTRAINT rule_definitions_rule_type_check CHECK (
        rule_type IN (
            'extraction', 'classification', 'response_strategy',
            'knowledge', 'proposal_memory', 'writing', 'compliance',
            'conflict_detection', 'response_prioritization',
            'template_generation', 'entity_relation',
            'business_validation'
        )
    );

CREATE TABLE IF NOT EXISTS project_business_reviews (
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    review_key TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    category TEXT NOT NULL CHECK (
        category IN (
            'outline', 'format', 'commercial_deviation',
            'scoring_evidence', 'qualification_material'
        )
    ),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'confirmed', 'rejected')
    ),
    decision_note TEXT,
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (project_id, review_key)
);

CREATE INDEX IF NOT EXISTS idx_project_business_reviews_status
    ON project_business_reviews(project_id, status, category);
