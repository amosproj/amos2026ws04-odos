# Custom Legal JSON 2.0

`document.json` is the public legal-content representation. Both German-law and EU profiles use the schema at:

`backend/schemas/odos-legal-json/2.0/legal-document.schema.json`

The schema uses JSON Schema Draft 2020-12 and is generated from the Pydantic classes in `backend/src/odos/legal_json/view.py`. `exporter.py` maps the internal model to these classes; `artifacts.py` writes the JSON and its validation report.

## Difference from Docling and the internal model

| File | Purpose |
|---|---|
| `docling_raw.json` | Original Docling extraction: layout elements, text, tables, pages and provenance |
| `document_model.json` | Legal hierarchy plus source links, coordinates and diagnostics |
| `document.json` | Legal content and structure in the public schema |

Version 2.0 keeps technical provenance in the internal model. Fields such as `sourceSpans` and bounding boxes from earlier public formats are not part of this output. Link public nodes to model elements by their shared IDs.

## Document and nodes

Top-level fields include schema/document identity, title, legal system, language, version information, page count, front matter, table of contents, structure, footnotes, sentences and logical TOC entries. Optional fields may be omitted when unavailable; the schema is authoritative for required fields.

| Node field | Meaning |
|---|---|
| `id` | Matching internal element ID |
| `type` | Public structural category |
| `germanType` | Source-language legal term, such as `Absatz` |
| `marker` | Label as printed, such as `(5)` |
| `number` | Identifier without surrounding label punctuation |
| `title` | Heading, where present |
| `text` | Own content without structural marker, title or children's content |
| `pages` | PDF page numbers |
| `children` | Nested legal nodes |

Tables additionally contain dimensions and rows. Parent nodes do not repeat all descendant text. An element's text may span several pages.

## German and EU conventions

| Unit | German-law `type` | EU `type` |
|---|---|---|
| Main provision | `section` for a German paragraph sign | `article` |
| Absatz | `subsection` | `paragraph` |
| Numbered list | `number` | `point` |
| Lettered list | `letter` | `point` |
| Annex | `annex` | `annex` |

An EU `section` denotes an Abschnitt, not a German paragraph sign. Interpret categories with `legalSystem`, `germanType` and the profile nesting rules. The current profiles process German-language text.

## Sentences, footnotes and sources

The `sentences` collection identifies logical sentences using ordered ranges into node text, rather than duplicating text. Offsets are Unicode code points, start inclusive and end exclusive. In JavaScript, ordinary string indices use UTF-16 code units; convert deliberately when applying these ranges.

Footnotes preserve their content and source-supported element anchors. Logical TOC entries can link to confirmed body nodes. The full technical evidence, uncertain cases and PDF coordinates remain in the internal model.

## Validation

Processing writes `legal_json_validation_report.json`, including schema checks, legal nesting/reference checks, comparison with the canonical model and source-fidelity information. Inspect the individual results: conformity with a schema or equality with a model does not prove that every PDF passage was interpreted correctly.

Schema validation is runtime application logic and remains even when automated development tests are removed. It is not a building-compliance check.

## Changing fields

1. Change the public definitions in `view.py`.
2. Update `exporter.py`, validators and frontend consumers where necessary.
3. Regenerate the published schema, for example from `backend` in PowerShell:

```powershell
.\.venv\Scripts\python.exe -c "import json; from pathlib import Path; from odos.legal_json.view import json_schema; Path('schemas/odos-legal-json/2.0/legal-document.schema.json').write_text(json.dumps(json_schema(), indent=2, ensure_ascii=False) + chr(10), encoding='utf-8')"
```

4. Reprocess documents and review the output and validation report.

Changing the schema file alone does not change exported JSON. Coordinate breaking changes and versioning with consumers. Future rule extraction should preserve source and revision references; executable rule interpretation is not implemented here.
