# LLM input reduction and applicability views

The raw Docling JSON and original `document.json` stay unchanged. After Legal JSON creation, two deterministic parsers create separate, downloadable views. Neither parser calls an LLM or rewrites retained legal text. Rule extraction (CLI and API) sends V2; selecting `--element-id` applies **after** these filters. Selecting an excluded element fails before a model call.

| File | Purpose |
| --- | --- |
| `document.json` | Original, full Custom Legal JSON; source of truth |
| `llm_input_v1.json` | Reduced LLM input JSON V1 |
| `llm_applicability_input_v2.json` | LLM applicability input JSON V2; actual rule-extraction input |
| `llm_input_report.json` | Separate audit: removed root nodes/reasons, policy, original hash and size estimates |

## V1: reduction parser

Empties the top-level front matter and table of contents/entries. Drops typed preamble, preamble formula, recitals, recital introduction, preamble citations and enacting formula nodes. Metadata (title, document identity, version/dates), signatures/conclusions, definitions, annexes, tables, cross-reference wording, stable IDs, page numbers and retained text remain unchanged. On retained structure nodes, V1 now omits `germanType`/`nativeType` and a printed string `marker` when `type` and `number` are available. Sentence-marker objects and footnote markers stay. Null values, empty fields and `pageCount` are preserved. These are derived LLM views, not replacements for the full Legal JSON contract. It does not guess relevance from keywords or summarize technical annexes. Signatures are deliberately retained as requested.

Sentences wholly referring to retained elements remain with their original IDs and offsets. A sentence spanning a removed element is omitted from the sentence index, not shortened; retained node text stays. Footnotes exclusively anchored to removed nodes are omitted; mixed anchors/references are filtered. Unanchored footnotes are retained conservatively. Empty structural containers left by exclusions are pruned, without renumbering anything.

## V2: applicability parser

Source: `ODOS_LLM_Ausschlussliste_Deutsch_Aktualisiert(1).xlsx` supplied by the team. The executable policy is in `backend/src/odos/llm_input/applicability.py`.

| Document | Excluded whole provisions |
| --- | --- |
| EU Machinery Regulation 2023/1230 | Articles 12, 26–42, 44, 47–48, 50, 53 |
| Musterbauordnung (MBO) | §§ 24, 52, 54, 56–57, 65–65d, 69–71, 84; Anlage 1 |

MBO §§ 22–23, 25, 53, 55, 58, 68, 74–75, 77–80 and all other unlisted provisions remain in full. Rows marked partially keep are **not** partially deleted automatically: their technical evidence/context requirements remain. The EU annexes, including correspondence tables, stay intact. No additional applicability exclusions are inferred.

Policies match identified documents only (MBO ID plus title, or EU Regulation type plus ID/document number 2023/1230). An unrelated law gets the generic V1 reduction but no document-specific V2 exclusions. Future document versions and the Excel list should be reviewed together before extending the policy. This is a project-scope choice, not a declaration that an article has no legal relevance. Retained text may still reference an excluded article: references are not rewritten; consult the full original for that context.

## Frontend and persistence

Under Custom Legal JSON, two additional sections show the **full** V1/V2 JSON (expand “Show full JSON”) and separate Download buttons. They do not change with the original's selected-element toggle. The original and Rule JSON tabs and raw Docling view remain available. A reduction report download gives exact removals and character counts. Character/token estimates exclude the system prompt and response, and are not a model-tokenizer measurement.

Newly processed documents save all views in the existing job directory/volume, alongside `document.json`. Existing stored documents generate the derived views from their saved original when loaded; no PDF reprocessing is required. All views follow the original job's retention/deletion lifecycle. The database still stores the original Legal JSON; derived views are files, not replacement database records. No database migration or new Python dependency is needed.

## Run in Docker / Windows PowerShell

From the updated project root, with Docker Desktop running and your existing `.env` configured:

```powershell
docker compose up --build -d
```

Open http://localhost:5173, upload a document (or reopen a stored one), and select Custom Legal JSON. V1 and V2 appear underneath. No Bedrock key or model call is needed to generate or download these views. LLM extraction remains an explicitly triggered, paid operation.

## Run just the parsers on an existing Legal JSON

The module requires only Python's standard library when `backend/src` is on the Python path. From the project root in PowerShell:

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) "backend/src"
python -m odos.llm_input "C:/path/document.legal.json" --output-dir "C:/path/reduced-inputs"
```

The input file is never overwritten; the output folder receives V1, V2 and the report. The delivery ZIP also contains example exports for the two supplied documents, outside the project folder.

## Verification

Dependency-free parser regressions (from the project root):

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) "backend/src"
python -m unittest discover -s backend/tests -p test_llm_inputs.py -v
```

With the usual project dependencies installed, also run the backend suite and frontend checks:

```powershell
cd backend
python -m pytest -m "not slow" tests
cd ../frontend
npm ci
npm run typecheck
npm test
npm run build
```

No test should use a real AWS key. Parser tests check exact exclusion lists, original immutability, retained text, unknown-document fallback, sentence/footnote integrity and idempotence. Existing model-request and frontend loading tests were updated for V2 and the new artifacts.

Verification in the delivery environment: 11 parser tests and 3 offline model-payload/schema contract tests passed (14 total); both supplied documents were transformed and checked for original-byte preservation, exact expected exclusions, unchanged retained node fields except the explicitly omitted type labels and printed markers, no dangling sentence/footnote anchors and idempotence. The contract tests exercised the actual ODOS request preparation, output handling and schema/provenance code with canned model responses; missing boto3/botocore transport imports were stubbed for this offline run. No AWS call was made. Full pytest, TypeScript/Vitest and the Docker application were not run here: dependency downloads are blocked (pip unavailable packages / npm HTTP 403). Run the commands above locally before merging.
