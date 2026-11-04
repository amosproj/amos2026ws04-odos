# Internal DocumentModel

`backend/src/odos/document_model.py` defines the canonical internal representation, written as `document_model.json`. The public Legal JSON and validation reports are derived from it. The frontend uses its source information to highlight the PDF.

## Main fields

| Field | Meaning |
|---|---|
| `model_version` | Internal representation version |
| `profile` | Parser profile; historically absent for German law and `eu_legislation` for EU legislation |
| `source` | File/extraction identity, versions, hash and page count |
| `metadata` | Recognized title, dates and document identifiers |
| `root_id` | Root element ID, normally `doc` |
| `elements` | Flat list of legal elements in document order |
| `furniture` | Page headers, footers and repeated page decoration outside the legal tree |
| `warnings` | Parser issues and unresolved cases |
| `structure_notes` | Recognized structural exceptions |
| `sentences` | Logical sentences represented by text ranges |
| `toc_entries` | Logical table-of-contents entries and their links |

## Elements and hierarchy

Each element has `id`, `type`, `region`, `parent_id` and `children_ids`. Parent/child references form the tree used by the frontend. Examples of IDs are `doc/teil-1/par-1/abs-1` and `doc/chp-2/art-10/para-1`.

Number-based IDs are useful within a document, but are not global document-revision identifiers. Consumers referencing an element across processing runs should also retain document/revision identity.

| Field group | Fields and purpose |
|---|---|
| Printed structure | `marker`, `number`, `title` |
| Text | `original_text`, `content_text`, optional `docling_text`, `search_text`, `text_repairs` |
| Tables | `table`, including rows and available cell-source information |
| Sources | `source_refs`, `pages`, `provenance`, `source_spans` |
| Highlighting | `highlight_boxes`; approximate source boxes can be used when exact boxes are unavailable |
| Footnotes | `anchor_id`, `anchor_ids`, `footnote_refs` |
| Diagnostics | `uncertain`, `uncertainty_reasons`, `hygiene_flags` |

`original_text` can contain evidence-based restorations from the PDF text layer. It is not necessarily byte-identical to Docling's extracted text. Differences and repair decisions are retained; `docling_raw.json` remains unchanged.

Coordinates are PDF points with a bottom-left origin. Display conversion is implemented in `frontend/src/structure.ts`.

## Sentences and table of contents

Sentences reference `[start, end)` ranges in element `content_text`, using Unicode code-point indices. Text hashes help detect stale ranges. A sentence may span several nodes, including list items. Printed sentence numbers and punctuation-based segmentation are distinguished in the model.

TOC entries contain source ranges, candidate/confirmed targets and status. Unresolved links are retained as diagnostics rather than guessed. These entries are separate from the legal body.

## Change discipline

Keep IDs and source relationships consistent when changing the parser. Renaming an internal field requires updating Python consumers and any frontend types that read it. Public JSON field changes are handled separately in `legal_json/view.py`; see [legal-json.md](legal-json.md).

The prototype has no correction interface. Reserved review fields do not imply an implemented review workflow.
