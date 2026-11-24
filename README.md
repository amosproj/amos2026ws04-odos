# ODOS Build Documentation

This guide explains how to build, test and run the ODOS project locally using Docker. It covers the required software, database and API-key configuration, automated tests, and the commands for starting and updating the application.

## 1. Requirements

Install Git and Docker Desktop (Linux containers; WSL 2 on Windows). Start Docker before continuing. Host ports 5173, 8000 and 5433 must be available. Python 3.12, Node.js 22 and PostgreSQL 17 run in containers. All commands below use PowerShell. Internet access is required for initial downloads; allow several GB of free disk space.

## 2. Clone, configure and build

```powershell
git clone --branch main `
  https://github.com/amosproj/amos2026ws04-odos.git ODOS
cd ODOS

Copy-Item .env.example .env
```

The commands use the main branch. If you already have a clone, open its root folder instead of cloning again. Skip the copy if .env already exists; do not overwrite your local settings.

### Configure the PostgreSQL password and optional API key

Open .env, not .env.example, in your editor. Keep POSTGRES_USER=odos and POSTGRES_DB=odos from the template for the commands below. Set these values:

```text
POSTGRES_PASSWORD=your_local_database_password
AWS_BEARER_TOKEN_BEDROCK=
```

PostgreSQL password: replace your_local_database_password with a password you choose for your local database. Do not leave the template placeholder. Compose supplies it to PostgreSQL and the backend so they can connect. Existing database volumes retain their original credentials: changing .env alone does not change an already initialized database password.

Bedrock API key: an authorized key is required only for real LLM rule extraction. It is not supplied in the repository. Request access from the project maintainer or the person responsible for the project's AWS/Bedrock account. Once provided, enter it after AWS_BEARER_TOKEN_BEDROCK=, save the .env file, and run docker compose up -d to apply it.

Until you receive a key, leave the API-key value empty. You can still build, run tests, open the frontend and process supported PDFs into Legal JSON. Paid rule extraction will be unavailable. Do not share or commit passwords or API keys. Starting real extraction uses the project's Bedrock account and incurs charges.

### Check the configuration

```powershell
docker compose config --quiet
```

### Build the application

```powershell
docker compose build
```

### Start the database

```powershell
docker compose up -d postgres
```

```powershell
docker compose ps
```

### Create the test database (only needed for backend tests)

```powershell
docker compose exec postgres createdb -U odos odos_test
```

Wait for PostgreSQL to be healthy before creating odos_test. Successful creation normally prints nothing. “Already exists” means the database is already created, which is fine.

The frontend build checks TypeScript and compiles the app. The backend installs dependencies and runs pip check. Cached builds can be much faster.

## 3. Run tests

### Backend tests

```powershell
docker compose run --rm --no-deps `
  -e AWS_BEARER_TOKEN_BEDROCK= `
  -e ODOS_RULE_EXTRACTION_ARCHIVE_DIR= `
  -e ODOS_RULE_EXTRACTION_REPORT_DIR= `
  -v ./backend/tests:/app/backend/tests:ro `
  -v ./backend/db:/app/backend/db:ro `
  -v ./dev-fixtures:/app/dev-fixtures:ro `
  backend python -m pytest -v -m "not slow" tests
```

### Frontend tests

```powershell
docker compose run --rm --no-deps `
  -v ./backend:/app/backend:ro `
  -v ./compose.yaml:/app/compose.yaml:ro `
  -v ./LICENSE:/app/LICENSE:ro `
  frontend npm test -- --testTimeout=20000 --maxWorkers=2
```

Read the final summaries: failures/errors require investigation; deselected tests include the excluded slow suite. Optional PDF/processed-JSON checks may skip, but database tests skipping due to a failed connection need attention.

## 4. Start and verify the local application

### Start

```powershell
docker compose up -d
```

### Check status

```powershell
docker compose ps
```

Open http://localhost:5173; API docs are http://localhost:8000/docs. PostgreSQL is exposed on host port 5433. Database/backend should be healthy and frontend running. Refresh with Ctrl+F5. Extraction preview prepares an estimate without calling the LLM. Starting real Bedrock extraction incurs charges.

### For subsequent build-and-start runs use

```powershell
docker compose up --build -d
```

This is local deployment: the frontend runs Vite's development server. Digital-twin validation is currently a preview, not a working validation check.

## 5. Stored data and database setup

ODOS keeps uploaded documents, results and review decisions in Docker volumes between sessions.

Stop it with docker compose down and restart with docker compose up -d. Do not use down --volumes for routine restarts, since it deletes stored data.

## 6. Updating ODOS and checking changes

Preserve local changes first. From a clean checkout, update main and rebuild/start the application:

```powershell
git switch main
git pull --ff-only origin main
docker compose up --build -d
```

Rerun the tests after updates. After changing only .env, use docker compose up -d to apply the settings.

## 7. Build-process video

The narrated [build-process video](https://github.com/amosproj/amos2026ws04-odos/blob/main/Deliverables/sprint-05/build-process-video.mp4) demonstrates the build process workflow: cloning the repository, configuring the environment, building the images, running backend and frontend tests, and starting the application. It concludes by opening the frontend in the browser.

Repository path: Deliverables/sprint-05/build-process-video.mp4

## 8. Versioning

The main branch contains the project version used in this guide. Release tags identify specific versions of the code. To check the exact revision currently downloaded, run git rev-parse HEAD.

