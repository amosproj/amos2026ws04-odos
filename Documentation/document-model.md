# The canonical DocumentModel

`DocumentModel` (`backend/src/odos/document_model.py`, written as `document_model.json`) is the single
source of truth for a document. Everything else is a one-way serialization of it:

- `document.json` (Custom Legal JSON 1.1)
- the validation reports

Nothing reads those outputs back as input. The model keeps the internal diagnostics (warnings,
uncertainty, hygiene flags) that the public outputs leave out.

## Top level

| Field | Meaning |
|---|---|
| `model_version` | `"0.1"` |
| `profile` | the parser profile: `"eu_legislation"`; **absent = German law** (as stored historically; never rewritten) |
| `source` | the Docling file it was parsed from: filename, Docling version, `docling_json_sha256`, page count |
| `metadata` | values printed in the document, verbatim, plus `metadata_provenance` naming the elements they come from. Dates are ISO only where the text gives a complete date |
| `root_id` | `"doc"` |
| `elements` | the legal structure as a flat list in document order; `parent_id` / `children_ids` form the tree |
| `furniture` | page headers and footers (and repeated page decoration), outside the tree |
| `warnings` | problems the parser could not resolve: `code`, `severity`, `message`, `element_id` |
| `structure_notes` | valid exceptions the parser recognised and verified (not problems) |
| `sentences` | derived: sentences as text ranges over elements |
| `toc_entries` | derived: logical table-of-contents entries with their verified links |
| `review` | reserved for an effective (corrected) model; the prototype has no correction step, so it stays empty |

## Element IDs

IDs are stable paths built from the printed numbering:

- German: `doc/teil-1/kapitel-1/par-1/abs-1/nr-2/lit-a`
- EU: `doc/chp-2/sec-1/art-3/para-2`

Further rules:

- **Repeated or restarted numbering** gets a suffix (`~2`) or a run prefix (`run2-nr-1`).
- **Only the profile's recognizer assigns IDs**; later lifecycle stages never renumber.
- **Sentences, TOC links, footnote anchors and the exports' element IDs all refer to these IDs.**
  Changing an ID scheme is therefore a breaking change.

## Elements

| Group | Fields |
|---|---|
| Structure | `id`, `type` (below), `region` (`document`, `front`, `toc`, `preamble`, `body`, `conclusions`, `annex`, `furniture`), `parent_id`, `children_ids` |
| Printed parts | `number` (as printed, e.g. `"22a"`, `"IX"`), `marker` (`"§ 1"`, `"(2)"`, `"a)"`), `title` (headings) |
| Text | `original_text` (the source text: Docling's `orig` plus the characters restored from the PDF text layer), `content_text` (without the structural marker), `docling_text` (Docling's own text, when it differs), `text_repairs` (every restored character with its rule and evidence), `search_text` (normalised, for search) |
| Tables | `table`: rows of cell texts, plus cell boxes where Docling gives them |
| Provenance | `source_refs` (Docling item refs), `pages`, `provenance` (page, box, character span), `source_spans` (the slice of a Docling item a split element covers), `highlight_boxes` (exact per-line rectangles proven from the PDF glyphs; empty = use `provenance`) |
| Footnotes | `anchor_id` (the single anchor), `anchor_ids` (all anchors), `footnote_refs` (each reference mark with page, box and evidence) |
| Diagnostics | `uncertain`, `uncertainty_reasons`, `hygiene_flags`, `docling_label` |
| Review | `reviewed`: reserved for corrected elements (corrected fields with their original values); empty in this prototype |

**Coordinates.** Boxes are in PDF points with `coord_origin: "BOTTOMLEFT"`. The frontend converts them
for display (`frontend/src/structure.ts`, `bboxToRect`).

**Element types:**

- **German law:** `teil`, `kapitel`, `abschnitt`, `unterabschnitt`, `paragraph` (§), `absatz`, `nummer`,
  `buchstabe`, `doppelbuchstabe`, `anlage`, `unmarked_list_item`
- **EU legislation:** `doc_title`, `preamble`, `preamble_formula`, `citation`, `recitals_intro`,
  `recital`, `enacting_formula`, `chapter`, `section`, `article`, `article_paragraph`, `numbered_point`,
  `point`, `subpoint`, `annex`, `annex_part`, `annex_heading`, `conclusions`, `final_formula`,
  `signature`
- **Shared:** `document`, `front_matter`, `toc`, `toc_entry`, `text`, `table`, `footnote`,
  `footnote_heading`, `unrecognized`, `picture`, `page_header`, `page_footer`, `sentence`

## Derived annotations

These never change an element, ID or text.

- **`sentences`:** `id` (`<unit>/s<n>`), `unit_id`, and `ranges` of `[start, end)` code-point offsets
  into the elements' `content_text`. Each range records the SHA-256 of the text it was computed on.
  `method` is `printed_number` (verified against the PDF's superscript Satz numbers) or `punctuation`.
- **`toc_entries`:** one entry per printed TOC line, with:
  - `source_spans` into the raw TOC items
  - `status`: `linked` only when kind, number, title and enclosing headings agree; otherwise
    `candidate`, `unmatched` or `ambiguous`
  - `target_id` for a linked entry

## Compatibility rules

- New fields are optional and left out when empty (`exclude_if`). Stored models stay valid.
- Fields are never renamed or given a new meaning. `profile` keeps its stored values.
- Moving the module (Phase 4: `normalization/model.py` → `document_model.py`) changes no JSON. The
  golden baselines (`backend/tests/golden/`) pin every output before and after each change.
