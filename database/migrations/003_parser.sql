ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS public_id UUID NOT NULL DEFAULT gen_random_uuid(),
    ADD COLUMN IF NOT EXISTS sha256 TEXT,
    ADD COLUMN IF NOT EXISTS size_bytes BIGINT,
    ADD COLUMN IF NOT EXISTS storage_key TEXT,
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'parsed',
    ADD COLUMN IF NOT EXISTS error_code TEXT,
    ADD COLUMN IF NOT EXISTS error_message TEXT,
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_public_id
    ON documents(public_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_project_sha256
    ON documents(project_id, sha256)
    WHERE project_id IS NOT NULL AND sha256 IS NOT NULL;

CREATE TABLE IF NOT EXISTS source_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    locator_kind TEXT NOT NULL CHECK (
        locator_kind IN ('page', 'paragraph')
    ),
    page_no INTEGER,
    paragraph_start INTEGER,
    paragraph_end INTEGER,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (document_id, chunk_index),
    CHECK (
        (
            locator_kind = 'page'
            AND page_no IS NOT NULL
            AND paragraph_start IS NULL
            AND paragraph_end IS NULL
        )
        OR
        (
            locator_kind = 'paragraph'
            AND page_no IS NULL
            AND paragraph_start IS NOT NULL
            AND paragraph_end IS NOT NULL
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_source_chunks_document_id
    ON source_chunks(document_id, chunk_index);
