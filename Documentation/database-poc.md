# PostgreSQL persistence proof of concept

Proof of concept for GitHub issue #24: ODOS jobs and their Legal JSON are stored in a local PostgreSQL 17 database as JSONB, so that processed documents survive a backend restart. The PoC is optional; without it the backend keeps its original in-memory behaviour.

## Scope

In scope:

- A local PostgreSQL 17 server in Docker (Docker Compose), reachable only from the developer's machine.
- One table, `documents`, with status, progress stage, message, processing summary (JSONB) and Legal JSON (JSONB) per uploaded PDF.
- Recording every job in the API (`backend/src/odos/api.py`) when `ODOS_DATABASE_ENABLED=1`, and restoring the jobs when the API starts.
- Automated integration tests against a separate `odos_test` database.

Out of scope: cloud hosting, shared team databases, authentication, migrations tooling, storing PDFs or result files inside PostgreSQL, and any change to the parser or the Legal JSON schema.

**Each developer runs an independent local PostgreSQL instance.** Nothing is synchronized between teammates: a document processed on one machine exists only in that machine's Docker volume and storage folder.

## Architecture

```
Browser (Vite, :5173) ──/api──▶ FastAPI odos.api (:8000) ──▶ run_pipeline (Docling, parser, Legal JSON export)
                                   │                │
                                   │                └──▶ ODOS_STORAGE_DIR/<job id>/
                                   │                        source.pdf, document.json, document_model.json,
                                   │                        docling_raw.json, reports ...
                                   ▼
                     PostgreSQL 17 (Docker, 127.0.0.1:5433)
                     database odos, table documents
                     (status, stage, message, summary JSONB, legal_json JSONB, pdf_storage_key)
```

| File | Role |
|---|---|
| `compose.yaml` | PostgreSQL 17 Alpine service `odos-postgres`, named volume `postgres_data`, healthcheck, port `127.0.0.1:5433` |
| `.env.example` | Template for the local `.env` with the database credentials (placeholders only) |
| `backend/db/001_documents.sql` | Schema of the `documents` table; idempotent (`CREATE ... IF NOT EXISTS`) |
| `backend/src/odos/database.py` | `connect()`: one psycopg 3 connection from the `POSTGRES_*` environment variables |
| `backend/src/odos/document_repository.py` | Parameterized SQL for creating, updating, reading, listing and deleting documents |
| `backend/src/odos/api.py` | Uses the repository when `ODOS_DATABASE_ENABLED=1` |
| `backend/tests/` | Tests with and without PostgreSQL; `conftest.py` holds the test-database safety guard |

### What happens in persistence mode

1. **Upload** (`POST /api/jobs`): the PDF is written to `ODOS_STORAGE_DIR/<id>/source.pdf`, then a row with status `queued` and `pdf_storage_key = "<id>/source.pdf"` is inserted. If the database is unavailable, the PDF is removed again and the API answers `503`.
2. **Processing**: the worker updates `status`/`stage` (`processing`, `extracting`, `normalizing`). At the end it stores the final status, the summary and, for completed documents, the content of `document.json` as JSONB (`legal_json`) and its `documentType` (`document_type`). The status becomes visible through the API only after the row has been written; if the result cannot be stored, the job is reported and stored as `failed`.
3. **Restart**: at startup, rows still `queued` or `processing` (their worker died with the old process) are marked `failed` with the message *Processing was interrupted by a server restart.*; then all rows are loaded into the API's job registry. `GET /api/jobs/{id}` and the result files work again.
4. **Delete** (`DELETE /api/jobs/{id}`): removes the row first, then the job folder. Queued or running jobs cannot be deleted (`409`). Every job in the API carries `"persistent": true` in this mode; the frontend then does not delete it when the user presses **Back to documents** or a document is refused. Deleting a stored document is an explicit action in the document list (Recent documents, with a confirmation) or an API call; it removes the row and that document's folder only.
5. **Reopen**: `GET /api/documents` lists the newest stored documents (metadata only). Opening a completed one reads `GET /api/jobs/{id}`, its result files and `GET /api/jobs/{id}/pdf`; the PDF path comes from the stored `pdf_storage_key` and must resolve inside `ODOS_STORAGE_DIR`. Nothing is processed again. A missing file answers `404` with a message; a job that is not completed answers `409`. Without persistence the upload is deleted after processing, so there is nothing to reopen.
6. **Shutdown**: queued jobs are cancelled (they are marked as interrupted at the next start); the running job is completed and stored before the process exits.

Without `ODOS_DATABASE_ENABLED=1`, none of this happens: jobs live in memory, the uploaded PDF is deleted after processing, old jobs are pruned, and temporary storage is removed at shutdown.

### PDFs and result files are not in PostgreSQL

PostgreSQL holds metadata, the processing summary and the Legal JSON only. The original PDF and all generated files (`document_model.json`, `docling_raw.json`, reports) stay on the local disk under `ODOS_STORAGE_DIR`. `pdf_storage_key` is relative to that folder, so **start the backend with the same `ODOS_STORAGE_DIR` every time**. If the folder is moved or deleted, the restored jobs remain visible, but their files answer `404 The result file is no longer available.`

### PostgreSQL 17 and JSONB

`summary` and `legal_json` are `JSONB` columns: PostgreSQL validates that the value is JSON, stores it in a binary form and allows queries into it (`->`, `->>`, `#>>`, `jsonb_path_query`, GIN indexes later if needed). psycopg 3 writes Python dicts with `Jsonb(...)` and returns JSONB as Python dicts. JSONB normalizes key order and whitespace, so the stored Legal JSON is equal to `document.json` as data, not byte for byte.

A stored Legal JSON is not necessarily schema-valid: the database stores what the pipeline produced. Check `summary->'json_schema_valid'`, `summary->'parser_warnings'` and `summary->'uncertain_elements'` (for the Musterbauordnung currently `false`, `17`, `27`).

### Schema

| Column | Type | Notes |
|---|---|---|
| `id` | `TEXT PRIMARY KEY` | Job ID (UUID hex) |
| `filename` | `TEXT NOT NULL` | Uploaded file name (display only) |
| `document_type` | `TEXT` | `documentType` of the Legal JSON, e.g. `de_legislation`, `eu_regulation` |
| `status` | `TEXT NOT NULL` | `CHECK` in `queued`, `processing`, `completed`, `unsupported`, `failed` |
| `stage` | `TEXT` | Progress while processing, otherwise `NULL` |
| `message` | `TEXT` | Result or error message shown to the user |
| `summary` | `JSONB NOT NULL` | Pipeline summary (pages, counts, validation flags) |
| `legal_json` | `JSONB` | Custom Legal JSON 2.0; `NULL` unless completed |
| `pdf_storage_key` | `TEXT NOT NULL` | `<id>/source.pdf`, relative to `ODOS_STORAGE_DIR` |
| `created_at`, `updated_at` | `TIMESTAMPTZ` | Set by the database / on every update |

Index: `idx_documents_status` on `status`.

## Prerequisites (macOS)

- [Docker Desktop for Mac](https://docs.docker.com/desktop/setup/install/mac-install/) (Apple Silicon or Intel), started. `docker compose version` must work.
- Python 3.12 and the backend virtual environment (`backend/.venv`), see below.
- Node.js 22.12 or newer for the frontend.
- Optional: `psql` (`brew install libpq`) or [DBeaver Community](https://dbeaver.io/download/). Neither is required: `psql` is also available inside the container.

All commands below are for zsh in Terminal, run from the repository root unless stated otherwise.

## Setup

### 1. Create `.env`

```bash
cp .env.example .env
```

Open `.env` and replace `replace_with_local_password` with a password of your choice. `.env` is ignored by Git; never commit it or paste it into issues or chat. Docker Compose reads it automatically; the backend reads the same variables after you export them (step 5).

`POSTGRES_PASSWORD` is applied only when the volume is created the first time. Changing it later in `.env` does not change the database password (see Troubleshooting).

### 2. Start PostgreSQL

```bash
docker compose up -d
docker compose ps
```

Wait until the status shows `(healthy)`. The server listens on `127.0.0.1:5433` only (not on the network); inside the container it is the default port 5432.

Stop it (data is kept):

```bash
docker compose stop
```

`docker compose down` also removes the container but keeps the named volume. **Do not run `docker compose down -v` or `docker volume rm`**: that deletes all stored documents. The container has `restart: unless-stopped`, so it starts again with Docker Desktop until you stop it.

### 3. Initialize the schema

On the first start with an empty volume, Docker runs `backend/db/001_documents.sql` automatically (the folder is mounted as `/docker-entrypoint-initdb.d`). For an existing volume, or to be sure, apply it manually; it is safe to run repeatedly:

```bash
docker exec -i odos-postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' < backend/db/001_documents.sql
```

Messages such as `relation "documents" already exists, skipping` are expected.

### 4. Create the test database (once)

```bash
docker exec odos-postgres sh -c 'createdb -U "$POSTGRES_USER" odos_test'
```

The tests create the table in `odos_test` themselves. An error `database "odos_test" already exists` means this step was already done.

### 5. Install and start the backend in persistence mode

Once, from `backend`:

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
```

Every start, from `backend`:

```bash
set -a; source ../.env; set +a
export ODOS_DATABASE_ENABLED=1
export ODOS_STORAGE_DIR="$PWD/storage/documents"
.venv/bin/python -m uvicorn odos.api:app --port 8000
```

`set -a` exports every variable from `.env` into this terminal only. `backend/storage/` is ignored by Git. Startup fails with a clear error if `ODOS_STORAGE_DIR` is missing, a `POSTGRES_*` variable is missing or PostgreSQL is not reachable. Run a single Uvicorn process (no `--workers`, no second instance on the same database): the job registry and the worker belong to one process.

| Variable | Default | Purpose |
|---|---|---|
| `ODOS_DATABASE_ENABLED` | unset | `1` enables PostgreSQL persistence |
| `ODOS_STORAGE_DIR` | temporary | Required with persistence; PDFs and result files |
| `POSTGRES_HOST` | `127.0.0.1` | Database host |
| `POSTGRES_PORT` | `5433` | Database port published by `compose.yaml` |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | none | From `.env` |

### 6. Start the frontend

In a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open `http://localhost:5173`, select a PDF and press **Process Document**. The frontend reaches the backend through the Vite proxy. In persistence mode it keeps processed documents; without persistence it deletes a job when you leave its result, as before.

## Verify stored documents

After processing a PDF:

```bash
docker exec odos-postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
  SELECT id, filename, document_type, status, jsonb_typeof(legal_json) AS legal_json,
         summary->>'"'"'json_schema_valid'"'"' AS schema_valid, created_at
  FROM documents ORDER BY created_at DESC;"'
```

Expected for a completed document: `status = completed`, `legal_json = object`. Through the API (replace the ID):

```bash
curl -s http://127.0.0.1:8000/api/jobs/<document-id>
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/api/jobs/<document-id>/files/document.json
```

### Verify persistence after a backend restart

1. Process a PDF and note its ID (from the query above).
2. Stop Uvicorn with Ctrl+C and start it again with the same commands from step 5 (same `ODOS_STORAGE_DIR`).
3. `curl -s http://127.0.0.1:8000/api/jobs/<document-id>` answers `200` with `"status":"completed"`, and `.../files/document.json` answers `200`.

The frontend has no list of earlier documents yet; after a restart, stored documents are reachable through the API by ID.

## Inspect the database with psql

Inside the container (no local installation needed):

```bash
docker exec -it odos-postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

With a local `psql` (enter the password from `.env` when asked):

```bash
psql -h 127.0.0.1 -p 5433 -U odos -d odos
```

Useful queries:

```sql
\d documents
SELECT id, filename, status, stage, updated_at FROM documents ORDER BY created_at DESC;
SELECT jsonb_pretty(summary) FROM documents WHERE id = '<document-id>';
SELECT legal_json->>'title', jsonb_array_length(legal_json->'structure') FROM documents WHERE status = 'completed';
SELECT pg_size_pretty(pg_column_size(legal_json)::bigint) FROM documents WHERE id = '<document-id>';
```

Only read data by hand. Deleting rows directly leaves the job folder on disk; use `DELETE /api/jobs/{id}` instead.

## Connect with DBeaver Community

1. **Database → New Database Connection → PostgreSQL**. Let DBeaver download the driver if asked.
2. Host `127.0.0.1`, port `5433`, database `odos`, username `odos` (or your `POSTGRES_USER`), password from `.env`. Leave SSL off; the server is local only.
3. **Test Connection**, then **Finish**. The table is under `odos → Schemas → public → Tables → documents`.
4. JSONB columns open in the value viewer as JSON. Prefer read-only use (connection settings → *Read-only connection*).

## Run the tests safely

From `backend`, with PostgreSQL running and `odos_test` created:

```bash
set -a; source ../.env; set +a
.venv/bin/python -m pytest -v tests
```

- The tests always use the database named by `ODOS_TEST_DATABASE` (default `odos_test`), even when `.env` exported `POSTGRES_DB=odos`. A name that does not end in `_test` is refused, and the server-side database name is checked again before the `documents` table is emptied. The regular `odos` database is never touched.
- Each database test starts and ends with an empty `documents` table in `odos_test`; job files go to pytest's temporary folders.
- The pipeline is replaced by a fake, so the tests take about a second and do not run Docling.
- Without exported credentials or without a reachable server, the database tests are reported as skipped (`-rs` shows why); the tests without PostgreSQL still run.

| File | Covers |
|---|---|
| `tests/test_database_api.py` | Safety guard, connection, create/read, JSONB round trip, status updates, constraints, SQL parameters, listing, deletion, interrupted jobs, API restart, unsupported and failed documents, missing files, storage failure |
| `tests/test_api_without_database.py` | In-memory mode without any database call, upload validation, configuration errors, database outage on upload, delete and startup |
| `tests/test_page_rendering.py` | Docling renders non-embedded PDF fonts as real glyphs (needs a substitute font such as fonts-liberation; see DOCKER.md) |
| `tests/test_reference_documents.py` | Real pipeline on the MBO and EU 2023/1230 (slow, minutes; skipped without the partner PDFs, see `backend/data/input/SOURCE.md`) |
| `frontend/src/demo/live.test.tsx` | The frontend deletes a finished job only when the backend does not keep it (`npx vitest run src/demo/live.test.tsx` in `frontend`) |

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Cannot connect to the Docker daemon` | Start Docker Desktop and wait until it is running. |
| `required variable POSTGRES_PASSWORD is missing a value` | `.env` is missing or incomplete: `cp .env.example .env` and set the password. |
| `Bind for 127.0.0.1:5433 failed: port is already allocated` | Another service uses 5433: `lsof -nP -iTCP:5433 -sTCP:LISTEN`. Stop it, or change the host port in `compose.yaml` and `POSTGRES_PORT` together. |
| Container stays `unhealthy` / restarts | `docker compose logs postgres` |
| `password authentication failed for user "odos"` | The password in `.env` differs from the one the volume was created with. Restore the original value in `.env`, or change the database password with `docker exec -it odos-postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'` and `ALTER USER odos PASSWORD '<new>';`. Do not delete the volume. |
| `Database settings missing from the environment: ...` | Export `.env` in the backend terminal: `set -a; source ../.env; set +a`. |
| `ODOS_STORAGE_DIR is required when database persistence is enabled` | Set `ODOS_STORAGE_DIR` (step 5). |
| `connection failed: ... Connection refused` at backend startup | PostgreSQL is not running or the port is wrong: `docker compose ps`. |
| `relation "documents" does not exist` | Apply the schema (step 3). |
| Upload answers `503 The ODOS database is not available` | PostgreSQL went down while the backend was running; start it again and retry. |
| Restored job: result files answer `404` | The backend runs with a different `ODOS_STORAGE_DIR`, or the job folder was deleted. |
| Database tests all skipped | Credentials not exported, or `database "odos_test" does not exist` (step 4). |
| `Refusing to run database tests against ...` | `ODOS_TEST_DATABASE` must end in `_test`. |
| Backend hangs on Ctrl+C | A document is still being processed; it is stored before the process exits. Press Ctrl+C again to abort (the job is then marked as interrupted at the next start). |

## Known limitations and possible next steps

- The document list shows only the newest 20 stored documents; there is no search, paging or user separation (every stored document is visible to everyone who can reach the API).
- Files live outside the database, on one machine, without backup; `pdf_storage_key` depends on `ODOS_STORAGE_DIR`. Object storage (or `bytea`/large objects) would be the next step for a shared setup.
- One local database per developer; no shared or hosted instance, no synchronization.
- No migrations tool: `001_documents.sql` is applied by hand or on the first start of an empty volume. Later schema changes need a migration approach (e.g. Alembic or numbered SQL files with a version table).
- One connection per database operation, no pool; adequate for one local user, not for load.
- Single API process only; interrupted jobs are marked `failed`, not re-queued.
- In persistence mode, old jobs are no longer pruned (`MAX_JOBS`); the database and `ODOS_STORAGE_DIR` grow until documents are deleted.
- If a progress update cannot be written while a document is processed, the job ends as `failed`.
- No authentication or authorization; the database is protected only by binding to `127.0.0.1` and the local password.
- Stored Legal JSON reflects the parser's current quality; for the Musterbauordnung `json_valid` and `json_schema_valid` are `false` with 17 parser warnings and 27 uncertain elements. This is a parser topic, not a persistence error.
