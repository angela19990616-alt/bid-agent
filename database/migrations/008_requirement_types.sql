ALTER TABLE requirements
    DROP CONSTRAINT IF EXISTS requirements_requirement_type_check;

ALTER TABLE requirements
    ADD CONSTRAINT requirements_requirement_type_check CHECK (
        requirement_type IN (
            'technical',
            'scoring',
            'delivery',
            'qualification',
            'compliance',
            'commercial'
        )
    );
