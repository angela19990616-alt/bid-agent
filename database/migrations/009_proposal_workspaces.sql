ALTER TABLE requirements
    ADD COLUMN IF NOT EXISTS proposal_relevance TEXT NOT NULL DEFAULT 'low',
    ADD COLUMN IF NOT EXISTS target_chapter TEXT,
    ADD COLUMN IF NOT EXISTS need_generation BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE requirements
    DROP CONSTRAINT IF EXISTS requirements_proposal_relevance_check;

ALTER TABLE requirements
    ADD CONSTRAINT requirements_proposal_relevance_check CHECK (
        proposal_relevance IN ('high', 'medium', 'low')
    );

CREATE INDEX IF NOT EXISTS idx_requirements_proposal_generation
    ON requirements(project_id, need_generation, proposal_relevance);

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS validation_status TEXT NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS validation_score NUMERIC(4, 3),
    ADD COLUMN IF NOT EXISTS validation_reason TEXT,
    ADD COLUMN IF NOT EXISTS knowledge_status TEXT NOT NULL DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS knowledge_scope TEXT NOT NULL
        DEFAULT 'organization_private';

ALTER TABLE documents
    DROP CONSTRAINT IF EXISTS documents_validation_status_check,
    DROP CONSTRAINT IF EXISTS documents_validation_score_check,
    DROP CONSTRAINT IF EXISTS documents_knowledge_status_check,
    DROP CONSTRAINT IF EXISTS documents_knowledge_scope_check;

ALTER TABLE documents
    ADD CONSTRAINT documents_validation_status_check CHECK (
        validation_status IN ('pending', 'valid', 'invalid')
    ),
    ADD CONSTRAINT documents_validation_score_check CHECK (
        validation_score IS NULL
        OR validation_score BETWEEN 0 AND 1
    ),
    ADD CONSTRAINT documents_knowledge_status_check CHECK (
        knowledge_status IN (
            'pending', 'eligible', 'duplicate', 'excluded', 'indexed'
        )
    ),
    ADD CONSTRAINT documents_knowledge_scope_check CHECK (
        knowledge_scope = 'organization_private'
    );

CREATE INDEX IF NOT EXISTS idx_documents_private_knowledge
    ON documents(knowledge_scope, knowledge_status, sha256);

ALTER TABLE sections
    ADD COLUMN IF NOT EXISTS sort_order INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS is_recommended BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_sections_project_order
    ON sections(project_id, sort_order, created_at);

ALTER TABLE projects
    DROP CONSTRAINT IF EXISTS projects_status_check;

ALTER TABLE projects
    ADD CONSTRAINT projects_status_check CHECK (
        status IN (
            'draft',
            'validating',
            'parsing',
            'extracting',
            'planning',
            'outline_ready',
            'reviewing_requirements',
            'writing',
            'ready_to_export',
            'exported'
        )
    );
