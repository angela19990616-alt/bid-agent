ALTER TABLE rule_definitions
    DROP CONSTRAINT IF EXISTS rule_definitions_rule_type_check;

ALTER TABLE rule_definitions
    ADD CONSTRAINT rule_definitions_rule_type_check CHECK (
        rule_type IN (
            'extraction', 'classification', 'response_strategy',
            'knowledge', 'proposal_memory', 'writing', 'compliance',
            'conflict_detection', 'response_prioritization',
            'template_generation', 'entity_relation'
        )
    );

ALTER TABLE requirements
    ADD COLUMN IF NOT EXISTS semantic_graph JSONB NOT NULL
        DEFAULT '{"entities":[],"relations":[],"actions":[],"material_entities":[],"constraints":[],"confidence":0}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_requirements_semantic_graph
    ON requirements USING GIN (semantic_graph);

CREATE TABLE IF NOT EXISTS enterprise_people (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_key TEXT NOT NULL DEFAULT 'default',
    name TEXT NOT NULL,
    id_number_ciphertext BYTEA,
    id_number_masked TEXT,
    title TEXT,
    phone_ciphertext BYTEA,
    phone_masked TEXT,
    certificates JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_documents JSONB NOT NULL DEFAULT '[]'::jsonb,
    permission_scope TEXT NOT NULL DEFAULT 'organization_private' CHECK (
        permission_scope = 'organization_private'
    ),
    verification_status TEXT NOT NULL DEFAULT 'pending' CHECK (
        verification_status IN ('pending', 'verified', 'rejected')
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_enterprise_people_lookup
    ON enterprise_people(
        organization_key, permission_scope, verification_status, name
    );

CREATE TABLE IF NOT EXISTS enterprise_organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_key TEXT NOT NULL DEFAULT 'default',
    full_name TEXT NOT NULL,
    unified_social_credit_code TEXT,
    registered_address TEXT,
    legal_representative_person_id UUID REFERENCES enterprise_people(id)
        ON DELETE SET NULL,
    source_document_id BIGINT REFERENCES documents(id) ON DELETE SET NULL,
    source_location JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence NUMERIC(4,3) NOT NULL DEFAULT 1 CHECK (
        confidence BETWEEN 0 AND 1
    ),
    permission_scope TEXT NOT NULL DEFAULT 'organization_private' CHECK (
        permission_scope = 'organization_private'
    ),
    verification_status TEXT NOT NULL DEFAULT 'pending' CHECK (
        verification_status IN ('pending', 'verified', 'rejected')
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_key, full_name)
);

ALTER TABLE enterprise_people
    ADD COLUMN IF NOT EXISTS organization_id UUID
        REFERENCES enterprise_organizations(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_enterprise_people_organization
    ON enterprise_people(organization_id, verification_status, name);

ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS bidder_organization_id UUID
        REFERENCES enterprise_organizations(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS project_role_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    organization_id UUID NOT NULL REFERENCES enterprise_organizations(id)
        ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (
        role IN (
            'LEGAL_REPRESENTATIVE', 'AUTHORIZED_REPRESENTATIVE',
            'PROJECT_MANAGER', 'TECHNICAL_LEAD', 'CONTACT_PERSON',
            'SIGNATORY'
        )
    ),
    person_id UUID NOT NULL REFERENCES enterprise_people(id)
        ON DELETE RESTRICT,
    authorization_document_id BIGINT REFERENCES documents(id)
        ON DELETE SET NULL,
    valid_from DATE,
    valid_to DATE,
    status TEXT NOT NULL DEFAULT 'active' CHECK (
        status IN ('draft', 'active', 'expired', 'revoked')
    ),
    source_document TEXT,
    source_location JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence NUMERIC(4,3) NOT NULL DEFAULT 1 CHECK (
        confidence BETWEEN 0 AND 1
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_active_project_role_assignment
    ON project_role_assignments(project_id, role)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_project_role_person
    ON project_role_assignments(person_id, project_id, status);
