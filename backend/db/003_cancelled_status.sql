-- Allow documents.status = 'cancelled' (a user stopped processing).
-- Idempotent: safe to run more than once. It does not delete or rewrite rows.
-- Existing databases do not pick this up from 001_documents.sql, because that file
-- only creates the table when it is missing. Apply this file by hand (see Documentation/database-poc.md).
ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_status_check;

ALTER TABLE documents ADD CONSTRAINT documents_status_check CHECK (
    status IN (
        'queued',
        'processing',
        'completed',
        'unsupported',
        'failed',
        'cancelled'
    )
);
