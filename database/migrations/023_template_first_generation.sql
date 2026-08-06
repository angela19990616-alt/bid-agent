ALTER TABLE rule_definitions
    DROP CONSTRAINT IF EXISTS rule_definitions_rule_type_check;

ALTER TABLE rule_definitions
    ADD CONSTRAINT rule_definitions_rule_type_check CHECK (
        rule_type IN (
            'extraction', 'classification', 'response_strategy',
            'knowledge', 'proposal_memory', 'writing', 'compliance',
            'conflict_detection', 'response_prioritization',
            'template_generation'
        )
    );

CREATE TABLE IF NOT EXISTS proposal_generation_profiles (
    project_id UUID PRIMARY KEY REFERENCES projects(id) ON DELETE CASCADE,
    generation_mode TEXT NOT NULL DEFAULT 'planned' CHECK (
        generation_mode IN (
            'strict_template', 'planned', 'pdf_template_manual_fill'
        )
    ),
    template_document_id BIGINT REFERENCES documents(id) ON DELETE SET NULL,
    template_descriptor JSONB NOT NULL DEFAULT '{}'::jsonb,
    template_field_values JSONB NOT NULL DEFAULT '{}'::jsonb,
    historical_case_mode TEXT NOT NULL DEFAULT 'closest_case' CHECK (
        historical_case_mode IN (
            'closest_case', 'balanced', 'structure_only', 'current_only'
        )
    ),
    last_fill_report JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE proposal_generation_profiles
    ADD COLUMN IF NOT EXISTS template_field_values JSONB
    NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_generation_profile_template
    ON proposal_generation_profiles(template_document_id, generation_mode);
