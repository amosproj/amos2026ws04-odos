# ODOS Backend

The Python package `odos` converts legal PDFs into structured data: Docling extracts layout and text, the backend
parses German and EU legal structure, and the result is exported as **Custom Legal JSON 2.0**. An optional second
step sends the Legal JSON to **Amazon Bedrock** (Claude Sonnet 4.6) and stores machine-readable compliance rules
as **Rule JSON**, ready for human review.

This README is the main entry point for backend setup, the Bedrock rule extraction feature, and troubleshooting.
For the Docker + build workflow, see [../DOCKER.md](../DOCKER.md). For detailed technical internals, see
[Documentation/bedrock-rule-extraction.md](../Documentation/bedrock-rule-extraction.md).

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Prerequisites](#3-prerequisites)
4. [Quick Start with Docker Compose](#4-quick-start-with-docker-compose)
5. [API Reference](#5-api-reference)
6. [CLI Reference](#6-cli-reference)
7. [Output Files and Rule JSON](#7-output-files-and-rule-json)
8. [Configuration](#8-configuration)
9. [Troubleshooting](#9-troubleshooting)
10. [Security and Costs](#10-security-and-costs)
11. [Current Limitations](#11-current-limitations)
12. [For Reviewers](#12-for-reviewers)
13. [Source Layout](#13-source-layout)
14. [Further Reading](#14-further-reading)

---

## 1. Overview

ODOS converts legal PDFs into structured legal data for downstream compliance tooling.

**PDF processing pipeline** (always available):

| Stage | What it does |
|---|---|
| Extraction | Docling converts the PDF to raw JSON and Markdown |
| Normalization | Reading order is corrected; text evidence is built for source highlighting |
| Parsing | German and EU legislative structure is recognized; sentences and footnotes are identified |
| Export | Custom Legal JSON 2.0 is written with full provenance back to source pages |

**LLM rule extraction** (optional, requires an Amazon Bedrock API key):

| Stage | What it does |
|---|---|
| Input preparation | The Legal JSON is filtered to the requested scope; size is checked against the context window |
| Bedrock call | The document is sent to Claude Sonnet 4.6 together with instructions and the Rule JSON schema |
| Validation | Each proposed rule record is checked against the schema; provenance is rewritten from the Legal JSON |
| Quality checks | Fact identifiers, units, thresholds, actor names and coverage are checked deterministically |
| Output | Validated `draft` rules are written to `rules.json` next to the Legal JSON |

Both steps run independently. The PDF pipeline is not changed by the Bedrock integration.

---

## 2. Architecture

### Full workflow

```
                    ┌─────────────────────────────────────────────┐
                    │                 ODOS Backend                 │
  PDF ──► POST /api/jobs ──► Docling ──► Parser ──► document.json  │
                    │                                              │
  document.json ──► POST /api/jobs/{id}/rule-extraction            │
                    │       │                                      │
                    │       ▼                                      │
                    │  LLM Input Builder                           │
                    │  (scope, size check, system prompt + schema) │
                    │       │                                      │
                    │       ▼                                      │
                    │  Amazon Bedrock (Claude Sonnet 4.6)          │
                    │  eu-central-1 / eu.anthropic.claude-sonnet-4-6│
                    │       │                                      │
                    │       ▼                                      │
                    │  Validation, provenance rewrite,             │
                    │  quality checks, coverage reporting          │
                    │       │                                      │
                    │       ▼                                      │
                    │   rules.json (draft records)                 │
                    └─────────────────────────────────────────────┘
```

### Key design decisions

- **No chunking.** The Legal JSON is sent in one request, with an optional scope filter (`--element-id`).
- **Schema-first validation.** Each proposed record is checked against the Rule JSON schema before being accepted.
- **Provenance rewrite.** `source.documentId`, element pages and sentence IDs are overwritten from the Legal JSON; records citing unknown elements are rejected, not repaired.
- **Draft-only output.** Every accepted record has `review.status: "draft"`. Human review is required before any rule is used for compliance decisions.
- **Separation from live processing.** The PDF pipeline runs in its own worker. The Bedrock call runs in a separate single-worker executor, so a long extraction never blocks a PDF upload.

For module-level details, see [Documentation/bedrock-rule-extraction.md](../Documentation/bedrock-rule-extraction.md).

---

## 3. Prerequisites

### Docker Compose (recommended)

- Docker Desktop with Linux containers (WSL 2 backend on Windows)
- A root `.env` file (copy from `.env.example`, fill in Postgres password)
- For rule extraction: an Amazon Bedrock API key — see [Getting a Bedrock API key](#getting-a-bedrock-api-key)

### Local (Windows / macOS / Linux)

- Python 3.12
- Node.js 22 (frontend only)
- Network access for the first Docling model download

### Getting a Bedrock API key

1. Open the AWS Console → **Amazon Bedrock → API keys**.
2. Create a key and copy it immediately (shown only once).
3. Paste it into `.env` as `AWS_BEARER_TOKEN_BEDROCK=<your-key>`.
4. The key must have access to `eu.anthropic.claude-sonnet-4-6` in `eu-central-1`.
5. Never commit the key to Git. `.env` is git-ignored by default.

---

## 4. Quick Start with Docker Compose

This is the recommended path for running all components together.

### 4.1 Configure the environment

```bash
cp .env.example .env
# Edit .env: set POSTGRES_PASSWORD (any local password)
# Optional: paste your Bedrock API key into AWS_BEARER_TOKEN_BEDROCK
```

### 4.2 Build and start

```bash
docker compose build
docker compose up -d
```

Wait until all services are healthy:

```bash
docker compose ps
```

### 4.3 Open the application

| URL | Purpose |
|---|---|
| http://localhost:5173 | Frontend (upload PDFs, browse results) |
| http://localhost:8000/docs | Interactive API documentation |

### 4.4 Verify Bedrock connectivity (if key is configured)

```bash
docker compose exec backend odos bedrock-check
```

Expected output:

```
env file:   /path/to/.env (2 Bedrock setting(s) applied)
region:     eu-central-1
model:      eu.anthropic.claude-sonnet-4-6
answer:     'ok'
stop:       end_turn
tokens:     14 in, 5 out (1234 ms)
```

### 4.5 Stop and restart

```bash
docker compose down          # stop, keep volumes
docker compose up -d         # start again
```

After source changes, rebuild only the backend (preserves volumes):

```bash
docker compose build backend
docker compose up -d --no-deps backend
```

---

## 5. API Reference

The backend exposes a REST API at `http://localhost:8000`. Full interactive documentation is available at `/docs`.

### Core processing endpoints

| Method | Route | Description |
|---|---|---|
| `POST` | `/api/jobs` | Upload a PDF (multipart field `file`); returns a queued job |
| `GET` | `/api/jobs/{id}` | Job status, stage, message and result summary |
| `GET` | `/api/jobs/{id}/files/{name}` | Download a result file (see [Output Files](#7-output-files-and-rule-json)) |
| `GET` | `/api/documents` | Metadata of stored documents; `[]` without database persistence |
| `GET` | `/api/jobs/{id}/pdf` | Original PDF (database persistence only) |
| `DELETE` | `/api/jobs/{id}` | Delete a job and its files |

Job status values: `queued` · `processing` · `completed` · `unsupported` · `failed`

### Rule extraction endpoints

Both endpoints require the job to be in `completed` status. Each `POST` is a paid Bedrock call.

#### Start an extraction

```bash
# Whole document (use --element-id or the body below for large documents)
curl -X POST http://localhost:8000/api/jobs/{id}/rule-extraction

# Specific section only (recommended; reduces cost and response time)
curl -X POST http://localhost:8000/api/jobs/{id}/rule-extraction \
  -H "Content-Type: application/json" \
  -d '{"elementIds": ["doc/teil-2/par-6"]}'
```

Returns `202 Accepted` immediately with the initial status:

```json
{
  "status": "queued",
  "scope": ["doc/teil-2/par-6"],
  "startedAt": null,
  "completedAt": null
}
```

**Error responses** (no Bedrock call is made in these cases):

| HTTP | Meaning |
|---|---|
| `404` | Job not found, or `document.json` missing |
| `409` | Job not completed, or an extraction is already queued/running for this job |
| `413` | Document too large for the context window; use `elementIds` to narrow scope |
| `422` | Unknown element IDs, unreadable `document.json`, or invalid request body |
| `429` | Queue full (`ODOS_RULE_EXTRACTION_MAX_QUEUED` reached) |
| `503` | Bedrock not configured (missing key or invalid setting) |

#### Poll status

```bash
curl http://localhost:8000/api/jobs/{id}/rule-extraction
```

Returns the current extraction status. Example of a completed extraction:

```json
{
  "status": "completed",
  "scope": ["doc/teil-2/par-6"],
  "startedAt": "2026-11-18T20:00:00Z",
  "completedAt": "2026-11-18T20:01:35Z",
  "counts": {
    "proposed": 19,
    "accepted": 19,
    "rejected": 0,
    "repaired": 0,
    "flagged": 1
  },
  "coverage": {
    "sentences": 23,
    "sentencesCited": 21,
    "uncitedSentences": [...],
    "elements": 26,
    "elementsCited": 26
  },
  "modelOutput": {
    "requests": 1,
    "parseMode": "exact",
    "partial": false
  },
  "review": {
    "status": "draft",
    "humanReviewRequired": true
  },
  "modelId": "eu.anthropic.claude-sonnet-4-6",
  "promptVersion": "4",
  "rulesFile": "rules.json"
}
```

On failure, `status` is `"failed"` and the response includes `errorCode` (e.g. `bedrock_auth`, `bedrock_timeout`, `malformed_output`) with a fixed message. See [Troubleshooting](#9-troubleshooting) for a full list.

#### Retrieve the result

```bash
curl http://localhost:8000/api/jobs/{id}/files/rules.json
```

Returns the full Rule JSON file including `_generation` metadata (token counts, rejected candidates, coverage). A failed extraction never overwrites an existing `rules.json`.

---

## 6. CLI Reference

### Local installation (macOS / Linux)

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
pip install --no-deps -e .
```

### Local installation (Windows PowerShell)

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
```

Start the API (leave this terminal running):

```powershell
.\.venv\Scripts\python.exe -m uvicorn odos.api:app --port 8000
```

### Core processing commands

```bash
# Full pipeline: PDF → Legal JSON
odos process path/to/law.pdf -o output/law --mode german_law
odos process path/to/eu.pdf  -o output/eu  --mode eu_legislation

# Individual steps
odos extract   path/to/law.pdf -o output/raw
odos normalize output/raw/docling_raw.json --pdf path/to/law.pdf --mode german_law
odos legal-json output/raw/document_model.json
```

Available modes: `german_law`, `eu_legislation`. The web API detects the mode automatically; the CLI requires it explicitly.

### Bedrock commands

The CLI reads the Bedrock API key from `.env` (searched in the working directory, its parents, and the repository root). The key is never echoed; only the file name and setting count are shown.

#### Connectivity check (a few tokens, low cost)

```bash
odos bedrock-check
```

#### Dry run (no API call, no cost)

```bash
odos extract-rules storage/{job-id}/document.json --dry-run
# Shows scope, model, estimated token count; sends nothing
```

#### Extract rules for a specific section

```bash
odos extract-rules storage/{job-id}/document.json \
  --element-id doc/teil-2/par-6
# Writes rules.json next to document.json; use -o to change the output path
```

#### Extract rules for multiple sections

```bash
odos extract-rules storage/{job-id}/document.json \
  --element-id doc/teil-2/par-6 \
  --element-id doc/teil-2/par-7
```

#### Extract the whole document (use with care)

```bash
odos extract-rules storage/{job-id}/document.json
# MBO ≈ 200 000 estimated input tokens; EU Machinery Regulation ≈ 230 000.
# If the answer reaches ODOS_BEDROCK_MAX_TOKENS it stops with an error and uses nothing.
# Prefer --element-id while exploring.
```

### In Docker

```bash
docker compose exec backend odos bedrock-check
docker compose exec backend odos extract-rules \
  /data/odos-storage/{job-id}/document.json \
  --element-id doc/teil-2/par-6
```

The job ID appears in the web UI and is the directory name inside the `backend_storage` volume. After extraction, the Rule JSON view of that job in the frontend shows the result.

---

## 7. Output Files and Rule JSON

### Result files per job

| File | Served by API | Contents |
|---|---|---|
| `document.json` | Yes | Custom Legal JSON 2.0: legal structure, sentences, provenance |
| `document_model.json` | Yes | Internal model: source coordinates, diagnostics |
| `docling_raw.json` | Yes | Raw Docling output |
| `validation_report.json` / `.md` | No | Parser diagnostics (not served) |
| `rules.json` | Yes | Rule JSON: accepted rules + `_generation` metadata |
| `rule_extraction.json` | No | Live extraction status (not served) |
| `llm-diagnostics/` | No | Private: unusable model answers only (deleted with the job) |

### Understanding rules.json

```
rules.json
├── _generation          Metadata: model, tokens, counts, coverage, rejected candidates
│   ├── counts           proposed / accepted / rejected / repaired / flagged
│   ├── coverage         sentences and elements cited, uncited, citedOnlyByRejected
│   ├── modelOutput      requests, parseMode, partial
│   ├── rulesRejected    each rejected candidate with its reason and the original record
│   └── schemaRepairs    automatic, unambiguous form-only fixes applied to records
└── rules[]              Accepted rule records (all with review.status: "draft")
    ├── id               Document-scoped: "<documentId>-<local>" (e.g. "mbo-par-6-abs-5")
    ├── source           documentId, citation, elements with sentenceIds and pages
    ├── classification   type (obligation / permission / ...), summary
    ├── requirements     or requirementExpression — the machine-readable logic
    ├── exceptions[]     conditions under which the main rule does not apply
    └── review           status: "draft", humanReviewRequired: true, ambiguities[]
```

**What "draft" means.** A rule record has been accepted because it is structurally valid (passes the Rule JSON schema), correctly sourced (every element ID exists in the document, provenance has been rewritten), and passes deterministic quality checks (fact identifiers, units, thresholds, actor names). It has *not* been verified for legal correctness: an experienced reviewer must check whether the extracted logic faithfully represents the statutory text.

**Coverage reporting.** `_generation.coverage` lists every sentence that no accepted record cites as a primary source (`uncitedSentences`). An uncited sentence may be non-normative, or it may represent a genuinely missed provision. `coveredByExceptionText` is a separate unverified category: sentences whose text appears almost verbatim in an exception description, but whose sentence ID is not in `source.elements`. This flag helps reviewers find provisions that the model paraphrased rather than cited.

For the full provenance rules and quality-check catalogue, see [Documentation/bedrock-rule-extraction.md](../Documentation/bedrock-rule-extraction.md).

---

## 8. Configuration

### Core backend variables

| Variable | Default | Purpose |
|---|---|---|
| `ODOS_STORAGE_DIR` | temporary | Job-file directory; temporary storage is removed at shutdown |
| `ODOS_MAX_UPLOAD_MB` | `50` | PDF upload size limit |
| `ODOS_DATABASE_ENABLED` | off | `1` enables PostgreSQL persistence (jobs, Legal JSON, startup restore) |

### Database variables (required when `ODOS_DATABASE_ENABLED=1` or when using Docker Compose)

| Variable | Example |
|---|---|
| `POSTGRES_USER` | `odos` |
| `POSTGRES_PASSWORD` | *your local password* |
| `POSTGRES_DB` | `odos` |

### Bedrock variables (optional — rule extraction only)

Copy the Bedrock block from `.env.example` into `.env`, fill in the key, and save.

| Variable | Default | Purpose |
|---|---|---|
| `AWS_BEARER_TOKEN_BEDROCK` | *required* | Bedrock API key; read by boto3, never logged |
| `ODOS_BEDROCK_REGION` | `eu-central-1` | AWS region (not `AWS_REGION`, to avoid shell pollution) |
| `ODOS_BEDROCK_MODEL_ID` | `eu.anthropic.claude-sonnet-4-6` | Model or inference profile ID |
| `ODOS_BEDROCK_MAX_TOKENS` | `32000` | Output token limit per request |
| `ODOS_BEDROCK_MAX_ATTEMPTS` | `3` | Transport-level retries (throttling, 5xx, timeouts) |
| `ODOS_BEDROCK_OUTPUT_RETRIES` | `1` | Correction requests on a malformed JSON answer (`0` or `1`) |
| `ODOS_RULE_EXTRACTION_MAX_QUEUED` | `3` | Maximum concurrent or waiting extractions before a 429 |

For the full variable list (timeouts, context window, diagnostics directory), see the [configuration table](../Documentation/bedrock-rule-extraction.md#configuration) in the technical reference.

---

## 9. Troubleshooting

### Startup and Docker

| Problem | What to check |
|---|---|
| `POSTGRES_*` variable errors | Create `.env` from `.env.example` and fill in `POSTGRES_PASSWORD` |
| Backend unhealthy | `docker compose logs --tail 100 backend` |
| Port already in use | Stop a previous ODOS stack or conflicting local server |
| Database authentication fails | Credentials must match those used when the volume was initialized |
| Frontend does not open | `docker compose ps` and `docker compose logs --tail 100 frontend` |

### Bedrock API errors

| `errorCode` | Meaning and fix |
|---|---|
| `not_configured` | `AWS_BEARER_TOKEN_BEDROCK` is missing or empty; check `.env` and restart the backend |
| `bedrock_auth` | Key rejected (401/403): expired, wrong key, or no access to `eu.anthropic.claude-sonnet-4-6` in `eu-central-1` |
| `bedrock_throttled` | Bedrock rate limit; wait and retry (the client retries automatically up to `ODOS_BEDROCK_MAX_ATTEMPTS`) |
| `bedrock_timeout` | The request timed out; increase `ODOS_BEDROCK_READ_TIMEOUT_SECONDS` (default 600 s) or use a narrower `--element-id` scope |
| `bedrock_unavailable` | Network or Bedrock endpoint unreachable; check connectivity |
| `bedrock_request` | Wrong model ID, invalid request, or other Bedrock error; check `ODOS_BEDROCK_MODEL_ID` |
| `model_response` | Malformed or empty Bedrock response |
| `too_large` | Input exceeds the context window; use `elementIds` to reduce scope |
| `output_truncated` | The answer was cut off at `ODOS_BEDROCK_MAX_TOKENS`; increase the limit or narrow scope |
| `malformed_output` | The answer was not valid JSON after the allowed correction request; a diagnostic file is kept in `llm-diagnostics/` |
| `internal` | Unexpected backend error; check the backend log |

### Key file not found by CLI

`odos extract-rules` and `odos bedrock-check` search for `.env` in the working directory and its parents. If the
key is not picked up, run from the repository root, or set `ODOS_ENV_FILE=/absolute/path/to/.env`.

### Extraction quality issues

If rules are unexpectedly rejected or uncited sentences appear:

1. Read the `_generation.rulesRejected` array: each entry includes the reason and the record as proposed.
2. Check `_generation.coverage.uncitedSentences` for missed provisions.
3. Use a narrower `--element-id` scope to reduce model uncertainty on large sections.
4. Run the full Bedrock test suite to confirm the pipeline is behaving correctly:
   ```bash
   cd backend
   python -m pytest tests/test_bedrock_client.py tests/test_rule_extraction.py \
     tests/test_rule_engine_v3.py tests/test_model_output.py \
     tests/test_prompt_v4_coverage.py tests/test_rule_extraction_api.py -v
   ```

---

## 10. Security and Costs

### Credentials

- The Bedrock API key lives only in `.env` (git-ignored) and in the backend container's environment.
- boto3 reads the key automatically; it is never logged, never included in error messages, never sent to any service other than `bedrock-runtime.eu-central-1.amazonaws.com`.
- Diagnostic files (unusable model answers) are written with file mode 0600 and directory mode 0700. They are deleted when the job is deleted.

### Cost

Each `POST /api/jobs/{id}/rule-extraction` is a paid AWS Bedrock call. Charges are based on input and output tokens.

| Scenario | Approximate token count |
|---|---|
| `odos bedrock-check` | ~15 tokens (negligible) |
| MBO § 6 (one section, ~23 sentences) | ~16 000 input / ~17 000 output |
| MBO whole document | ~200 000 estimated input |
| EU Machinery Regulation whole document | ~230 000 estimated input |

If the model's answer is not valid JSON, the client sends one correction request (`ODOS_BEDROCK_OUTPUT_RETRIES=1`), which roughly doubles the cost of that run. Use `--dry-run` to estimate costs before running.

### Endpoint access

The rule extraction endpoint (`POST /api/jobs/{id}/rule-extraction`) has **no authentication**. It is intended for internal use in a trusted environment. Do not expose it to the public internet without adding authentication.

---

## 11. Current Limitations

### Implemented and validated

- Full rule extraction pipeline (Legal JSON 2.0 → Bedrock → Rule JSON)
- Prompt version 4: mutual exclusivity of requirement forms, exception-sentence provenance
- Schema validation, provenance rewrite, deterministic quality checks
- Coverage reporting including `coveredByExceptionText`
- One correction retry on a malformed JSON answer
- Document-scoped rule IDs, `draft` status on all records
- API endpoints with background execution and status polling
- CLI `bedrock-check` and `extract-rules` commands
- Validated live on MBO § 6: 19/19 accepted, 21/23 sentences cited, 0 schema errors

### Known limitations

| Area | Current state | Planned |
|---|---|---|
| DIN/EN/ISO technical standards | Extracted with generic profile; no standards-specific instructions | Add `ExtractionProfile` for technical standards |
| Frontend trigger | No UI button; extraction must be started via API or CLI | Add a "Start rule extraction" button |
| Endpoint authentication | None; internal use only | Add token-based auth before exposing externally |
| Multi-process deployment | Extraction state is stored in a file, not the database; single process only | Migrate state to the `documents` table |
| Large documents | Whole-document extraction can hit the output token limit; use `--element-id` | Chunking or incremental extraction |
| Semantic correctness | Quality checks are deterministic; legal correctness requires human review | No planned automation |
| Fact terminology | German and English general vocabulary only; unknown domain terms are flagged | Extend terminology lists |

---

## 12. For Reviewers

This section is for project members and industry partners evaluating the current state of the Bedrock integration.

### What can be evaluated now

| Item | How to evaluate |
|---|---|
| **End-to-end extraction** | Process an MBO or EU document via the frontend, then call `POST /api/jobs/{id}/rule-extraction` with an element ID; poll until `completed` and open `rules.json` in the Rule JSON view |
| **Result quality** | Review `rules.json`: check that rules match the statutory text, that provenance (`source.elements`) cites the right sentences, and that flagged records in `review.ambiguities` reflect genuine uncertainties |
| **Coverage** | `_generation.coverage.uncitedSentences` lists provisions with no corresponding rule; `coveredByExceptionText` lists sentences the model paraphrased without citing |
| **Rejected records** | `_generation.rulesRejected` shows every record the pipeline rejected, with the schema error or provenance problem as reason and the record as proposed |
| **Test suite** | 7 test files, 0 Bedrock calls; all tests pass with `python -m pytest tests/test_bedrock_client.py tests/test_rule_extraction.py tests/test_rule_engine_v3.py tests/test_model_output.py tests/test_prompt_v4_coverage.py tests/test_rule_extraction_api.py tests/test_rule_quality.py -v` |
| **Example results** | `dev-fixtures/bedrock-extraction-results/` contains four real extractions (MBO § 6 and EU Machinery Regulation Article 10, prompt versions 1–4) |

### What is not ready for external use

- **No endpoint authentication** on `POST /api/jobs/{id}/rule-extraction`.
- **DIN-specific extraction** is not yet validated (generic profile is applied).
- **Legal correctness** of extracted rules has not been verified against a reference; every record must be reviewed before use.

---

## 13. Source Layout

| Path | Contents |
|---|---|
| `src/odos/api.py` | Web API, job handling, rule-extraction endpoints |
| `src/odos/pipeline.py` | PDF processing pipeline |
| `src/odos/extraction.py` | Docling extraction |
| `src/odos/normalization/` | Reading order and source highlighting |
| `src/odos/parsing/` | Legal hierarchy, sentences, footnotes |
| `src/odos/document_model.py` | Internal data model |
| `src/odos/legal_json/` | Custom Legal JSON 2.0 export and validation |
| `src/odos/llm/` | Amazon Bedrock client, rule extraction, prompt profiles, quality checks |
| `src/odos/rule_extraction_jobs.py` | Background execution and status management for API rule extraction |
| `src/odos/cli.py` | CLI entry point (`odos` command) |
| `schemas/odos-legal-json/2.0/` | Legal JSON 2.0 schema |
| `schemas/rule-json/` | Rule JSON 2.0 schema |
| `pyproject.toml` | Package metadata, direct dependencies, CLI entry point |
| `requirements.lock` | Pinned dependency set |
| `tests/` | Automated tests (pytest); no test calls Bedrock |

---

## 14. Further Reading

| Document | Purpose |
|---|---|
| [Documentation/bedrock-rule-extraction.md](../Documentation/bedrock-rule-extraction.md) | Full technical reference: prompt layers, schema repair, quality checks, error classes, provenance rules, structured-output evaluation |
| [Documentation/architecture.md](../Documentation/architecture.md) | Component overview and live-processing data flow |
| [Documentation/rule-json.md](../Documentation/rule-json.md) | Rule JSON 2.0 schema, examples, validation |
| [Documentation/legal-json.md](../Documentation/legal-json.md) | Custom Legal JSON 2.0 schema and traceability |
| [Documentation/database-poc.md](../Documentation/database-poc.md) | Optional PostgreSQL 17 persistence: setup, tests |
| [DOCKER.md](../DOCKER.md) | Docker Compose build, test and startup workflow |
| [Documentation/development.md](../Documentation/development.md) | Local development setup (Windows/macOS/Linux) |
