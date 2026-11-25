# Rule review states: design and implementation

**Status: implemented and in use** (backend, frontend, tests). The migration `backend/db/002_rule_reviews.sql` is applied to the ODOS database of the development environment; other installations apply it once, as described in [database-poc.md](database-poc.md). Only `flagged` and `unverified` exist as automated verification; `checks_passed` waits for calibration (section 5.7). Without the database or the `rule_reviews` table the review endpoints answer `503` with an explanation and the Rule Extraction page keeps Accept / Reject / Edit disabled.

## 1. Starting point

| Fact | Where |
|---|---|
| A rule's `review.status` is `draft`, `reviewed` or `approved` (`Review` has `additionalProperties: false`). The extractor always writes `draft`; nothing can change it. | `backend/schemas/rule-json/rule.schema.json`, `llm/rule_extraction.py` |
| The result is one file per job, `rules.json` (`{ _generation, rules }`), replaced atomically by every successful extraction. Rule IDs are written by the model, so the same ID can mean a different rule in the next run. | `rule_extraction_jobs.py`, `llm/rule_extraction.py` |
| ODOS's automated checks add `ODOS check: …` notes to `review.ambiguities`. They check form, units, duplicates, cross-rule consistency, that numbers of a cited sentence appear in the logic, and that provenance exists. They do not check meaning (operator direction, scope, exceptions, actors, modality, completeness). | `llm/rule_checks.py`, `llm/source_checks.py` |
| The `documents` table holds the document library. Extraction status and `rules.json` live in the job directory, not in PostgreSQL; review decisions are the only extraction-related data in the database (`rule_reviews`). | `backend/db/001_documents.sql`, `002_rule_reviews.sql` |
| The SQL files run only when the PostgreSQL volume is empty (compose mounts `backend/db` into `docker-entrypoint-initdb.d`). There is no migration mechanism, so `002_rule_reviews.sql` reaches an existing database only when it is applied by hand. | `compose.yaml` |
| The API has no authentication, so the reviewer name is self-declared. | `backend/src/odos/api.py` |

## 2. Principles

1. **A person decides.** No automated step ever sets an accepted/approved state. An unflagged rule is not a verified rule.
2. **Two separate concepts, never merged:** the *human review decision* (stored, attributable) and the *automated verification result* (computed, versioned, advisory).
3. **`rules.json` stays the LLM's artifact.** It is not edited in place by review: it is replaced by re-extraction, validated against the schema, and pinned by tests (the baseline fixture's hash). Decisions live in a separate store and are merged on read.
4. **A decision belongs to one exact rule.** It is bound to the extraction run and to a hash of the record, so a decision can never silently attach to a different rule after a re-extraction or an edit. The same holds for what the reviewer *sees*: the page shows review state only for the extraction of the rules on screen (section 5.5).
5. **History is kept.** Decisions are append-only events; the current state is the latest event.

## 3. States

**Human review (stored).** `pending` (default, no event), `accepted`, `rejected`. A reviewer may also supply an edited record, stored with the event (the original is never overwritten). Each event has: reviewer name (self-declared), time, reason. An edit never keeps an earlier acceptance: it returns the rule to `pending`, so the accepted content is always exactly what a person last looked at.

Mapping to Rule JSON on the *approved export only*: `accepted` → `review.status: "approved"`. `reviewed` is not used (ambiguous next to `accepted`). Rejected and pending rules are not exported; rejected rules stay in the history.

**Automated verification (computed, not stored).** A pure function of the record, the Legal JSON and the criteria version, returned in the API response next to each rule:

| Value | Meaning |
|---|---|
| `flagged` | at least one `ODOS check:` note |
| `unverified` | no flag |
| `checks_passed` | every criterion below is met. **Not offered in the first release** (decision 6): only `flagged` and `unverified` are shown until the criteria are calibrated against manually reviewed examples. |

`checks_passed` means "passed ODOS's automated checks, criteria version N". It is shown as its own badge and is never a review decision. It is not stored, so it cannot go stale when criteria change.

### Criteria v1 for `checks_passed` (all must hold)

1. The record is schema-valid and was not repaired (`schemaRepairs` has no entry for it).
2. No `ODOS check:` note, and no model-written ambiguity.
3. Every `primary` source element and sentence resolves in the job's Legal JSON; page numbers are copied from it.
4. Every quantity in the cited sentences appears in the machine-readable logic (the existing quantity check, with no flag).
5. The logic contains no `unresolved` predicate or requirement, and `review.machineCheckable` is not `false`.
6. The rule is not in a duplicate or inconsistency group (shared exceptions, conflicting operators on one fact, one fact with several units).

These criteria catch form and traceability errors. They do **not** establish that the rule says what the law says. They are therefore only useful as a triage signal ("review these first / these last"), never as acceptance. Enabling the `checks_passed` badge should require a calibration run first: a person reviews a sample of rules that would pass, and the proportion they would reject is reported next to the badge. The threshold is for the team to set; this document does not invent one.

## 4. Decisions

1. PostgreSQL stores decisions and the audit history.
2. Reviewer: a manually entered name (self-declared, not authenticated); authentication can come later.
3. Rejected rules stay in the history and are excluded from the approved export; `rules.json` is never modified.
4. No automatic carry-over of decisions after a re-extraction.
5. Accept, Reject and Edit JSON, with validation and an audit trail.
6. Show only `unverified` and `flagged` first; add `checks_passed` after calibration.

## 5. Implementation

### 5.1 Database

`backend/db/002_rule_reviews.sql` is idempotent and additive (nothing in `documents` changes, no row is touched):

```sql
CREATE TABLE IF NOT EXISTS rule_reviews (
    id            BIGSERIAL PRIMARY KEY,
    document_id   TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    extraction_id TEXT NOT NULL,   -- _generation.generatedAt of the reviewed rules.json (else "sha256:" + file hash)
    rule_id       TEXT NOT NULL,
    rule_sha256   TEXT NOT NULL,   -- SHA-256 of the canonical JSON of the ORIGINAL record
    action        TEXT NOT NULL CHECK (action IN ('accept', 'reject', 'edit', 'reset')),
    decision      TEXT NOT NULL CHECK (decision IN ('pending', 'accepted', 'rejected')),  -- state after this event
    reviewer      TEXT NOT NULL CHECK (char_length(reviewer) BETWEEN 1 AND 100),
    reason        TEXT CHECK (char_length(reason) <= 2000),
    edited_rule   JSONB,           -- the effective edited record after this event; NULL = the original
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (action <> 'reject' OR (reason IS NOT NULL AND char_length(btrim(reason)) > 0)),
    CHECK (action <> 'reset' OR edited_rule IS NULL)
);
CREATE INDEX IF NOT EXISTS idx_rule_reviews_current ON rule_reviews (document_id, extraction_id, rule_id, id DESC);
```

* Events are only ever inserted, never updated or deleted by the application. The current state of a rule is its latest event; no event means `pending`, unedited.
* `accept` and `reject` copy the current effective `edited_rule` into the event, so every event is a self-contained snapshot of what was decided on. `edit` sets `decision = pending`. `reset` discards the edit (`edited_rule = NULL`, `pending`).
* `ON DELETE CASCADE`: deleting a document from the library removes its history with it. This was accepted for the prototype; the alternative (no foreign key, history kept for deleted documents) leaves orphaned rows.

**Migration.** ODOS has no migration tool, and the SQL files run automatically only on an empty volume:

1. A fresh installation creates `rule_reviews` with the other tables. An existing installation applies the file once, after a backup:
   `docker exec -i odos-postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' < backend/db/002_rule_reviews.sql` (backup and rollback commands: [database-poc.md](database-poc.md)). Rollback is `DROP TABLE rule_reviews`, which cannot affect `documents`.
2. The API never migrates on its own. If the table is missing, the review endpoints answer `503` with a plain message that names the file and [database-poc.md](database-poc.md); the frontend then keeps the controls disabled and shows that message. Everything else keeps working. (There is no separate error code: clients rely on the status and the message.)
3. Tests run only against a database whose name ends in `_test` (existing guard). The `db` fixture applies both SQL files and truncates both tables; the regular database is never connected to.

### 5.2 Backend code

* `backend/src/odos/rule_reviews.py`: canonical hash, request validation, the edit rules below, state derivation from events, approved export. No SQL.
* `backend/src/odos/rule_review_repository.py`: parameterized SQL only (append event, latest event per rule, history of one rule, counts). An advisory transaction lock per (document, rule) makes the "latest event unchanged" check and the insert atomic.
* `api.py`: four thin routes below. No change to existing routes, `rules.json`, `RESULT_FILES` or the extraction code.

**Edit rules.** An edited record must (a) validate against `rule.schema.json` (`rule_validator()`); (b) keep `schemaVersion`, `id` and `source` unchanged (provenance is system-owned and was rewritten from the Legal JSON); (c) keep `review.status` as it is (status is system-owned); (d) be at most 200 KB. The `ODOS check:` notes are recomputed for the edited record, on a copy: a check error is a `422` with its message, and the submitted text is never silently rewritten. Flags are stored with the result and shown. `reviewer` is required on every action, `reason` on `reject`, `editedRule` exactly on `edit`.

### 5.3 API contracts

All four require a completed job (`409` otherwise); review writes are refused while an extraction of the job is queued or running.

**`GET /api/jobs/{id}/rule-reviews`**

```json
{
  "extractionId": "2026-11-18T19:19:20+00:00",
  "criteriaVersion": 1,
  "counts": { "pending": 61, "accepted": 7, "rejected": 2, "edited": 3 },
  "rules": {
    "<ruleId>": {
      "ruleSha256": "…", "state": "pending | accepted | rejected", "edited": false,
      "verification": "unverified | flagged",
      "lastEventId": 0, "reviewer": null, "reason": null, "at": null,
      "effectiveRule": null
    }
  }
}
```

`effectiveRule` is the edited record, present only when `edited` is true. Errors: `404` unknown job or no `rules.json`; `409` job not completed; `503` database off or table missing (the message says how to create it).

**`POST /api/jobs/{id}/rule-reviews`** appends one event and returns `201` with the rule's new entry (same shape as above).

```json
{ "ruleId": "…", "extractionId": "…", "expectedRuleSha256": "…", "expectedLastEventId": 0,
  "action": "accept | reject | edit | reset", "reviewer": "Name", "reason": "…", "editedRule": { } }
```

`409` if `extractionId` or the rule's hash no longer matches the current `rules.json`, if `expectedLastEventId` is not the latest event (someone else decided), or while an extraction runs; `404` unknown job or rule; `422` invalid request, invalid edit or missing reviewer/reason; `503` as above.

**`GET /api/jobs/{id}/rule-reviews/history?ruleId=…`** the audit trail of one rule, oldest first, across all extractions of the job: `[ { id, extractionId, action, decision, reviewer, reason, at, edited, ruleSha256 } ]`. Earlier extractions' events are history only; they are never applied to a newer `rules.json` (decision 4).

**`GET /api/jobs/{id}/rule-reviews/approved-export`** `{ _review: { extractionId, exportedAt, source: "human-accepted" }, rules: [...] }`: the effective record of every accepted rule, each with `review.status: "approved"` and a note `Approved by <name> on <date> (ODOS review)`, each validated against the schema. Rejected and pending rules are not included. Download name `<stem>.approved.rules.json` (`?download=true` adds the header). It is built on request and never written over `rules.json`.

**Structural validity** is a fact of its own, apart from the decision, the advisory `verification` and `review.machineCheckable`. Every entry of `GET .../rule-reviews` carries `validity: { valid, issues[] }` for the record in force (the edited record, else the original), and the state carries `export: { accepted, invalid, blockedBy[], ready }`. A rule that is not valid Rule JSON 2.0 (for example a model that wrote `informational`, a `normativeCategory` value, as `classification.type`) cannot be newly accepted (`POST` answers 422 with the reason); it can be rejected, or edited into shape through the normal edit, which is validated by the same schema. A valid rule that is not machine-checkable can be accepted. An acceptance that predates this rule stays as it is (no decision or history is changed), and the export then answers **422** `{ detail, invalidRules: [{ id, issues[] }] }` instead of exporting a partial file: nothing is silently left out or repaired.

### 5.4 Rule JSON 2.0 compatibility and immutability

`rules.json` is never opened for writing by review code; a test hashes the file before and after a sequence of decisions. Edited records and exports validate against the unchanged 2.0 schema. `review.status` stays `draft` in the stored file; `approved` appears only in the export.

### 5.5 Frontend integration

* `live.ts`: `getRuleReviews`, `postRuleReview`, `getRuleHistory`, `downloadApprovedRules`; HTTP status and the backend's message are kept (`HttpError`).
* **The review state is bound to the extraction on screen.** `useRuleReviews(jobId, shownId)` takes the identity of the displayed rules (`_generation.generatedAt` of the `rules.json` the page holds) and derives, on every render, one of: `loading` (the state was requested for other rules), `stale` (the backend's `extractionId` differs, or the displayed rules carry no identity), `unavailable` (storage missing, backend down) or `ready`. Only `ready` applies decisions to the displayed rules and enables Accept / Reject / Edit; in every other state the page applies no decision by rule ID, keeps the buttons disabled and says why. Rule IDs alone never connect a decision to a displayed rule, because a new extraction keeps the IDs.
  * `stale` shows *The extraction has changed* with **Reload results**, which fetches the current `rules.json` and then the review state of exactly those rules (the check runs again, so a third extraction in between is caught too). A `409` from a decision reloads the review state, which is how a second browser tab learns that another extraction replaced the rules.
  * The backend checks `extractionId`, the record hash and the last event on every write (section 5.3), so this is a second layer, not a replacement.
* A **Reviewer name** field (required before any action; remembered per browser with `localStorage` in a try/catch; labelled as self-declared).
* **Accept**: one click. **Reject**: asks for a reason. **Edit JSON**: an editor with the effective JSON; local `JSON.parse` check, then the server's `422` text is shown as is; **Reset edit** returns to the original. The reject and edit reasons are separate. Buttons are disabled while a request is in flight; there is no optimistic update; a `409` reloads the state and says why. Open forms are cleared when the rule, its extraction or its record changes.
* The JSON viewer shows the effective record with an "Edited" badge and a toggle to the original. The **Audit trail** lists the selected rule's events in two groups: those of the current extraction, and, apart and labelled *earlier extraction: history only, not applied to these rules*, those of earlier runs. Only current events decide the state.
* The overview's human-review group shows real pending / accepted / rejected / edited counts. The automated group is unchanged and the two are never summed. Filters: All, Pending, Accepted, Rejected, Flagged (a saved filter that is not offered in the current state falls back to All). **Download approved rules** fetches the export and saves it only if the backend answered with a file; an error answer (for example `409` while an extraction runs) is shown and nothing is saved.
* After a re-extraction all rules are pending; the page notes how many earlier decision events are kept in the history.
* **Navigation.** "Show in PDF" leaves the page for Document Review. The app keeps the reviewer's place (selected rule, filter, search, detail tab, scroll positions of the list and the page) for the same job and restores it when the page is opened again, without a request that starts an extraction and without fetching `rules.json` again (the page refreshed it before leaving); the review state and the extraction status are read again.
* Only `flagged` and `unverified` are shown as verification.

### 5.6 Tests

* Backend (needs a `_test` database): hash stability; each action and its state; reject without reason, missing reviewer, invalid edit, changed `id`/`source`/`review.status`, oversize edit, stale extraction, stale hash, concurrent decision, running extraction, unknown rule; history order; approved export contents and schema validity; `rules.json` byte-identical; cascade on document delete; `503` without the table; migration file idempotent (applied twice).
* Also backend: every review route answers `409` for a job without results; a `rules.json` without `generatedAt` gets a content-bound identity (`sha256:…`) and decisions do not carry over when the content changes.
* Frontend: a faked backend for unavailable (503, unreachable), loading, ready, accept, reject with reason, edit success and `422`, reset, `409` reload, name required and remembered, no double submit, counts, filters, audit trail (current and earlier extractions), slow history answers, the two-tab scenario (another extraction replaces the rules: all actions disabled, no foreign decision applied, reload shows consistent rules and state, new decisions carry the new identity), rules without an identity, approved export success and error, and the restored navigation state.

### 5.7 Calibration of `checks_passed` (after the above)

Reviewers decide a sample using the new controls; a script compares criteria v1 with those decisions (how many `checks_passed` rules were rejected or edited, and how many accepted rules had flags). `checks_passed` is shown only after the team sets an acceptance threshold; this document does not choose one.

### 5.8 Known limits

The reviewer name is not authenticated and the API has no access control; this is acceptable only while the API is reachable from the local machine alone (compose binds it to `127.0.0.1`). Authentication is required before any shared deployment. Deleting a document deletes its history. Decisions apply to one extraction. One reviewer's concurrent decision wins by order of arrival (the other gets a `409`).
