# LLM rule extraction with Amazon Bedrock

## Current API and CLI workflow

The API and `odos extract-rules` use `odos.llm.document_extraction`. The selected
document, Teil, or other subtree is partitioned into § targets in source order.
Each target runs `odos.llm.extraction_workflow` independently, with at most three
Converse calls: initial extraction and up to two schema/JSON corrections. The
budget is per target, not per whole document. Up to four worker threads process
targets concurrently. A freed worker takes the next queued target. All workers
finish before merging; results and report entries are merged in original source
order, regardless of completion order. A failed target does not cancel its peers.
The shared boto3 client is initialized before the workers start.

Workflow version 4 reports `strategy: parallel_provisions` and `maxWorkers`. Each
chunk records UTC start/end times, queue wait, preparation, workflow and elapsed
seconds. The total report records extraction wall time, summed/max chunk time,
local merge time and total processing time. Workflow time includes model calls,
schema checks and corrections; it is not exclusively provider generation time.
Concurrency reduces waiting time, not the number of tokens sent to the model.

`elementIds` is unchanged. Omit it to process the document; select a Teil to process
its § nodes. Selecting an Absatz retains that narrow selection rather than adding
the other Absätze of its §. Overlapping selections are collapsed. Text outside §
nodes and annexes receive explicit fallback targets instead of being silently
skipped. Front matter and navigation tables are not extraction targets.

Each request separates `target` from `context`. The target contains the selected
§ subtree, document metadata, headings, sentence IDs, pages and relevant footnotes.
Direct local citations such as `§ 2 Abs. 3` are resolved from the original Legal
JSON and supplied as contextual provisions, with a 12,000 estimated-token context
budget. Context citations are not followed recursively. Missing, ambiguous,
external/compound citations and over-budget context are reported. This resolver
does not infer implicit terminology dependencies or promise complete citation
resolution. Source text must never override extraction instructions.

The model is instructed to extract only target rules and use context as supporting
material. Rules without a target primary source are retained and flagged. Citation
coverage counts only targets, not contextual material.

Schema compliance is the retry gate: save immediately once the response parses and
all retained records conform to the schema. Content ambiguities, source checks and
citation coverage remain in the report but do not trigger another model call.
Only schema-invalid records are targeted for correction.

Clear field repairs and all existing
schema/source checks remain in use, but their findings are advisory: invalid and
duplicate candidates stay in the final `rules` list for review. The low-level
`odos.llm.rule_extraction.extract_rules` remains a strict single-round helper.

Feedback targets specific schema-invalid record indexes. There is no
delete operation, and omitted indexes stay unchanged. Each report retains raw
responses and before/after changes. After the third check the workflow saves its
result, even with validation issues. Unparseable/truncated output is explicitly
marked partial and preserved in the report. A failed correction keeps prior
output. A truncated response with schema-valid recovered records is saved as
partial immediately: requesting a schema-only patch cannot recover omitted text.
The report explicitly requests further splitting into Absatz targets; automatic
subdivision of unusually long § nodes is not implemented yet.

Each chunk is saved under the job's
`extraction-runs/<runId>/chunks/<sequence>/{rules,report}.json`. `progress.json`
records finished/failed chunks. A failed chunk does not prevent later chunks from
running; if every chunk fails, the API reports failure and preserves the previous
job result. Completed chunks and their reports remain on disk.

Merging is deterministic and makes no model call. All candidates are retained in
source order; ID conflicts are renamed with an origin map rather than discarded.
The combined report includes each chunk report, a fresh merged schema/source/
quantity/coverage check, possible exact duplicates, unknown/unresolved reference
links, empty/failed/partial chunks and context-only source findings. These local
checks do not constitute a semantic review. The final result is marked partial if
any chunk failed or was truncated.

The API's transport status may be `completed` while `workflow.outcome` is
`completed_with_issues`. `counts.retained` is the number saved, `counts.invalid`
counts records that failed validation, and `counts.rejected` is zero. Passing
checks and citation coverage do not prove semantic completeness.

Each job stores `rule_extraction_report.json`, served by
`GET /api/jobs/{id}/files/rule_extraction_report.json`. Docker also saves paired,
timestamped results and reports in `dev-fixtures/bedrock-extraction-results/` and
`dev-fixtures/Reports_for_results/`. Their basenames and `runId` match.

The sections below describe configuration and the underlying single-round
components. Their older statements about rejecting candidates and malformed-output
retries apply to the strict helper, not to the bounded API/CLI workflow above.

ODOS can send a Custom Legal JSON 2.0 document (`document.json`) to Claude Sonnet 4.6 on Amazon Bedrock and store the answer as Rule JSON (`rules.json`):

```
document.json (Legal JSON 2.0) ──► Bedrock Converse API ──► checks + provenance rewrite ──► rules.json (Rule JSON 2.0)
```

It can be started through the CLI or API. The frontend's **LLM Rule Extraction & Review** page (Document Review → *Continue to Rule Extraction*) starts the API step with an explicit click, follows its status and shows the stored `rules.json`; a `rules.json` that already exists is shown without a new request, and *Restart Extraction* asks for confirmation because every extraction is a paid call. The Document Review page also shows the original Legal JSON, the reduced LLM input V1 and applicability input V2 with separate downloads. The model receives the derived V2 view; redundant native type labels and printed node markers are omitted while stable IDs, numbers, page references and sentence ranges remain. The original Legal JSON and Rule JSON schema are not changed.

| Module | Responsibility |
|---|---|
| `backend/src/odos/llm/document_extraction.py` | Ordered § planning, direct-reference context, four-worker extraction, timing, per-chunk persistence and merged audit |
| `backend/src/odos/llm/extraction_workflow.py` | Per-chunk schema feedback, three-call budget and candidate retention |
| `backend/src/odos/llm/bedrock.py` | Reusable Bedrock client: configuration, authentication, timeouts, retries, typed errors |
| `backend/src/odos/llm/rule_extraction.py` | Prompt, scope selection, size check, answer validation, provenance, `rules.json` |
| `backend/src/odos/llm/profiles.py` | Extraction instructions: general rules, language glossaries, document-type profiles |
| `backend/src/odos/llm/rule_checks.py` | Deterministic quality checks of proposed records (fact identifiers, units, bounds, duplicates) |
| `backend/src/odos/cli.py` | `odos bedrock-check`, `odos extract-rules` |

## What was verified in the AWS documentation

| Topic | Result | Source |
|---|---|---|
| Authentication | Bedrock API key in `AWS_BEARER_TOKEN_BEDROCK`; sent as `Authorization: Bearer <key>`. boto3 reads the variable itself. Not usable with a few APIs (bidirectional streaming, Agents, Data Automation); `Converse` is supported. | [api-keys-use](https://docs.aws.amazon.com/bedrock/latest/userguide/api-keys-use.html) |
| API | `bedrock-runtime` client, `converse(modelId, messages, system, inferenceConfig)`; answer in `output.message.content[].text`, plus `stopReason` and `usage`. | [conversation-inference](https://docs.aws.amazon.com/bedrock/latest/userguide/conversation-inference.html) |
| Model ID | Base ID `anthropic.claude-sonnet-4-6` has **no in-region support in `eu-central-1`**; geo (`eu.`) and global (`global.`) inference profiles are supported. Context window 1M tokens, 64K output tokens. | [model card](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-4-6.html) |
| Not stated by AWS | A minimum boto3 version for the key variable; the exact exceptions Converse raises. | – |

Consequences: the default model ID is the EU geo profile **`eu.anthropic.claude-sonnet-4-6`** (requests stay in the EU; it needs the key to be allowed to use that profile). The tests confirm with a real botocore client that the key reaches Bedrock as a bearer token and that the endpoint is `bedrock-runtime.eu-central-1.amazonaws.com`. boto3 1.44.5 was used; `boto3>=1.40,<2` is the declared range.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `AWS_BEARER_TOKEN_BEDROCK` | – (required) | Bedrock API key. Read by boto3, never logged, never part of an error message. |
| `ODOS_BEDROCK_REGION` | `eu-central-1` | AWS region (deliberately not `AWS_REGION`, so an unrelated shell setting cannot redirect the data) |
| `ODOS_BEDROCK_MODEL_ID` | `eu.anthropic.claude-sonnet-4-6` | Model or inference profile ID |
| `ODOS_BEDROCK_MAX_TOKENS` | `32000` | Answer limit per request (model maximum 64,000; MBO § 6 alone needed about 17,000). Billed per token actually generated. |
| `ODOS_BEDROCK_TEMPERATURE` | `0` | |
| `ODOS_BEDROCK_CONNECT_TIMEOUT_SECONDS` | `10` | |
| `ODOS_BEDROCK_READ_TIMEOUT_SECONDS` | `600` | A long answer arrives only when it is complete |
| `ODOS_BEDROCK_MAX_ATTEMPTS` | `3` | Total attempts per request. botocore's `standard` retry mode retries throttling, 5xx and timeouts with back-off; authentication and validation errors are not retried. |
| `ODOS_BEDROCK_CONTEXT_TOKENS` | `1000000` | Context window used for the size check |
| `ODOS_BEDROCK_OUTPUT_RETRIES` | `1` | Correction requests when an answer is not valid JSON: `0` or `1`. Each is a paid call; a higher value is refused as a configuration error. Independent of `ODOS_BEDROCK_MAX_ATTEMPTS` (transport retries for throttling, 5xx and timeouts). |
| `ODOS_LLM_DIAGNOSTICS_DIR` | `~/.cache/odos/llm-diagnostics` | CLI: where unusable answers are kept (the API keeps them in the job directory) |
| `ODOS_RULE_EXTRACTION_MAX_QUEUED` | `3` | API: extractions that may wait or run at the same time (all jobs); more are refused with 429 |
| `ODOS_RULE_EXTRACTION_ACCEPT_PARTIAL` | off | API: `1` uses the complete records before a JSON defect of the last answer (marked partial); the CLI has `--accept-partial` |

Copy the Bedrock block of `.env.example` into `.env` (git-ignored), paste the key there and **save the file**. Never commit a key.

`odos bedrock-check` and `odos extract-rules` read only the Bedrock settings (`AWS_BEARER_TOKEN_BEDROCK`, `ODOS_BEDROCK_*`) from the first `.env` they find: in the working directory, in one of its parents, or in the repository root (`ODOS_ENV_FILE=/path/to/file` names one explicitly). A non-empty variable exported in the shell wins over the file; other variables in `.env` (such as `POSTGRES_*`) are not loaded. The commands show the file they used, never a value. In Docker, Compose passes the variables instead.

## Running it locally

From `backend/` with the virtual environment active (the key is read from `.env`, see above):

```bash
odos bedrock-check
```

One request of a few tokens: prints the `.env` file used, region, model, the answer, and token counts. It fails with a message naming the problem (missing key, rejected key, wrong model ID, ...); if the `.env` it found has no key line, it says so.

```bash
odos extract-rules storage/<job-id>/document.json --dry-run
odos extract-rules storage/<job-id>/document.json --element-id doc/teil-2/par-6/abs-5
odos extract-rules storage/<job-id>/document.json
```

* `--dry-run` shows the scope and the estimated size and sends nothing.
* `--element-id ID` (repeatable) sends only that element with its whole subtree and its ancestors, so the hierarchy stays intact. The ID is an `id` from `document.json`.
* Without `--element-id` the entire V2 view is sent. MBO is about 200,000 and the EU Machinery Regulation about 230,000 estimated input tokens, within the 1M window. A whole-document answer is long: if it reaches `ODOS_BEDROCK_MAX_TOKENS` the command stops with an error and **uses none of it**.
* `rules.json` is written next to the input (`-o` changes that) and replaced atomically.

Every call is a paid request. Use `--dry-run` and `--element-id` while trying things out.

## Running it with Docker

`compose.yaml` passes the key and the `ODOS_BEDROCK_*` variables from `.env` to the backend container. Without a key the backend behaves exactly as before.

```bash
docker compose up --build -d
docker compose exec backend odos bedrock-check
docker compose exec backend odos extract-rules /data/odos-storage/<job-id>/document.json --element-id <element-id>
```

The job ID is the one the web UI shows (also the directory name in the `backend_storage` volume). The resulting `rules.json` is then shown by the Rule JSON view of that job.

## What goes to the model

The system prompt holds the instructions, the complete Rule JSON schema (`backend/schemas/rule-json/rule.schema.json`) and one example. The user message holds applicability input **V2** derived non-destructively from the original Legal JSON, or, with `--element-id`, selected V2 subtrees with ancestors and their surviving sentences/footnotes. The system prompt still includes the full Rule JSON schema and example. There is no chunking. See [llm-input-reduction.md](llm-input-reduction.md) for the exact reduction and Excel policy.

If the estimated input plus the answer limit exceeds the context window, the command stops before sending anything (`DocumentTooLargeError`). The estimate uses 3 characters per token, which errs towards refusing; the real count is reported after a request.

## Reliable handling of the model's answer

**Why one malformed answer used to fail the whole extraction.** The answer is a single JSON document of 10,000 to 20,000 tokens. It was used only if all of it parsed; one defect anywhere (an unescaped quote in German text, a missing comma, prose after the JSON) discarded every record, and the answer itself was not kept, so the cause of the failed MBO § 6 V3 run cannot be determined afterwards.

**Structured output was evaluated and is not used.** Bedrock Converse supports structured output (`outputConfig.textFormat`, `type: json_schema`, the schema passed as a string) for Claude Sonnet 4.6 on `bedrock-runtime` through the EU inference profile (AWS user guide "Structured outputs", Claude Sonnet 4.6 model card; botocore 1.44.5 has the field). It accepts only a subset of JSON Schema: no recursive schemas, no `oneOf`/`not`, no `minimum`/`maximum`/`minLength`, `additionalProperties: false` required on every object, at most 12 optional properties and 16 union-typed properties in the whole schema. The Rule JSON schema needs recursive predicates and requirement expressions, `oneOf` branches, `if`/`then` conditions, numeric bounds and far more than 12 optional properties. Using structured output would therefore need a second, flattened output schema, which is a change of the Rule JSON contract and was out of scope. It is the main candidate for a later step (a non-recursive transport schema converted into Rule JSON before validation).

**What is implemented instead** (`model_output.py`, `rule_extraction.py`):

| Step | Behaviour |
|---|---|
| Parsing | The answer is used if it is exactly a JSON value, or a JSON value inside a code fence or with text around it (the text is ignored and counted, not kept). The JSON itself is never edited or "repaired". |
| Unusable answer | Kept as a diagnostic file (see below); `OutputParseError` gives the line and column of the defect, never the text. |
| Retry | At most one correction request (`ODOS_BEDROCK_OUTPUT_RETRIES`, `0` or `1`): the original request, the model's own answer and the parse error, asking for the complete answer as valid JSON. Bedrock's `stopReason: malformed_model_output` counts as malformed. A truncated answer (`max_tokens`) is not retried, since the retry would stop at the same limit. So an extraction makes at most two model calls. |
| Still unusable | `MalformedOutputError`: nothing is used. Only on explicit request (`--accept-partial`, `ODOS_RULE_EXTRACTION_ACCEPT_PARTIAL=1`) are the complete record objects before the defect used; the result is then marked `modelOutput.partial: true`. |
| Validation | Whatever is parsed or recovered goes through the same provenance rewrite, repair, checks and schema validation as every answer; recovered records are never accepted unchecked. |

**Diagnostics.** An unusable answer is written to a private folder (directory mode 0700, file mode 0600, newest 20 kept) with the parse error, attempt, model, stop reason, token counts, document ID, scope, length and SHA-256 of the answer, and the answer itself. Bedrock API keys, AWS access key IDs and bearer tokens are masked. The CLI uses `ODOS_LLM_DIAGNOSTICS_DIR` (default `~/.cache/odos/llm-diagnostics`, never inside the repository); the API uses `llm-diagnostics/` in the job directory, which is never served and is deleted with the job. Logs contain only the diagnostic ID, the length, a hash prefix and the parse position; rejected records are logged by index and ID only.

`_generation.modelOutput` records the number of model requests, the parse mode (`exact`, `embedded`, `partial`), ignored characters and diagnostic IDs; `_generation.counts` has `proposed`, `accepted`, `rejected`, `repaired` and `flagged`; `_generation.review` states that every rule is a draft that needs human review.

## Rule IDs

Rule IDs are scoped to the document: `<Legal JSON id>-<local id>` (`mbo-par-6-abs-5-satz-1`, `verordnung-2023-1230-art-10-para-3-s1`), lower-case ASCII. A proposed ID that already starts with the document ID is kept; IDs that would repeat get a numeric suffix. Rule sets of different documents therefore never share an ID, and the same document keeps the same IDs across runs. `source.documentId` remains the authoritative link to the document; provenance (`source.elements`, sentence IDs, pages) is not changed by the ID scheme, and `review.status` is always `draft`.

## Web API

Rule extraction is a step of an existing API job (the processed document), not a second job system. It needs the Bedrock configuration in the backend's environment (Compose passes it from `.env`).

| Request | Result |
|---|---|
| `POST /api/jobs/{id}/rule-extraction` with no body or `{"elementIds": ["doc/teil-2/par-6"]}` | `202` with the extraction status (`queued`) at once. Refused before anything is queued or paid for: unknown job `404`; job not completed or an extraction of this job already queued/running `409`; Legal JSON artifact missing `404` or unreadable `422`; unknown or empty element IDs, unknown body fields `422`; text too large for the context window `413`; more than `ODOS_RULE_EXTRACTION_MAX_QUEUED` extractions waiting `429`; Bedrock not configured (no key, invalid setting such as retries above 1) `503`. |
| `GET /api/jobs/{id}/rule-extraction` (also `ruleExtraction` in `GET /api/jobs/{id}`) | `status` (`queued`, `running`, `completed`, `failed`), `scope`, timestamps, `counts` (proposed, accepted, rejected, repaired, flagged), `coverage` (sentence and element counts, IDs of uncited sentences and elements, IDs cited only by rejected records), `modelOutput` (requests, parse mode, partial, number of diagnostics), `review` (`status: draft`, `humanReviewRequired: true`, flagged/rejected counts), `modelId`, `promptVersion`, `rulesFile`; on failure `errorCode` and a fixed message (`not_configured`, `bedrock_auth`, `bedrock_throttled`, `bedrock_timeout`, `bedrock_unavailable`, `bedrock_request`, `model_response`, `too_large`, `output_truncated`, `malformed_output`, `invalid_scope`, `interrupted`, `internal`). |
| `GET /api/jobs/{id}/files/rules.json` | The Rule JSON artifact (with `_generation`: rejected candidates, repairs, flags, full coverage), as before. A failed extraction never replaces an existing `rules.json`. |
| `GET /api/jobs/{id}/rule-reviews` | The review state of every rule of the current `rules.json`: decision (`pending`, `accepted`, `rejected`), whether it was edited (and the edited record), automated `verification` (`flagged` / `unverified`), the latest event ID, hash, reviewer, reason. `503` without the database or the `rule_reviews` table (`backend/db/002_rule_reviews.sql`). |
| `POST /api/jobs/{id}/rule-reviews` | Appends one review event (`accept`, `reject` with a reason, `edit` with a validated record, `reset`) with a self-declared reviewer name. `409` if the rules or the rule's review changed since they were read, or an extraction is running; `422` for an invalid request or edit (the message says why). |
| `GET /api/jobs/{id}/rule-reviews/history?ruleId=` | The audit trail of one rule, oldest first, across all extractions of the document. |
| `GET /api/jobs/{id}/rule-reviews/approved-export` | The accepted rules (edited content where edited) as Rule JSON 2.0 with `review.status: approved`; rejected and pending rules are not included. Built on request; `rules.json` is never modified. |

The model call runs in a single-worker executor of its own, outside the HTTP request: one paid extraction at a time, never blocking PDF processing. The status is kept in `rule_extraction.json` in the job directory (written before each published change); with the database enabled it is restored with the job at startup, and an extraction that was queued or running at shutdown is reported as `failed` / `interrupted`. The `documents` table is unchanged. A job cannot be deleted while its extraction is queued or running. Status and errors never contain document text, model output or credentials.

## Extraction instructions

The system prompt combines three layers (`profiles.py`, version `PROMPT_VERSION`, recorded in `_generation.promptVersion`):

| Layer | Chosen by | Content |
|---|---|---|
| General | always | One record per requirement; exceptions belong to the rule they change (no second record); operators from the wording (a determined value with a floor is one `== max(...)` formula, never several `>=`; an alternative keeps the operator of the rule it changes); every threshold in the machine-readable logic, never only in a description (cases split by a threshold are a rule plus an exception, each with its predicate); formulas and UCUM-style units (angles `deg`, `1` only for counts); English ASCII snake_case fact identifiers, translated rather than transliterated; one value type and unit per fact, numbers as numbers; periods and deadlines as `temporal` requirements with their start event; provenance including the sentences of exceptions, no skipped sentence or item; one name per actor; only the properties the schema allows at each place; references; non-binding text |
| Language glossary | `language` (`de`, `en`) | How modality, bounds, relaxations, exceptions and time are worded ("beträgt", "mindestens", "genügt", "innerhalb von", "spätestens", "shall", "at least", "within", "no later than", ...); for German, preferred English fact terms from `terminology.py` (`Gebäudeklasse -> building_class`, `Hersteller -> manufacturer`, ...) |
| Document-type profile | `documentType`, else `legalSystem` | Structure, citation style, addressees: `german_legislation` (`de_legislation`), `eu_legislation` (`eu_regulation`, `eu_decision`, `eu_legislation`), `eu_directive` (EU profile plus Member-State duties and transposition deadlines), `generic` (everything else) |

Prompt version 4 adds to the general layer: (1) `requirements` and `requirementExpression` are mutually exclusive, with guidance on when to use each, and cases that depend on a condition are a main case plus `exceptions` with their own conditions, never an `any` without conditions; (2) an exception or alternative has no source of its own, so every sentence it comes from is cited in the `source.elements` of its record (the prompt example cites three sentences for one rule with two exceptions). A record that still contains both forms is rejected by the schema with a readable reason, not repaired.

The general layer names no particular law. Technical standards (`documentType: technical_standard`, DIN/EN/ISO) currently get the general rules and the generic profile; supporting them means adding one `ExtractionProfile` to `PROFILES` (structure such as clauses and normative annexes, "shall/should/may" in the standards sense, citation style), with no change to the rest of the pipeline.

## Schema-aware repair

A record that is right in substance but breaks the schema in form is not thrown away (`rule_repair.py`). The repair walks the record along the Rule JSON schema itself (no hard-coded paths) and applies only repairs with one possible result:

| Form error | Repair |
|---|---|
| A property the schema does not allow at that place, if it is a pure annotation (`description`, `note`, `comment`, `explanation`, `rationale`, `remark` with text) | removed; its text is kept in the flag (e.g. a `description` on a comparison predicate, which rejected MBO § 6 Abs. 6 Nr. 2 in the V2 run) |
| `"3"` where a number is required, `"true"` where a boolean is required (also for a comparison's `value` under its `valueType`) | converted |
| An enum value that matches exactly one schema value after case/space/hyphen folding or without a plural `s` (`"Obligation"`, `"for at least"`, `"years"`) | mapped |
| `m²`, `m³`, `°`, `Grad`, `°C` as a unit | `m2`, `m3`, `deg`, `deg`, `Cel` |
| A comparison without `valueType` whose value has one JSON type | `valueType` added |

Every repair is flagged on the record (`ODOS check: schema repair: ...`) and listed in `_generation.schemaRepairs`. Anything else (a missing required field, a property that is not an annotation, a choice between schema branches) is not guessed: the record is rejected, with the most specific schema error as reason (for a `oneOf` failure, the error of the closest branch), and **kept as proposed** in `_generation.rulesRejected[].candidate` for review.

## Quality checks

After the provenance rewrite and the repair, every record goes through `rule_checks.py`; after all records are known, `source_checks.py` compares them with the cited text. None of the checks depends on the document type; language-dependent word lists (German, English) are data in `terminology.py` and `source_checks.py`.

| Check | Effect |
|---|---|
| Fact identifiers (`fact`, arithmetic `name`) must be English ASCII snake_case, optionally dotted (`building.height`) | camelCase, upper case, hyphens and spaces are converted (`controlSystem.withstandsX` → `control_system.withstands_x`, `H` → `h`) and listed in `_generation.factRenames`; an identifier in the document's language whose words are **all** in the terminology is translated word by word (`gebaeudeklasse`/`gebäudeklasse` → `building_class`, listed in `_generation.factTranslations`); an ASCII identifier that still contains recognisable words of the document's language (`abweichende_..._zulaessig`) is **flagged**, never half-translated; a non-ASCII identifier that cannot be translated **rejects** the record |
| A period in days, weeks, months or years written as a numeric fact (`retention_period >= 10 year`) | flagged: the start event is lost, it is a `temporal` requirement (`s`, `min`, `h` pass: often a measured property) |
| An exception or alternative that sets a fact of the rule with another operator (`==` relaxed to `>=`) | flagged |
| Numbers compared as strings (`["1", "2"]`) | flagged |
| The same fact with different value types or units in different records; identifiers that differ only in underscores | flagged |
| One actor written in several ways (case, article, singular/plural), or a name that extends another (`... Behörden der Mitgliedstaaten`) | flagged, with the most frequent spelling |
| A measure, threshold, fraction, period or date of a cited sentence (`weniger als 70 Grad`, `zu einem Drittel`, `zehn Jahre`, `bis zum 20. Januar 2027`) that is in no condition, requirement, formula, duration or deadline of the records citing that sentence as `primary` | flagged on those records: a threshold only in a description cannot be checked. Section numbers, citations (`Sätze 1 bis 4`, `Artikel 21`, `Anhang III Abschnitt 1.2.1`) and the date of another act (`vom 17. Mai 2006`) are not quantities; a number in an `unresolved` node counts as acknowledged |
| A number in the record's own summary or descriptions that its logic does not contain | flagged |
| Reference to the record's own primary source element | removed (counted in `_generation.selfReferencesRemoved`) |
| Angle facts (`angle`, `slope`, `pitch`, `inclination`, `tilt`) need `deg`, `rad` or `%`; operands of `add`/`subtract`/`min`/`max` and a formula's result share one unit | flagged |
| Several lower (or upper) bounds on one fact inside one `all` | flagged: usually a determined value ("X, at least Y") split into bounds |
| Records identical apart from `id`, `review` and descriptions | the first is kept, the others **rejected** as duplicates |
| A record whose conditions equal an exception's condition in another record from the same source element | flagged: the same alternative modeled twice |
| Two records from the same sentence with different operators on the same fact (without conditions) | flagged: contradictory reading |

A flag is a string in `review.ambiguities` starting with `ODOS check:`; the record stays a schema-valid draft and `_generation.rulesFlagged` counts them. The checks run on structure and on the wording of numbers only: whether an operator matches the wording, whether a unit is physically right for an unknown fact name, whether an English identifier is a good translation, and whether two differently worded records mean the same, still need human review.

**Coverage.** `_generation.coverage` counts the sentences (and elements without sentences) of the extracted text and the elements with own text, lists those that no accepted record cites as `primary` (`uncitedSentences`, `uncitedElements`, with the first 160 characters) and those cited only by a rejected candidate (`citedOnlyByRejected`). Headings, recitals and other non-normative node types are not counted. An uncited sentence may be non-normative or covered as an exception of a record that does not cite it; the report makes a dropped provision visible, it does not decide. `coveredByExceptionText` is a separate, **unverified** category (`verified: false`): uncited sentences whose normalized text (words only, case-insensitive, sentence number and punctuation ignored) is quoted by the `description` of an exception or alternative of an accepted record (the sentence must have at least 25 characters; a description that is only part of the sentence must reproduce at least 90 % of it). It is a text comparison, not provenance: such a sentence stays in `uncitedSentences`, is not counted in `sentencesCited`, and no rule or source is changed or completed. The API status lists their IDs as `coveredByExceptionTextIds`. The CLI prints the counts.

Regression baselines (never rewritten by the tests): the hand-modeled examples in `dev-fixtures/rule-json-examples/` must pass every check, also with the document language (the EU example's camelCase facts are only renamed); the real extractions in `dev-fixtures/bedrock-extraction-results/` (prompt versions 1 and 2) are pinned by hash and their known problems must be detected (`test_rule_quality.py`, `test_rule_engine_v3.py`).

## Provenance: what is checked and rewritten

A model's answer is only a proposal. Before a record enters `rules.json`:

| Check | Effect |
|---|---|
| Every `source.elements[].elementId` must be an `id` of the text the model was given | otherwise the record is **rejected** |
| `source.documentId`, `documentTitle`, `language` | overwritten from the Legal JSON |
| `source.elements[].pdfPages` | overwritten with the element's `pages` |
| `sentenceId` | kept only if the Legal JSON has that sentence on that element, else removed |
| `references[].elementId` not in the document | removed, reference becomes `unresolved` |
| `schemaVersion`, `review.status` | forced to `2.0` and `draft`; a note records the model |
| The record validates against the Rule JSON schema | otherwise **rejected** |
| Duplicate rule `id` | made unique with a numeric suffix |

`rules.json` is `{ "_generation": {...}, "rules": [...] }`. `_generation` records provider, model, region, time, scope, token counts, profile and prompt version, fact renames and translations, schema repairs, coverage, and every rejected record with its reasons and the record as proposed (`candidate`). The legal text itself is never rewritten.

A record that passes is well-formed and correctly sourced, not necessarily legally correct: see "What Needs Semantic Validation" in [rule-json.md](rule-json.md). All records are drafts for human review.

## Errors

`odos.llm.bedrock.BedrockError` and its subclasses: `BedrockConfigError` (no key, bad number), `BedrockAuthError` (401/403, expired key, no access to the model), `BedrockThrottledError`, `BedrockTimeoutError`, `BedrockUnavailableError`, `BedrockRequestError` (wrong model ID, invalid request; `BedrockContextLimitError` when AWS reports the input too long) and `BedrockResponseError` (malformed, empty, filtered). Rule extraction adds `DocumentTooLargeError`, `OutputTruncatedError`, `MalformedOutputError` and `InvalidScopeError`. The CLI prints the message and exits with status 2; nothing is written.

## Tests

```bash
cd backend
python -m pytest tests/test_bedrock_client.py tests/test_rule_extraction.py tests/test_rule_quality.py tests/test_rule_engine_v3.py tests/test_prompt_v4_coverage.py tests/test_model_output.py tests/test_rule_extraction_api.py -v
```

No test calls AWS. `test_bedrock_client.py` drives a real boto3 client with a fake key and intercepts the HTTP request (authentication header, endpoint, model, retries, timeouts, error mapping, malformed responses). `test_rule_extraction.py` uses canned model answers (scope, size limit, validation, provenance, `rules.json`, CLI); one test uses a processed MBO document from `backend/storage/` if present and skips otherwise.

## Limits

* No chunking: a document is processed in one request. Very large documents need `--element-id`.
* The frontend extracts the whole document only (no chunking exists, by design: a request that does not fit the context window, `too_large`, or an answer cut off at the output limit, `output_truncated`, is reported as an error and nothing is used). Choosing provisions (`elementIds`) is possible through the API and the CLI but not yet in the frontend. Human review decisions (accept, reject, edit) are stored in PostgreSQL when the `rule_reviews` table exists (see [database-poc.md](database-poc.md)); without it the page shows those controls disabled and every rule as `draft` (*Pending Review*). Decisions apply to one extraction: a re-extraction starts with all rules pending, and earlier decisions stay in the history. The reviewer name is self-declared, not authenticated. Records refused by the automated checks are listed separately and are not review decisions.
* Structured output is not used (the Rule JSON schema exceeds what Bedrock structured output accepts); a malformed answer is retried once and otherwise reported, so a run can still fail and cost two calls.
* The extraction status is a file in the job directory, not a database column: in-memory mode loses it with the job, and several API processes would not share it (the API is single-process anyway).
* The correction request resends the input and the malformed answer, so it costs roughly the input plus twice the output of the first call.
* Quality of the extracted rules depends on the model; nothing here evaluates it against a reference.
* The checks detect and flag; apart from the unambiguous schema repairs and the dictionary translation of fact identifiers they never change what a record means. There is no automatic second request to the model to fix a flagged record.
* The fact terminology and the number words cover German and English only, and only general vocabulary; an unknown German word is flagged, not translated. Word-by-word translation keeps German word order in compounds (`setback_area_depth`).
* Quantity detection is pattern-based: a number without a unit word (other than a decimal factor) is not checked, and a sentence that spans several items (a lead-in with points a to c) is checked as a whole.
