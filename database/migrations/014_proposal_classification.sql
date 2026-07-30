ALTER TABLE rule_definitions
    DROP CONSTRAINT IF EXISTS rule_definitions_rule_type_check;

ALTER TABLE rule_definitions
    ADD CONSTRAINT rule_definitions_rule_type_check CHECK (
        rule_type IN (
            'extraction', 'classification', 'knowledge',
            'writing', 'compliance'
        )
    );

ALTER TABLE requirements
    DROP CONSTRAINT IF EXISTS requirements_requirement_type_check,
    DROP CONSTRAINT IF EXISTS requirements_importance_check;

UPDATE requirements
SET requirement_type = CASE requirement_type
    WHEN 'technical' THEN 'technical_capability'
    WHEN 'scoring' THEN 'scoring_requirement'
    WHEN 'delivery' THEN 'delivery_requirement'
    WHEN 'qualification' THEN 'qualification_requirement'
    WHEN 'commercial' THEN 'commercial_requirement'
    WHEN 'compliance' THEN 'other'
    ELSE requirement_type
END;

ALTER TABLE requirements
    ADD COLUMN IF NOT EXISTS proposal_chapter TEXT,
    ADD COLUMN IF NOT EXISTS scoring_relation TEXT NOT NULL
        DEFAULT 'unknown',
    ADD COLUMN IF NOT EXISTS classification_confidence NUMERIC(4, 3)
        NOT NULL DEFAULT 0.500,
    ADD COLUMN IF NOT EXISTS classification_conflict BOOLEAN NOT NULL
        DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS classification_notes TEXT,
    ADD COLUMN IF NOT EXISTS knowledge_support_required BOOLEAN NOT NULL
        DEFAULT FALSE;

UPDATE requirements
SET proposal_chapter = target_chapter
WHERE proposal_chapter IS NULL AND need_generation = TRUE;

ALTER TABLE requirements
    ADD CONSTRAINT requirements_requirement_type_check CHECK (
        requirement_type IN (
            'technical_capability', 'functional_requirement',
            'system_architecture', 'security_requirement',
            'performance_requirement', 'implementation_requirement',
            'project_management', 'operation_maintenance',
            'training_requirement', 'delivery_requirement',
            'commercial_requirement', 'qualification_requirement',
            'scoring_requirement', 'other'
        )
    ),
    ADD CONSTRAINT requirements_importance_check CHECK (
        importance IN ('low', 'medium', 'high', 'critical')
    ),
    ADD CONSTRAINT requirements_scoring_relation_check CHECK (
        scoring_relation IN (
            'high_score_item', 'medium_score_item',
            'requirement_only', 'unknown'
        )
    ),
    ADD CONSTRAINT requirements_classification_confidence_check CHECK (
        classification_confidence BETWEEN 0 AND 1
    );

CREATE INDEX IF NOT EXISTS idx_requirements_proposal_classification
    ON requirements(
        project_id, requirement_type, proposal_chapter,
        classification_conflict
    );
