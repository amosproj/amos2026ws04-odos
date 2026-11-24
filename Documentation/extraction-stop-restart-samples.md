> Frontend update: the random-sample controls described below have been replaced by an article/§ checklist and Whole document. See article-checklist-extraction.md. Legacy sample API fields remain supported.

# Stop, additive restart and sample extraction

Apply this update to the current develop project with the newer rule-review frontend. The ZIP contains updated/new files only. Copy its folders into the project root beside compose.yaml, merge folders and replace matching files. Do not remove the existing project or Docker volumes. Keep .env unchanged. This cumulative update also retains the earlier preview/call-limit and artifact/navigation frontend changes.

```powershell
docker compose up --build -d
```

## Test a small part first

Open LLM Rule Extraction, then Preview Rule Extraction. Document scope offers:

- 1 sample: up to 4 randomly selected eligible articles / § provisions in one chunk (default for testing)
- 3 samples: up to 12 randomly selected eligible articles / § provisions in groups of four
- All remaining eligible chunks

The call limit independently offers 1 (default, no correction) or 3 (initial response plus up to two schema/JSON corrections) per chunk. The preview and extraction plan use the same V2 prompt preparation and selection logic. Changing scope invalidates the preview until the new estimate arrives. Full-document chunking is unchanged. Sample mode chooses actual article nodes (or § provisions for MBO), groups at most four per request, and shows the selected numbers/titles before starting. Random samples are not a complete or representative legal check. The preview list is reused for extraction; eligibility changes return 409 instead of silently resampling. Choose another random sample redraws locally without paid inference. Selected IDs are recorded in the report. Direct-reference context may include material outside the extraction target. A sample is explicitly marked partial.

## Stop

While queued/running, Stop extraction sets a cooperative stop request on the server. No further chunks or correction calls are started after the signal is observed. At most four chunks run concurrently, so requests already dispatched may still finish and cost tokens. SDK transport retries on an in-flight request are not interrupted. There is no promise of immediate cancellation at Bedrock.

Completed responses are merged and saved as a partial extraction. If stopped while still queued, the job is marked cancelled and previous artifacts stay unchanged. Closing the browser does not stop extraction. A stop marker survives a backend restart and is cleared for a newly accepted extraction request.

## Additive restart

Restart no longer replaces the entire rule collection. It keeps all previous rules, accepted/rejected decisions and manual edits, and appends novel model candidates as pending drafts. It skips provisions that already have at least one rule and whose existing rules are all accepted or manually edited. This skip policy saves tokens; it does not prove that the provision was exhaustively extracted. A provision containing both protected and pending rules can be processed again, while its protected records are kept unchanged.

Exact structural/logic duplicates are skipped, ignoring generated IDs, review metadata and wording of the summary. Semantically similar but structurally different candidates may still appear and need human review. Existing rules are not deleted. New IDs are made unique when they collide with old IDs. An edited rule stays pending unless a person has accepted that edited version; edits never imply approval.

Every revision receives a fresh extraction/run identity. Carried decisions are bound to unchanged original hashes; manual edits remain the effective review overlay, as in the existing review design. They are used in the UI and approved export. The raw original rule is retained for audit, and the carried overlay is included in generation metadata. Future review events supersede the carried baseline and use event ID zero for the new revision. Old rules and review state are snapshotted in extraction-runs/<runId>/previous-rules.json and previous-reviews.json before the new collection is written. The database's original event history is retained. No database schema change is introduced.

A working review database is required when restarting an existing extraction. If review state cannot be read, restart fails before any paid request. If an older database is missing rule_reviews, apply the existing backend/db/002_rule_reviews.sql migration; the Compose PostgreSQL container exposes it under /docker-entrypoint-initdb.d/. Do not delete volumes to apply migrations.

## API

POST /api/jobs/{id}/rule-extraction/preview and POST /api/jobs/{id}/rule-extraction accept maxModelCalls (1 or 3), sampleChunks (1 or 3 groups of four, or null for all), sampleSeed (optional reproducible preview seed), sampleArticleIds (the provision IDs returned by the preview), and the existing optional elementIds. API omission of sampleChunks keeps the prior full-scope default; the frontend defaults to sampleChunks=1. Preservation of existing reviewed content is always enabled.

POST /api/jobs/{id}/rule-extraction/stop requests a stop, returning 202 for an active extraction and 409 if none is active. Status includes stopRequested and can end as cancelled if no extraction was started. Both endpoint plan and worker use the same cached per-request review snapshot; review writes are serialized with taking that snapshot.

## Verification

32 offline backend tests passed, covering V2, budget limits, preview/sample consistency, grouped four-article prompts, stable preview IDs, seed variation, insufficient remaining provisions, eligibility-change rejection, stop before dispatch, retaining completed chunks, avoiding corrections after stop, bounded concurrent scheduling, additive deduplication, review hash checks, approved export of edited rules, subsequent review actions and HTTP preview/start/stop handlers. AWS transport and repository boundaries were replaced by fakes; actual schema, prompt, merge and review logic ran. Frontend TS/TSX parsed/transpiled, and lightweight component checks exercised the sample default, matching start parameters and stale-preview disabling. Full pytest/Vitest/build, real PostgreSQL integration and live Bedrock extraction were not available here. No paid inference was performed.
