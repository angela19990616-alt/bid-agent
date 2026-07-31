ALTER TABLE rule_definitions
    DROP CONSTRAINT IF EXISTS rule_definitions_rule_type_check;

ALTER TABLE rule_definitions
    ADD CONSTRAINT rule_definitions_rule_type_check CHECK (
        rule_type IN (
            'extraction', 'classification', 'response_strategy',
            'conflict_detection', 'response_prioritization',
            'knowledge', 'proposal_memory', 'writing', 'compliance'
        )
    );

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS document_role TEXT NOT NULL DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS source_authority_level SMALLINT NOT NULL DEFAULT 9;

ALTER TABLE requirements
    ADD COLUMN IF NOT EXISTS proposal_value SMALLINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS risk_type TEXT;

ALTER TABLE requirements
    DROP CONSTRAINT IF EXISTS requirements_proposal_value_check;

ALTER TABLE requirements
    ADD CONSTRAINT requirements_proposal_value_check
    CHECK (proposal_value BETWEEN 0 AND 5);

ALTER TABLE requirements
    DROP CONSTRAINT IF EXISTS requirements_risk_type_check;

ALTER TABLE requirements
    ADD CONSTRAINT requirements_risk_type_check
    CHECK (
        risk_type IS NULL OR risk_type IN (
            'disqualification', 'qualification', 'contract', 'delivery'
        )
    );

ALTER TABLE requirements
    DROP CONSTRAINT IF EXISTS requirements_proposal_relevance_check;

ALTER TABLE requirements
    ALTER COLUMN proposal_relevance DROP DEFAULT;

ALTER TABLE requirements
    ALTER COLUMN proposal_relevance TYPE BOOLEAN
    USING proposal_relevance IN ('high', 'medium');

ALTER TABLE requirements
    ALTER COLUMN proposal_relevance SET DEFAULT FALSE,
    ALTER COLUMN proposal_relevance SET NOT NULL;

UPDATE requirements
SET proposal_value = CASE
        WHEN response_action <> 'write_into_proposal' THEN 0
        WHEN scoring_impact = 'score_item' THEN 5
        WHEN importance IN ('critical', 'high') THEN 4
        WHEN need_generation THEN 3
        ELSE 2
    END,
    risk_type = CASE
        WHEN priority <> 'P0' THEN NULL
        WHEN scoring_impact = 'qualification_pass' THEN 'qualification'
        WHEN requirement_type = 'commercial_requirement' THEN 'contract'
        WHEN requirement_type = 'delivery_requirement' THEN 'delivery'
        ELSE 'disqualification'
    END;

CREATE TABLE IF NOT EXISTS requirement_conflicts (
    conflict_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    topic TEXT NOT NULL,
    conflict_type TEXT NOT NULL CHECK (
        conflict_type IN (
            'positive_difference', 'compatible_difference',
            'potential_conflict', 'true_conflict'
        )
    ),
    requirement_a_id UUID NOT NULL REFERENCES requirements(id)
        ON DELETE CASCADE,
    requirement_b_id UUID NOT NULL REFERENCES requirements(id)
        ON DELETE CASCADE,
    source_a JSONB NOT NULL,
    source_b JSONB NOT NULL,
    source_a_location JSONB NOT NULL,
    source_b_location JSONB NOT NULL,
    source_a_authority_level SMALLINT NOT NULL DEFAULT 9,
    source_b_authority_level SMALLINT NOT NULL DEFAULT 9,
    description TEXT NOT NULL,
    risk_priority TEXT NOT NULL DEFAULT 'P3' CHECK (
        risk_priority IN ('P0', 'P1', 'P2', 'P3')
    ),
    resolution_status TEXT NOT NULL DEFAULT 'pending' CHECK (
        resolution_status IN ('pending', 'resolved', 'ignored')
    ),
    resolution_choice TEXT CHECK (
        resolution_choice IS NULL OR resolution_choice IN (
            'choose_a', 'choose_b', 'keep_both', 'request_clarification'
        )
    ),
    resolved_by TEXT,
    resolved_time TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (
        project_id, requirement_a_id, requirement_b_id, conflict_type
    ),
    CHECK (requirement_a_id <> requirement_b_id)
);

CREATE INDEX IF NOT EXISTS idx_requirement_conflicts_project
    ON requirement_conflicts(project_id, resolution_status, risk_priority);

CREATE TABLE IF NOT EXISTS conflict_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conflict_id UUID NOT NULL REFERENCES requirement_conflicts(conflict_id)
        ON DELETE CASCADE,
    version INTEGER NOT NULL,
    resolution_choice TEXT NOT NULL CHECK (
        resolution_choice IN (
            'choose_a', 'choose_b', 'keep_both', 'request_clarification'
        )
    ),
    decided_by TEXT NOT NULL,
    decision_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (conflict_id, version)
);

CREATE TABLE IF NOT EXISTS conflict_sections (
    conflict_id UUID NOT NULL REFERENCES requirement_conflicts(conflict_id)
        ON DELETE CASCADE,
    section_id UUID NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (conflict_id, section_id)
);

CREATE INDEX IF NOT EXISTS idx_requirements_planner_gate
    ON requirements (
        project_id, response_action, proposal_relevance, target_chapter
    );
