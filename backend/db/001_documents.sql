CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    document_type TEXT,
    status TEXT NOT NULL CHECK (
        status IN (
            'queued',
            'processing',
            'completed',
            'unsupported',
            'failed'
        )
    ),
    stage TEXT,
    message TEXT,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    legal_json JSONB,
    pdf_storage_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_status
    ON documents (status);
