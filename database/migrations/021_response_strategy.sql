ALTER TABLE rule_definitions
    DROP CONSTRAINT IF EXISTS rule_definitions_rule_type_check;

ALTER TABLE rule_definitions
    ADD CONSTRAINT rule_definitions_rule_type_check CHECK (
        rule_type IN (
            'extraction', 'classification', 'response_strategy',
            'knowledge', 'proposal_memory', 'writing', 'compliance'
        )
    );

ALTER TABLE requirements
    DROP CONSTRAINT IF EXISTS requirements_requirement_type_check;

ALTER TABLE requirements
    ADD CONSTRAINT requirements_requirement_type_check CHECK (
        requirement_type IN (
            'technical_requirement', 'scoring_requirement',
            'commercial_requirement', 'qualification_requirement',
            'delivery_requirement', 'compliance_requirement',
            'format_requirement', 'document_structure_requirement'
        )
    );

UPDATE requirements
SET requirement_type = 'commercial_requirement',
    response_action = 'compliance_commitment',
    proposal_mapping = NULL,
    proposal_chapter = NULL,
    target_chapter = NULL,
    need_generation = FALSE,
    scoring_impact = 'penalty_risk',
    priority = 'P0'
WHERE normalized_text ~ '不得分包|禁止分包|不得转包|禁止转包'
   OR quote ~ '不得分包|禁止分包|不得转包|禁止转包';

UPDATE requirements
SET requirement_type = 'document_structure_requirement',
    response_action = 'risk_notice',
    proposal_mapping = NULL,
    proposal_chapter = NULL,
    target_chapter = NULL,
    need_generation = FALSE,
    scoring_impact = 'penalty_risk'
WHERE normalized_text ~ '目录格式|章节顺序|响应文件组成|文件结构|章节组成'
   OR quote ~ '目录格式|章节顺序|响应文件组成|文件结构|章节组成';
