# Docker and PostgreSQL developer guide

This guide shows how to start ODOS with Docker Compose, connect to the local PostgreSQL database, and inspect the persisted Legal JSON. Every query is generic: you first pick a stored document and then query it by ID, so nothing here depends on a particular PDF.

For the design behind the persistence (table schema, API behaviour, tests), see [database-poc.md](database-poc.md). For building and troubleshooting the images, see [DOCKER.md](../DOCKER.md).

**Current status:** PostgreSQL runs locally on each developer's machine, in Docker. There is no shared or hosted database, and no database web client is part of ODOS. Hosted PostgreSQL (for example Neon) and clients such as pgAdmin or Adminer are possible future options only; nothing in this repository uses them yet.

## 1. Three things that are easy to confuse

| Term | What it is | Where it lives |
|---|---|---|
| **Legal JSON 2.0** | The actual structured document: title, hierarchy of parts, sections or articles, paragraphs, text, page numbers, footnotes. This is the data. | `documents.legal_json` (and the file `document.json` in the backend storage volume) |
| **Legal JSON Schema 2.0** | The JSON Schema (Draft 2020-12) that describes what a valid Legal JSON 2.0 document looks like. It is a set of rules, not document data. The backend validates every generated document against it. | `backend/schemas/odos-legal-json/2.0/legal-document.schema.json`. It is not stored in PostgreSQL. |
| **PostgreSQL JSONB** | The database column type that stores JSON in a binary form and can be queried (`->`, `->>`, `jsonb_path_query`). It says nothing about the content. | The type of the columns `documents.summary` and `documents.legal_json` |

In short: the *schema* defines the shape, the *Legal JSON* is a document of that shape, and *JSONB* is how PostgreSQL stores that document.

Consequences for you:

- A row can hold JSONB that does not conform to the schema. The database stores what the pipeline produced. Whether the document passed schema validation is recorded in `summary->>'json_schema_valid'`.
- JSONB normalizes key order and whitespace, so `legal_json` equals `document.json` as data, not byte for byte.
- PostgreSQL never reads the Legal JSON Schema. Schema validation happens in the backend (see [legal-json.md](legal-json.md)).

## 2. Prerequisites

- **Docker Desktop**, installed and running. On Windows use Linux containers with the WSL 2 backend. Check with `docker compose version`.
- **The repository**, cloned. Run all commands from the repository root (the folder containing `compose.yaml`) unless stated otherwise.
- **A `.env` file** in the repository root. Create it from the template and set a local password:

  ```bash
  cp .env.example .env
  ```

  | Variable | Meaning |
  |---|---|
  | `POSTGRES_USER` | Database user (the template uses `odos`) |
  | `POSTGRES_PASSWORD` | Local password of your choice. Replace the placeholder. |
  | `POSTGRES_DB` | Database name (the template uses `odos`) |
  | `POSTGRES_HOST`, `POSTGRES_PORT` | Only used when the backend runs on your host machine instead of in Docker. Compose sets its own values for the backend container (`postgres:5432`). |

  `.env` is ignored by Git. Never commit it and never paste its content into issues or chat. `compose.yaml` refuses to start if `POSTGRES_USER`, `POSTGRES_PASSWORD` or `POSTGRES_DB` is missing.

  `POSTGRES_PASSWORD` is applied only when the database volume is created for the first time. Changing it in `.env` later does not change the password of an existing database.

Optional: a local `psql` client is **not** needed. All commands below run `psql` inside the container.

## 3. Start the application

```bash
docker compose up -d --build
```

Builds the backend and frontend images and starts PostgreSQL, backend and frontend in the background (`-d`). The first build downloads several GB of dependencies; the first PDF extraction additionally downloads Docling models. Startup order is enforced: the backend waits for a healthy database, the frontend waits for a healthy backend.

Check the services:

```bash
docker compose ps
```

Expected output (abbreviated): three services, all `Up`, with `postgres` and `backend` showing `(healthy)`. The backend can take up to a minute or two to become healthy.

| Service | Container | Host address | Container port | Purpose |
|---|---|---|---|---|
| `frontend` | `<project>-frontend-1` | `http://localhost:5173` | 5173 | Web app |
| `backend` | `<project>-backend-1` | `http://localhost:8000` (API docs: `/docs`) | 8000 | FastAPI, Docling pipeline |
| `postgres` | `odos-postgres` | `127.0.0.1:5433` | 5432 | PostgreSQL 17 |

Notes:

- All ports are bound to `127.0.0.1` and are not reachable from other machines.
- PostgreSQL is published on host port **5433**, not 5432, so it does not clash with a PostgreSQL installed on your machine. Inside Docker (for example from the backend container) it is `postgres:5432`.
- `<project>` is the Compose project name, by default the name of the repository folder. The PostgreSQL container has the fixed name `odos-postgres`, which is why the commands below use it.

Open `http://localhost:5173`, upload a PDF and process it. Documents are written to PostgreSQL when processing finishes. Without at least one processed document, the queries below return empty results.

## 4. Check that PostgreSQL is ready

```bash
docker exec odos-postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

`pg_isready` only asks the server whether it accepts connections; it does not log in. Expected output:

```
/var/run/postgresql:5432 - accepting connections
```

`no response` or `rejecting connections` means the server is still starting or has failed (see Troubleshooting).

The single quotes matter: `$POSTGRES_USER` and `$POSTGRES_DB` must be expanded by the shell *inside* the container, where Compose has set them. Your host shell does not know these variables.

## 5. Open a psql session

```bash
docker exec -it odos-postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

`-it` gives you an interactive terminal. You get a prompt like `odos=#`. No password is asked, because the connection is local inside the container.

Inside `psql`:

- Commands starting with a backslash (`\dt`, `\d`, `\q`) are `psql` commands and need no semicolon.
- SQL statements must end with `;`.
- Leave with `\q`.

All following sections assume you are inside this session. Only run read-only statements (`SELECT`) by hand; see [Data persistence](#10-data-persistence-docker-volumes-and-safe-restarts) for deleting documents.

### List tables

```
\dt
```

Lists the tables of the current database. Expected: one table, `documents`, in schema `public`, owned by your `POSTGRES_USER`.

### Inspect the `documents` table

```
\d documents
```

Shows columns, types, defaults, indexes and constraints. Expected columns:

| Column | Type | Meaning |
|---|---|---|
| `id` | `text` (primary key) | Document/job ID |
| `filename` | `text` | Name of the uploaded file |
| `document_type` | `text` | Recognized type, for example `de_legislation` or `eu_regulation` |
| `status` | `text` | `queued`, `processing`, `completed`, `unsupported` or `failed` (enforced by a check constraint) |
| `stage` | `text` | Progress stage while processing, otherwise empty |
| `message` | `text` | Result or error message |
| `summary` | `jsonb` | Processing summary (page and element counts, validation flags) |
| `legal_json` | `jsonb` | The Legal JSON 2.0 document; empty (`NULL`) unless processing completed |
| `pdf_storage_key` | `text` | Path of the PDF relative to the backend storage folder (the PDF itself is not in PostgreSQL) |
| `created_at`, `updated_at` | `timestamptz` | Timestamps |

### Count stored documents

```sql
SELECT COUNT(*) FROM documents;
```

Returns one row with the number of rows in `documents`, including failed and unsupported ones. `0` means nothing has been persisted yet.

To see how many documents have each status:

```sql
SELECT status, COUNT(*) FROM documents GROUP BY status ORDER BY status;
```

### List available documents

```sql
SELECT id, filename, document_type, status, created_at
FROM documents
ORDER BY created_at DESC;
```

One row per stored document, newest first. Copy the `id` of a row with `status = completed`: only those have a Legal JSON.

A more informative variant that also shows whether a Legal JSON is stored and whether it passed schema validation:

```sql
SELECT id, filename, status,
       legal_json IS NOT NULL                AS has_legal_json,
       summary->>'json_schema_valid'         AS schema_valid,
       created_at
FROM documents
ORDER BY created_at DESC;
```

`schema_valid` is `true` or `false` as reported by the backend, or empty if the summary does not contain the key (for example for failed documents). Older rows may have an empty `document_type` even though their `legal_json` has a `documentType`; the Legal JSON is authoritative.

### Select a document once, reuse it everywhere

To avoid pasting the ID into every query, store it in a `psql` variable. Either set it by hand:

```
\set doc_id '<document-id>'
```

or pick the newest completed document automatically:

```sql
SELECT id AS doc_id
FROM documents
WHERE status = 'completed'
ORDER BY created_at DESC
LIMIT 1 \gset
```

`\gset` stores the result in the variable `doc_id` and prints nothing. (If no completed document exists, `psql` reports `no rows returned for \gset`.) Check it with `\echo :doc_id`.

In SQL, write the variable as `:'doc_id'` (with quotes); `psql` replaces it by a properly quoted string literal. This substitution works in normal SQL statements but **not** inside `$$ ... $$` blocks or inside an existing quoted string. That is why the JSONPath examples below hand values to JSONPath through its `vars` argument instead of building the path string.

## 6. Inspect the JSONB columns

### `summary`

```sql
SELECT jsonb_pretty(summary) FROM documents WHERE id = :'doc_id';
```

`jsonb_pretty` formats JSONB with indentation. Expected: a small object with counters and flags, for example `pages`, `elements`, `paragraphs`, `parser_warnings`, `uncertain_elements`, `json_valid`, `json_schema_valid`, `json_text_identical`, `toc_found`, `docling_status`. The exact set comes from the pipeline and may change.

Single values:

```sql
SELECT summary->>'json_schema_valid'  AS schema_valid,
       summary->>'parser_warnings'    AS parser_warnings,
       summary->>'uncertain_elements' AS uncertain_elements
FROM documents WHERE id = :'doc_id';
```

`->` returns JSONB, `->>` returns text. Use `->>` for printing and comparing, `->` when you want to continue navigating into the value.

### `legal_json`: top level

```sql
SELECT jsonb_typeof(legal_json) AS json_type,
       legal_json->>'title'          AS title,
       legal_json->>'documentType'   AS document_type,
       legal_json->>'schemaVersion'  AS schema_version,
       jsonb_array_length(legal_json->'structure') AS top_level_nodes
FROM documents WHERE id = :'doc_id';
```

Expected: `json_type = object`, `schema_version = 2.0`, and the number of top-level nodes of the hierarchy. `jsonb_typeof` is also a quick way to see whether a document has Legal JSON (`object`) or not (empty).

List all top-level keys with their JSON types:

```sql
SELECT key, jsonb_typeof(value) AS json_type
FROM documents, jsonb_each(legal_json)
WHERE id = :'doc_id'
ORDER BY key;
```

Expected keys include `id`, `title`, `version`, `language`, `legalSystem`, `documentType`, `schemaVersion`, `pageCount`, `frontMatter`, `tableOfContents`, `tableOfContentsEntries`, `structure`, `footnotes`, `sentences`. The field `structure` is the legal hierarchy; see [legal-json.md](legal-json.md) for the meaning of the fields. Optional fields can be absent.

### Pretty-print a complete Legal JSON

```sql
SELECT jsonb_pretty(legal_json) FROM documents WHERE id = :'doc_id';
```

Prints the whole document. This is long (hundreds of kilobytes for a full law), so `psql` opens it in a pager: scroll with the arrow keys, leave with `q`. For plain output without table borders:

```
\pset format unaligned
\pset tuples_only on
SELECT jsonb_pretty(legal_json) FROM documents WHERE id = :'doc_id';
```

Restore the defaults with `\pset format aligned` and `\pset tuples_only off`.

To look at the metadata without the large arrays:

```sql
SELECT jsonb_pretty(legal_json - 'structure' - 'sentences' - 'footnotes'
                    - 'frontMatter' - 'tableOfContents' - 'tableOfContentsEntries')
FROM documents WHERE id = :'doc_id';
```

The `-` operator removes keys from a JSONB value; the stored data is not changed.

Do not write exports of real documents into the repository. Legal JSON generated from partner PDFs must not be committed.

## 7. Query a specific legal element with JSONPath

The `structure` array is a tree: each node can have `children`, to arbitrary depth. A node looks like this (fields vary by node type):

```json
{
  "id": "<node-id>",
  "type": "<section | article | subsection | paragraph | ...>",
  "germanType": "<source-language term, if any>",
  "marker": "<label as printed>",
  "number": "<identifier>",
  "title": "<heading, if any>",
  "text": "<own text, if any>",
  "pages": [1],
  "children": [ ]
}
```

Node `id`s are unique within a document and have a path-like form (for example `doc/<part>/<section>`), but their exact form depends on the document and parser version. Always look them up first instead of guessing them.

### Step 1: find the ID of the element you want

List the main provisions (German `section` or EU `article`) of the selected document:

```sql
SELECT n->>'id'     AS node_id,
       n->>'type'   AS type,
       n->>'marker' AS marker,
       n->>'title'  AS title
FROM documents,
     jsonb_path_query(legal_json,
       'strict $.structure[*].** ? (@.type == "section" || @.type == "article")') AS n
WHERE id = :'doc_id';
```

How the JSONPath reads:

- `strict` makes path errors explicit and, importantly, avoids duplicate results that the default `lax` mode produces with `.**`.
- `$.structure[*]` is every top-level node.
- `.**` descends through all levels below it (children at any depth).
- `? (...)` filters the nodes; `@` is the current node.

Expected output: one row per section or article, in document order. To list every node type that exists in a document:

```sql
SELECT n->>'type' AS type, COUNT(*)
FROM documents,
     jsonb_path_query(legal_json, 'strict $.structure[*].** ? (exists(@.type))') AS n
WHERE id = :'doc_id'
GROUP BY 1 ORDER BY 2 DESC;
```

To search by text, marker or title instead of browsing, use `like_regex`:

```sql
SELECT n->>'id' AS node_id, n->>'marker' AS marker, n->>'title' AS title
FROM documents,
     jsonb_path_query(legal_json,
       'strict $.structure[*].** ? (@.title like_regex "<search term>" flag "i")') AS n
WHERE id = :'doc_id';
```

Replace `<search term>` with a word. Searching `@.text` works the same way. A search that matches nothing returns zero rows.

### Step 2: store the chosen ID and fetch the element

Copy a `node_id` from the result above:

```
\set node_id '<node-id>'
```

Fetch that node, including all its children, pretty-printed:

```sql
SELECT jsonb_pretty(
         jsonb_path_query_first(
           legal_json,
           'strict $.structure[*].** ? (@.id == $node_id)',
           jsonb_build_object('node_id', :'node_id')))
FROM documents WHERE id = :'doc_id';
```

- `jsonb_path_query_first` returns the first match (IDs are unique, so there is at most one).
- `$node_id` inside the path is a JSONPath variable; its value is passed by `jsonb_build_object('node_id', :'node_id')`. This keeps the path string constant and avoids quoting problems.

Expected: the node as pretty-printed JSON with its nested `children`. If the ID does not exist, the result is a single empty row.

### More element queries

Own text and marker of the node (children's text is *not* included; see [legal-json.md](legal-json.md)):

```sql
SELECT n->>'marker' AS marker, n->>'title' AS title, n->>'text' AS own_text
FROM documents,
     jsonb_path_query(legal_json, 'strict $.structure[*].** ? (@.id == $node_id)',
                      jsonb_build_object('node_id', :'node_id')) AS n
WHERE id = :'doc_id';
```

Direct children (for example the paragraphs of a section or article):

```sql
SELECT c->>'id' AS child_id, c->>'type' AS type, c->>'marker' AS marker,
       left(c->>'text', 80) AS text_start
FROM documents,
     jsonb_path_query(legal_json,
       'strict $.structure[*].** ? (@.id == $node_id).children[*]',
       jsonb_build_object('node_id', :'node_id')) AS c
WHERE id = :'doc_id';
```

Expected: one row per direct child; zero rows if the node has no `children`. In `strict` mode a node without `children` simply produces no result.

All descendants of the node, at any depth:

```sql
SELECT d->>'id' AS node_id, d->>'type' AS type, d->>'marker' AS marker
FROM documents,
     jsonb_path_query(legal_json,
       'strict $.structure[*].** ? (@.id == $node_id).children[*].**',
       jsonb_build_object('node_id', :'node_id')) AS d
WHERE id = :'doc_id' AND jsonb_typeof(d) = 'object' AND d ? 'id';
```

The last two conditions drop values that are not nodes (such as page-number arrays and text strings that `.**` also visits).

Check whether a node exists, without returning it (`@?` tests a path for any match):

```sql
SELECT legal_json @? '$.structure[*].** ? (@.id == "<node-id>")' AS node_exists
FROM documents WHERE id = :'doc_id';
```

This one embeds the ID in the path string, so replace `<node-id>` literally; in the interactive session the earlier variant with `$node_id` is more convenient.

### Inspect another document

Change `doc_id` (step "Select a document once") and, because node IDs depend on the document, repeat Step 1 to find a node of the new document.

### Run a query without an interactive session

For a one-off check from your normal terminal:

```bash
docker exec odos-postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT COUNT(*) FROM documents;"'
```

For anything with quotes or JSONPath, the interactive session is much easier.

## 8. Reading the Legal JSON through the API instead

The same JSON is available without SQL, which is useful for comparing with what the frontend shows (replace `<document-id>`):

```bash
curl -s http://127.0.0.1:8000/api/jobs/<document-id>
curl -s http://127.0.0.1:8000/api/jobs/<document-id>/files/document.json
```

The first call returns the job status, the second the `document.json` file from the backend storage volume. `documents.legal_json` and `document.json` are equal as data.

## 9. Everyday commands

| Task | Command | Data kept? |
|---|---|---|
| Status | `docker compose ps` | n/a |
| Logs | `docker compose logs -f backend` (or `postgres`, `frontend`) | n/a |
| Stop, keep containers | `docker compose stop` | Yes |
| Start again | `docker compose start` or `docker compose up -d` | Yes |
| Rebuild after code changes | `docker compose up -d --build` | Yes |
| Remove containers and network | `docker compose down` | Yes (volumes stay) |
| Remove containers **and volumes** | `docker compose down -v` | **No, deletes data** |

## 10. Data persistence, Docker volumes and safe restarts

Compose defines three named volumes:

| Volume | Holds |
|---|---|
| `postgres_data` | The PostgreSQL data: the `documents` table with `summary` and `legal_json` |
| `backend_storage` | Uploaded PDFs and generated result files (`document.json`, `document_model.json`, `docling_raw.json`, reports) |
| `model-cache` | Downloaded Docling models |

On disk their names get the Compose project name as prefix, for example `<project>_postgres_data`. List them with `docker volume ls`.

Persistence rules:

- **Safe:** `docker compose stop`, `docker compose restart`, `docker compose down`, `docker compose up -d --build`, restarting Docker Desktop or the computer. Volumes survive all of these. The `postgres` service uses `restart: unless-stopped`, so it comes back with Docker Desktop.
- **Backend restart:** the backend restores its jobs from PostgreSQL. A job that was still running during the restart is marked `failed`.
- **Do not run `docker compose down -v` (or `--volumes`).** It deletes all three volumes: every stored document, every uploaded PDF and result file and the model cache (which must then be downloaded again). The same applies to `docker volume rm <volume>`, `docker volume prune` and `docker system prune --volumes`.
- **The schema script runs only on an empty volume.** `backend/db/001_documents.sql` is executed by the PostgreSQL image on the first start only. An existing database is not touched.
- **Different checkout, different data.** The volume names depend on the Compose project name (normally the folder name). A second clone, or a renamed folder, starts with empty volumes. Because the PostgreSQL container has the fixed name `odos-postgres`, two checkouts cannot run at the same time.
- **Not shared.** Every developer has their own database. Nothing is synchronized between machines.
- **Deleting a document:** use the API (`curl -X DELETE http://127.0.0.1:8000/api/jobs/<document-id>`), not SQL. Deleting a row by hand leaves the PDF and result files in the storage volume.

## 11. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Cannot connect to the Docker daemon` / `docker: command not found` | Docker Desktop is not running or not installed. Start it, wait until it reports running, then retry. |
| `required variable POSTGRES_PASSWORD is missing a value: set POSTGRES_PASSWORD in .env` (same for `POSTGRES_USER`, `POSTGRES_DB`) | `.env` is missing, incomplete, or you are not in the folder containing `compose.yaml`/`.env`. Run `cp .env.example .env`, set the values, retry from the repository root. |
| `Error response from daemon: No such container: odos-postgres` | The stack is not running, or runs under another container name. Check `docker compose ps` and start it with `docker compose up -d`. |
| `pg_isready` prints `no response` or `rejecting connections` | PostgreSQL is still starting or crashed. Wait a few seconds; then `docker compose logs postgres`. |
| `psql: error: connection to server on socket ... failed: FATAL: database "..." does not exist` | You passed a wrong database name. Use the `sh -c '... "$POSTGRES_DB"'` form from this guide. |
| `psql: error: ... FATAL: password authentication failed for user "..."` (only when connecting from the host, or after editing `.env`) | The password in `.env` differs from the one the volume was created with. Restore the original value in `.env`. Do not delete the volume to "fix" it. |
| `Bind for 127.0.0.1:5433 failed: port is already allocated` | Another program uses port 5433 (or 8000, 5173 for the other services). Find it with `lsof -nP -iTCP:5433 -sTCP:LISTEN`, stop it, or change the left-hand host port in `compose.yaml`. |
| `zsh: command not found: psql` / `bash: psql: command not found` | You ran a `psql` command in your normal terminal. `psql` is installed inside the container, not necessarily on your machine. Start it with `docker exec -it odos-postgres sh -c 'psql ...'`. |
| `ERROR: syntax error at or near "\d"` or `\dt` is not recognized | `\dt`, `\d`, `\q`, `\set` only work inside a `psql` session, not in your shell and not as part of `-c` SQL. Open a session first (section 5). |
| `$POSTGRES_USER` is empty, `psql: error: ... role "" ...` | The variable was expanded by your host shell. Wrap the whole `psql` command in single quotes, as shown, so the container's shell expands it. |
| `\dt` shows `Did not find any relations` | The schema was not created. Apply it: `docker exec -i odos-postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1' < backend/db/001_documents.sql` (idempotent, safe to repeat). |
| `SELECT COUNT(*)` returns `0`, or the document list is empty | No document has been processed yet, or the stack was started in a different checkout/volume (section 10). Process a PDF in the frontend and check again. |
| The list shows rows, but `legal_json` is empty (`has_legal_json = f`) | The document is `queued`, `processing`, `failed` or `unsupported`. Only `completed` documents have a Legal JSON; check `status` and `message`. |
| `no rows returned for \gset` | There is no document matching your selection (for example no `completed` one). |
| Node queries return no rows | The `doc_id` or `node_id` variable is not set (check with `\echo :doc_id :node_id`), the ID belongs to another document, or the node has no `children`. Re-run Step 1 for the selected document. Node IDs are copied from the output, never guessed. |
| `ERROR: syntax error at or near ":"` in a query | The `:'name'` variable was not recognized, usually because it is inside `$$ ... $$` or an existing quoted string. Pass it as a JSONPath variable as shown in section 7. |
| Backend `unhealthy`, or the frontend does not start | The frontend waits for a healthy backend. See `docker compose logs backend`; the first start can take over a minute. |
| Backend upload answers `503 The ODOS database is not available` | PostgreSQL is not running or not healthy: `docker compose ps`, then `docker compose up -d`. |
| Stored documents are gone after a restart | Volumes were removed (`down -v`, `volume rm`/`prune`) or you are in a different checkout. Documents cannot be recovered; reprocess the PDFs. |

## 12. Limitations and future options

- PostgreSQL is a **local** instance per developer. There is no shared database, no hosted service and no backup.
- Possible later steps, **not implemented**: a hosted PostgreSQL service such as Neon for a shared team database, and a database client such as pgAdmin or Adminer. Until then, `psql` inside the container is the supported way to inspect data. ([database-poc.md](database-poc.md) mentions DBeaver as an optional local client; it is not part of ODOS either.)
- There is no document list in the frontend and no `GET /api/jobs` endpoint; use SQL to find document IDs.
- Stored Legal JSON reflects the parser's current quality. `json_schema_valid` and `parser_warnings` in `summary` tell you how much to trust a document; a value of `false` is a parser topic, not a database error.
