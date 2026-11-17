# ODOS: build, test and run with Docker

These instructions cover the local Docker workflow for the current project:
clone a clean repository, configure it, build the images, run automated tests,
and open the frontend. PDF processing is not required for the startup check.

Run the commands in a **PowerShell terminal**, one at a time. Unless stated
otherwise, stay in the repository root: the folder containing `compose.yaml`,
`backend` and `frontend`. Stop and investigate if a command fails.

## Requirements

- Git and VS Code.
- Docker Desktop running with Linux containers; on Windows, use the WSL 2 backend.
- Internet access for container images and dependencies.
- Several GB of free disk space and sufficient Docker memory. The existing
  Docker guide suggests an 8 GB starting allocation for document processing;
  actual needs depend on the workload.
- Available host ports 5173, 8000 and 5433.

Python and Node.js run inside the containers; separate host installations are
not required for this workflow. Stop any older ODOS stack before starting a new
checkout: this configuration uses the fixed container name `odos-postgres`.

## 1. Clone a clean checkout

Use the repository's GitHub clone URL if it differs from the example below.
The branch must contain the version you intend to demonstrate.

```powershell
git clone --branch develop https://github.com/amosproj/amos2026ws04-odos.git odos-build-video
cd odos-build-video
git status
git log -1 --oneline
```

Open this folder in VS Code.

## 2. Configure the environment

For a new checkout:

```powershell
Copy-Item .env.example .env
```

Edit `.env`, keeping `POSTGRES_USER=odos` and `POSTGRES_DB=odos` for the
commands below. Replace `POSTGRES_PASSWORD` with a local password. Do not
commit this file or display its password in a recording.

If `.env` already exists, edit it instead of overwriting it. Existing database
volumes retain their original database credentials; editing `.env` does not
change a password already stored in PostgreSQL.

Validate the configuration without printing the resolved credentials:

```powershell
docker compose config --quiet
```

No output normally means validation succeeded.

## 3. Build the images

```powershell
docker compose build
```

The frontend image runs `npm ci` and `npm run build`. The build performs
TypeScript checking and generates `dist/`.

The backend image installs its system and Python dependencies, installs the
ODOS package and runs `pip check`.

Continue only when the build succeeds.

## 4. Start PostgreSQL and create the test database

```powershell
docker compose up -d postgres
docker compose ps
```

Wait until PostgreSQL is healthy, then run:

```powershell
docker compose exec postgres createdb -U odos odos_test
```

Create this database once per PostgreSQL volume. A message that `odos_test`
already exists means it is already available. Other errors need investigation.

The tests enforce a database name ending in `_test` and use `odos_test`
by default. They create the test table and clear its records between tests.
The application uses the separate `odos` database.

If you changed `POSTGRES_USER`, replace `odos` after `-U` with that username.

## 5. Run the backend tests

Run the following as one command:

```powershell
docker compose run --rm --no-deps -v ./backend/tests:/app/backend/tests:ro -v ./backend/db:/app/backend/db:ro -v ./dev-fixtures:/app/dev-fixtures:ro backend python -m pytest -v -m "not slow" tests
```

The mounts supply tests, database initialization SQL and rule examples that
are not copied into the backend image. Compose supplies the database
connection settings; PostgreSQL must already be running.

This selection covers:

- API behavior with and without database persistence.
- PostgreSQL repository and persistence integration.
- Legal JSON schema compatibility.
- Rule JSON schema and example validation.
- Legal text continued across page breaks and its source geometry.
- PDF rendering with non-embedded fonts.

The command excludes tests marked `slow`, which process complete reference PDFs.
Two additional Rule JSON source-reference checks skip unless
`ODOS_MBO_LEGAL_JSON_PATH` and `ODOS_EU_LEGAL_JSON_PATH` are configured with
accessible Legal JSON files. Read the final pytest summary and skip reasons.
Skipped tests are not passed tests.

For full reference-document tests, see `backend/data/input/SOURCE.md`,
`DOCKER.md` and `Documentation/database-poc.md`. Partner PDFs are not included
in Git. They are unnecessary for the selected startup demonstration.

## 6. Run the frontend tests

```powershell
docker compose run --rm --no-deps frontend npm test
```

The frontend tests cover document upload and processing states, document lists,
hierarchy navigation, JSON views, source highlights and interface interactions.
Read the final Vitest result and resolve failures before proceeding.

This checkout has no GitHub Actions workflow. Run the tests locally as above.

## 7. Start the complete application

```powershell
docker compose up -d
docker compose ps
```

Wait for PostgreSQL and the backend to become healthy and the frontend to be
running. The frontend has no separate health check in this configuration.

Open:

- Frontend: http://localhost:5173
- API documentation: http://localhost:8000/docs

The startup check is complete when the frontend opens and the services have
the expected status. This demonstrates startup; it does not demonstrate the
PDF-processing workflow.

The frontend container starts Vite's development server. These instructions
describe local development, not a production deployment.

## 8. Stop or restart later

Stop the stack while retaining its named volumes:

```powershell
docker compose down
```

Start it again:

```powershell
docker compose up -d
```

After source or dependency changes:

```powershell
docker compose build
docker compose up -d
```

Avoid `docker compose down --volumes` unless you intend to delete the stored
database, result files and downloaded model cache.

## Troubleshooting

| Problem | What to check |
| --- | --- |
| Missing POSTGRES variables | Create and fill in the root `.env` file before running Compose. |
| Docker cannot connect to its engine | Start Docker Desktop and wait until it is ready. |
| Container name or port already in use | Stop the previous ODOS stack or conflicting local server. |
| Backend unhealthy | Run `docker compose logs --tail 100 backend`. |
| Database authentication fails | Verify the credentials match those used when the volume was initialized. |
| Database tests skip unexpectedly | Check PostgreSQL is healthy and `odos_test` exists. |
| Missing test/example files | Use the backend test command above with all three mounts, from the repository root. |
| Frontend does not open | Check `docker compose ps` and `docker compose logs --tail 100 frontend`. |

## Build-process video

Show the clean clone, configuration check, image build, automated test results,
service status and frontend startup. Narrate each step. Long installations
may be paused in the recording.

Save the recording as `Deliverables/sprint-05/build-process-video.mp4`
(or another accepted common video format with the same base name).

## Configuration and storage

| Variable | Purpose |
|---|---|
| `ODOS_STORAGE_DIR` | Backend job-file location; temporary storage is used by default |
| `ODOS_MAX_UPLOAD_MB` | Upload size limit; default 50 MB |
| `ODOS_API_URL` | Vite proxy's backend address; default `http://127.0.0.1:8000` |

Set variables before starting the corresponding process. Jobs are processed one at a time. Uploaded PDFs are deleted after processing; the browser displays its own local copy. Temporary storage is removed on shutdown, and old completed jobs may be deleted as the job limit is reached.

Setting `ODOS_STORAGE_DIR` retains files but does not restore the in-memory job registry after restart. Do not commit uploaded PDFs, generated document data, virtual environments or `node_modules`.

Optional persistence: with a local PostgreSQL 17 database (Docker Compose) and `ODOS_DATABASE_ENABLED=1`, jobs and their Legal JSON are stored as JSONB and restored after a backend restart; the uploaded PDF and result files are kept, and old jobs are not removed automatically. See the [PostgreSQL proof of concept](Documentation/database-poc.md). [DOCKER.md](DOCKER.md) runs PostgreSQL, backend and frontend with Docker Compose, with this persistence enabled. To start the stack and inspect the stored Legal JSON with `psql`, see the [Docker and PostgreSQL developer guide](Documentation/docker-postgresql-guide.md).

## Repository layout

| Folder | Contents |
|---|---|
| `backend/` | Python pipeline, API, CLI and Legal JSON schema |
| `frontend/` | React/TypeScript application and Vite configuration |
| `Documentation/` | [Architecture and development documentation](Documentation/README.md) |
| `Deliverables/` | Sprint submission materials |

For command-line processing, parsing details and schema changes, see [Documentation/README.md](Documentation/README.md).
