-- Human review decisions on extracted rules (see Documentation/review-state-design.md).
-- Additive and idempotent: it only creates this table; `documents` and the stored rules.json files are not touched.
-- On an existing database apply it by hand (after a backup), see Documentation/database-poc.md; the API never migrates.
-- Rollback: DROP TABLE rule_reviews;

CREATE TABLE IF NOT EXISTS rule_reviews (
    id            BIGSERIAL PRIMARY KEY,
    document_id   TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    extraction_id TEXT NOT NULL,   -- _generation.generatedAt of the reviewed rules.json (else "sha256:" + file hash)
    rule_id       TEXT NOT NULL,
    rule_sha256   TEXT NOT NULL,   -- SHA-256 of the canonical JSON of the ORIGINAL record in rules.json
    action        TEXT NOT NULL CHECK (action IN ('accept', 'reject', 'edit', 'reset')),
    decision      TEXT NOT NULL CHECK (decision IN ('pending', 'accepted', 'rejected')),  -- state after this event
    reviewer      TEXT NOT NULL CHECK (char_length(reviewer) BETWEEN 1 AND 100),  -- self-declared, not authenticated
    reason        TEXT CHECK (char_length(reason) <= 2000),
    edited_rule   JSONB,           -- the effective edited record after this event; NULL = the original record
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (action <> 'reject' OR (reason IS NOT NULL AND char_length(btrim(reason)) > 0)),
    CHECK (action <> 'reset' OR edited_rule IS NULL)
);

CREATE INDEX IF NOT EXISTS idx_rule_reviews_current
    ON rule_reviews (document_id, extraction_id, rule_id, id DESC);
