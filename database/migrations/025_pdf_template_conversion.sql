ALTER TABLE proposal_generation_profiles
    DROP CONSTRAINT IF EXISTS proposal_generation_profiles_generation_mode_check;

ALTER TABLE proposal_generation_profiles
    ADD CONSTRAINT proposal_generation_profiles_generation_mode_check CHECK (
        generation_mode IN (
            'strict_template', 'planned', 'pdf_template_manual_fill',
            'template_conversion_required'
        )
    ),
    ADD COLUMN IF NOT EXISTS writer_strategy TEXT,
    ADD COLUMN IF NOT EXISTS converted_template_storage_key TEXT,
    ADD COLUMN IF NOT EXISTS template_conversion_status TEXT NOT NULL
        DEFAULT 'not_required',
    ADD COLUMN IF NOT EXISTS template_conversion_report JSONB NOT NULL
        DEFAULT '{}'::jsonb;

UPDATE proposal_generation_profiles
SET writer_strategy = CASE generation_mode
    WHEN 'strict_template' THEN 'strict_template_writer'
    WHEN 'planned' THEN 'planned_proposal_writer'
    ELSE NULL
END
WHERE writer_strategy IS NULL;

ALTER TABLE proposal_generation_profiles
    DROP CONSTRAINT IF EXISTS proposal_generation_profiles_writer_strategy_check;

ALTER TABLE proposal_generation_profiles
    ADD CONSTRAINT proposal_generation_profiles_writer_strategy_check CHECK (
        writer_strategy IS NULL OR writer_strategy IN (
            'strict_template_writer', 'planned_proposal_writer'
        )
    );

ALTER TABLE proposal_generation_profiles
    DROP CONSTRAINT IF EXISTS proposal_generation_profiles_conversion_status_check;

ALTER TABLE proposal_generation_profiles
    ADD CONSTRAINT proposal_generation_profiles_conversion_status_check CHECK (
        template_conversion_status IN (
            'not_required', 'pending', 'succeeded', 'failed',
            'structure_validation_failed'
        )
    );
