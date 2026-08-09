ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS organization_key TEXT NOT NULL
        DEFAULT 'default';

CREATE INDEX IF NOT EXISTS idx_projects_organization
    ON projects(organization_key, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_enterprise_knowledge_permission
    ON enterprise_knowledge(
        organization_key, permission_scope, status, category
    );
