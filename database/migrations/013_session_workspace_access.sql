ALTER TABLE projects
    ADD COLUMN IF NOT EXISTS access_token_hash TEXT,
    ADD COLUMN IF NOT EXISTS client_ip_hash TEXT,
    ADD COLUMN IF NOT EXISTS access_bound_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_projects_access_token_hash
    ON projects(access_token_hash)
    WHERE access_token_hash IS NOT NULL;

COMMENT ON COLUMN projects.access_token_hash IS
    'Hash of an ephemeral browser-session token; the raw token is never stored.';
COMMENT ON COLUMN projects.client_ip_hash IS
    'Session-keyed hash of the originating client IP.';
