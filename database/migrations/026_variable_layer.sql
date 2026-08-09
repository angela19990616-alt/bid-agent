ALTER TABLE enterprise_people
    ADD COLUMN IF NOT EXISTS employment_history JSONB NOT NULL
        DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS role_history JSONB NOT NULL
        DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS certification_history JSONB NOT NULL
        DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS project_participation JSONB NOT NULL
        DEFAULT '[]'::jsonb;

CREATE INDEX IF NOT EXISTS idx_enterprise_people_employment_history
    ON enterprise_people USING GIN (employment_history);

CREATE INDEX IF NOT EXISTS idx_enterprise_people_certification_history
    ON enterprise_people USING GIN (certification_history);
