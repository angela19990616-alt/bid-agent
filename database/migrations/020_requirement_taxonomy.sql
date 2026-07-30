ALTER TABLE requirements
    ADD COLUMN IF NOT EXISTS response_action TEXT,
    ADD COLUMN IF NOT EXISTS proposal_mapping TEXT,
    ADD COLUMN IF NOT EXISTS scoring_impact TEXT,
    ADD COLUMN IF NOT EXISTS priority TEXT;

UPDATE requirements
SET
    response_action = CASE
        WHEN need_generation AND proposal_chapter IS NOT NULL
            THEN 'write_into_proposal'
        WHEN requirement_type = 'qualification_requirement'
            THEN 'provide_attachment'
        WHEN requirement_type IN ('commercial_requirement', 'other')
            THEN 'compliance_commitment'
        ELSE 'write_into_response_table'
    END,
    proposal_mapping = CASE
        WHEN need_generation THEN proposal_chapter
        ELSE NULL
    END,
    scoring_impact = CASE
        WHEN requirement_type = 'scoring_requirement' THEN 'score_item'
        WHEN requirement_type = 'qualification_requirement'
            THEN 'qualification_pass'
        WHEN importance = 'critical' THEN 'penalty_risk'
        ELSE 'no_score'
    END,
    priority = CASE importance
        WHEN 'critical' THEN 'P0'
        WHEN 'high' THEN 'P1'
        WHEN 'medium' THEN 'P2'
        ELSE 'P3'
    END
WHERE response_action IS NULL
   OR scoring_impact IS NULL
   OR priority IS NULL;

ALTER TABLE requirements
    ALTER COLUMN response_action SET NOT NULL,
    ALTER COLUMN scoring_impact SET NOT NULL,
    ALTER COLUMN priority SET NOT NULL,
    DROP CONSTRAINT IF EXISTS requirements_requirement_type_check;

UPDATE requirements
SET requirement_type = CASE
    WHEN requirement_type IN (
        'technical_capability', 'functional_requirement',
        'system_architecture', 'security_requirement',
        'performance_requirement', 'implementation_requirement',
        'project_management', 'operation_maintenance',
        'training_requirement', 'technical'
    ) THEN 'technical_requirement'
    WHEN requirement_type IN ('scoring_requirement', 'scoring')
        THEN 'scoring_requirement'
    WHEN requirement_type IN ('commercial_requirement', 'commercial')
        THEN 'commercial_requirement'
    WHEN requirement_type IN ('qualification_requirement', 'qualification')
        THEN 'qualification_requirement'
    WHEN requirement_type IN ('delivery_requirement', 'delivery')
        THEN 'delivery_requirement'
    ELSE 'compliance_requirement'
END;

UPDATE requirements
SET requirement_type = 'format_requirement',
    response_action = 'risk_notice',
    proposal_mapping = NULL,
    scoring_impact = 'penalty_risk'
WHERE normalized_text ~ '目录格式|章节顺序|编制格式|字体|字号|行距|页数|字数|装订|签章'
   OR quote ~ '目录格式|章节顺序|编制格式|字体|字号|行距|页数|字数|装订|签章';

UPDATE requirements
SET requirement_type = 'compliance_requirement',
    response_action = 'compliance_commitment',
    proposal_mapping = NULL,
    scoring_impact = 'penalty_risk',
    priority = 'P0',
    need_generation = FALSE,
    proposal_chapter = NULL,
    target_chapter = NULL
WHERE normalized_text ~ '不得分包|禁止分包|不得转包|禁止转包'
   OR quote ~ '不得分包|禁止分包|不得转包|禁止转包';

ALTER TABLE requirements
    ADD CONSTRAINT requirements_requirement_type_check CHECK (
        requirement_type IN (
            'technical_requirement', 'scoring_requirement',
            'commercial_requirement', 'qualification_requirement',
            'delivery_requirement', 'compliance_requirement',
            'format_requirement'
        )
    ),
    ADD CONSTRAINT requirements_response_action_check CHECK (
        response_action IN (
            'write_into_proposal', 'write_into_response_table',
            'compliance_commitment', 'provide_attachment',
            'risk_notice', 'ignore'
        )
    ),
    ADD CONSTRAINT requirements_scoring_impact_check CHECK (
        scoring_impact IN (
            'score_item', 'qualification_pass',
            'penalty_risk', 'no_score'
        )
    ),
    ADD CONSTRAINT requirements_priority_check CHECK (
        priority IN ('P0', 'P1', 'P2', 'P3')
    );

CREATE INDEX IF NOT EXISTS idx_requirements_response_action
    ON requirements(project_id, response_action, priority);
