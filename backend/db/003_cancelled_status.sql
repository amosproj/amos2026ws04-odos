-- Allow documents.status = 'cancelled'. Additive and idempotent: it only widens the CHECK constraint when it does not
-- yet allow 'cancelled', and never touches a row. A fresh volume gets it from docker-entrypoint-initdb.d; for an existing
-- database the API applies the same statement when it starts with ODOS_DATABASE_ENABLED=1 (odos.document_repository).
DO $$
BEGIN
    IF to_regclass('documents') IS NOT NULL AND EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'documents'::regclass AND contype = 'c'
          AND pg_get_constraintdef(oid) LIKE '%status%'
          AND pg_get_constraintdef(oid) NOT LIKE '%cancelled%'
    ) THEN
        ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_status_check;
        ALTER TABLE documents ADD CONSTRAINT documents_status_check CHECK (
            status IN ('queued', 'processing', 'completed', 'unsupported', 'failed', 'cancelled')
        );
    END IF;
END $$;
