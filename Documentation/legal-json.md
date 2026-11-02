# document.json – public JSON of a legal document

Schema: `backend/schemas/odos-legal-json/1.1/legal-document.schema.json` (JSON Schema 2020-12). It is
generated from the Pydantic classes in `backend/src/odos/legal_json/view.py`; a test fails when the two drift.

The demo's JSON preview (`*.legal-view.json`, `frontend/README.md`) is a simplified presentation derived from this
file, without source spans, boxes and character offsets. It is not a document of this schema.

## Versions

- **1.0** (`backend/schemas/odos-legal-json/1.0/`) is frozen. The file is never regenerated, and a test pins
  its hash.
- **1.1** adds optional fields only. Every 1.0 field keeps its meaning:
  - `sentences`
  - `tableOfContentsEntries`
  - `Footnote.anchorElementIds` and `Footnote.references`
  - `TableCell.source`
- **Downgrade:** `downgrade_to_1_0` removes the additions. The validation report checks that the
  result is valid against the 1.0 schema (`downgrade_to_1_0_valid`).
- **`anchorElementId` (1.0 meaning, unchanged):** the single anchor, or `null` when there is none or
  more than one. `anchorElementIds` lists them all.
- **Information loss (`downgrade_to_1_0_information_loss`):** the report states what a 1.0 consumer
  does not get. For each 1.1 field, it gives how many values `downgrade_to_1_0` drops and the first
  JSON paths. It also lists the footnotes whose several anchors 1.0 can only give as
  `anchorElementId = null`. This is informational and never affects `valid`.
- **One default:** 1.1 is the only format ODOS writes (`document.json`, for every profile). There is
  no 1.0 output option. A 1.0 consumer applies `odos.legal_json.view.downgrade_to_1_0`, which every
  report validates against the frozen 1.0 schema.
- **Legacy code:** everything 1.0 (the downgrade and the information-loss report) is in
  `odos/legal_json/legacy.py`. `odos.legal_json.view.downgrade_to_1_0` stays as the documented import
  path for 1.0 consumers.
- **Deprecation status:** 1.0 is legacy and frozen.
  - Every `document.json` the pipeline writes is 1.1.
  - Nothing in ODOS reads or writes 1.0 except the downgrade check in the report.
  - Next step: once it is confirmed that no external consumer still needs 1.0 exports, stop computing the
    downgrade in the report. That changes the report, so it needs its own approval.
  - The frozen 1.0 schema file stays in the repository, to validate old exports.

## One canonical model

`DocumentModel` (`document_model.json`) is the single source of truth. `document.json` is its
one-way, deterministic serialization (`odos.legal_json.exporter.to_legal_json`). Nothing reads
`document.json` back. `legal_json_validation_report.json` records the `model_sha256` it came from.

`document_model.json` keeps the internal diagnostics (uncertainty, warnings, hygiene flags). None of
them appear in `document.json`.

## Top level

| Field | Content |
|---|---|
| `id` | slug of the document type and number (EU) or the short title (German); otherwise `doc-<sha>` |
| `documentType` | `de_legislation`, `eu_regulation`, `eu_directive`, `eu_decision`, `eu_legislation` |
| `legalSystem` | `de` or `eu`: which tradition the shared English type names come from |
| `language` | `de`, from the parser rule set (both rule sets match German-language legislation only) |
| `version` | `statement` verbatim, `date` only as printed (e.g. `2002-11`) |
| `publicationDate`, `adoptionDate`, `enactmentDate` | ISO dates, only when the document prints a complete date |
| `pages` | page sizes from the Docling output |
| `frontMatter`, `tableOfContents` | title page and table of contents, outside the legal structure |
| `structure` | the legal body in document order (preamble, parts … sections, conclusions, annexes) |
| `footnotes` | all footnotes; `anchorElementId` is `null` unless the source evidence establishes it |

Page headers and footers are not exported. The report counts them as excluded source items.

## Nodes

`id` is the internal element id (stable, unique). `marker` is verbatim, `markerStyle` its numbering
system, `number` the normalized number. `title` is set for headings; `text` is the element's own
text without marker, title or children. A parent never repeats its children's text.

| Internal | `de` type | Internal | `eu` type |
|---|---|---|---|
| Teil / Kapitel / Abschnitt / Unterabschnitt | part / chapter / division / subdivision | KAPITEL / ABSCHNITT | chapter / section |
| § (Paragraph) | section | Artikel | article |
| Absatz | subsection | Absatz "(1)" | paragraph |
| Satz | sentence | Nummer "1." / Buchstabe "a)" | point |
| Nummer | number | Ziffer "i)" | subpoint |
| Buchstabe / Doppelbuchstabe | letter | Erwägungsgrund / Bezugsvermerk | recital / citation |
| Anlage | annex | ANHANG / TEIL / "1.2.4.1." | annex / part / heading |

A German `section` (§) and an EU `section` (ABSCHNITT) are different units; `legalSystem`,
`nativeType` and the nesting rules keep them apart. `sentence` is part of the schema and the model
(`ElementType.SENTENCE`); no parser splits sentences yet, so none are emitted.

## Coordinates

PDF user space in points, origin bottom-left (`top > bottom`), exactly as Docling reports them. For a
top-left viewer: `y = pageHeight - top` (as `frontend/src/structure.ts` `bboxToRect` does). A span's box
covers the whole source item (`bboxScope: "source_item"`); `charStart`/`charEnd` locate the
element's characters in that item when known. Missing boxes or offsets are omitted, never estimated.

## Source text: what the PDF prints

Docling's page assembly drops every hyphen at a line end between two words (`Gewerbe-|und` becomes
`Gewerbeund`) and turns `„ “ ” – —` into ASCII. When the PDF is available, the pipeline records the PDF
text layer inside every item's box in `pdf_text_lines.json`. `backend/src/odos/normalization/source_text.py`
then restores what is printed, and only where the two texts differ by exactly those normalizations:

- Typographic characters are taken from the PDF.
- A line-end hyphen is kept before `und`, `oder`, `bzw.` or `sowie` (`Gewerbe- und`), before a
  capital letter (`CE-Zeichen`) and before punctuation (`Sport-,`).
- Otherwise the same document decides: if the hyphenated form is printed mid-line elsewhere, the
  hyphen is kept; if only the joined form appears, Docling's join stands (`Brandschutznachweisen`).
- Without evidence, the printed hyphen is kept and the element is flagged for review
  (`source_text_uncertain:…`, warning `LINE_END_HYPHEN_UNRESOLVED`).

The canonical model keeps the restored text in `original_text` and `content_text`. Docling's own text
stays in `docling_text`, and every decision is recorded in `text_repairs` with its rule and evidence.
`docling_raw.json` is never modified. Undoing the repairs gives back Docling's text exactly; the
validation reports check this. Without the PDF, nothing is restored.

## Footnote anchors

The anchor is set only when the source evidence supports it:

- **Proven anchor:** an `anchor_id` in the canonical model, proven from the PDF
  (`backend/src/odos/parsing/footnotes.py`). A page footnote's superscript reference mark lies in exactly
  one element. On that page, the superscript references (not Satz numbers, which are glued to the next
  word) must be exactly the page's footnote marks, each once and in order. A "*" note in the front
  matter is anchored to the one line that ends with the same "*".
- **"Fußnote" block:** printed directly after its anchor's content.
- **EU page footnote "( n )":** the anchor's text contains "( n )" on a page they share.

Otherwise the anchor is `null`. In the MBO, 21 footnotes are proven. The other 15 stay `null` because
their page shows extra candidates, or because one "*)" note is referenced several times.

## Page furniture

Page numbers and headers that Docling labelled as body text (repeated in the page margin band) are
moved out of the structure into `furniture`. They keep their ids, and later ids are not renumbered.

## Validation

`legal_json_validation_report.json` holds three checks:

1. JSON Schema.
2. Structural rules (`backend/src/odos/legal_json/nesting.py`): allowed parents per unit and legal system,
   unique ids, and anchors that resolve.
3. Text preservation against the model: every element exactly once, in document order, with the
   model's marker, title and text, and every Docling item accounted for. **This proves equality with
   the canonical model only, not fidelity to the PDF.**
4. Source fidelity (`source_fidelity`): each element's text against the PDF text layer inside its
   source boxes. Every difference must be explained by a recorded word-division decision; anything else
   is listed under `unexplained_differences`. Tables, pictures and page furniture are not compared.
   Without a text layer (or without the PDF) the report says the text is not verified.

Akoma Ntoso XSD validation is separate and unchanged.

CLI: `odos legal-json output/mbo/document_model.json`

## Sentences (1.1)

A sentence is a logical object with ordered text ranges. It may span several nodes: an Absatz, its
list items and the text after the list. Text is never repeated; consumers read it from the referenced
nodes.

- **Offsets:** `start`/`end` are Python `str` indices (Unicode code points) into the referenced node's
  `text` in the same `document.json`, half-open `[start, end)`.
- **Hashes:** `textSha256` is the SHA-256 (UTF-8) of that `text`. It detects a range used against
  another revision.
- **Printed numbers:** `number` is set only when the PDF prints the Satz number as a superscript;
  `marker` and `numberSource` locate it. Numbers are never derived from position.
- **Unnumbered sentences** come from punctuation. A boundary is never accepted after legal
  abbreviations, dates or ordinals. A unit with an undecidable boundary is not split and gets the
  warning `SENTENCE_SEGMENTATION_UNRESOLVED` (internal).
- **IDs:** `<unit>/satz-<n>` (printed) and `<unit>/s<k>` (unnumbered).
- **Stability:** numbered IDs follow the printed number; unnumbered IDs are only stable for an unchanged
  text hash.

## Footnote references (1.1)

- **Classifying marks:** each superscript is classified once, by
  `backend/src/odos/normalization/source_marks.py`, from PDF geometry:
  - Satz number (glued to the following word)
  - attached or spaced reference
  - exponent (`m2`)
  - ambiguous
- **Anchoring:** a footnote is anchored to every element that holds one of its reference marks. The
  page's references must not compete with an unclear mark, and they must come in footnote order.
- **Previous page:** a reference may also stand on the previous page, when it is the only unclaimed one.
- **Coordinates:** `references[].bbox` is the mark's own glyph box.
- **Unresolved:** an unresolved footnote keeps `page_footnote_anchor_unknown` and gets
  `FOOTNOTE_REFERENCE_UNRESOLVED`. A reference with no footnote gets
  `FOOTNOTE_REFERENCE_WITHOUT_FOOTNOTE`.

## Table-of-contents entries (1.1)

`tableOfContents` keeps the raw TOC nodes unchanged. `tableOfContentsEntries` lists one logical entry
per printed line (`backend/src/odos/parsing/toc.py`):

- **Boundaries:** cells and items are cut at their PDF lines, cells on the same visual line are
  joined, and entries follow the printed order.
- **Characters** come from the canonical text, and `sourceSpans` points into the raw nodes or cells.
- **`targetElementId`** is published only for a confirmed link: kind, number, title (letter spacing,
  whitespace and case ignored) and the enclosing Teil/Kapitel/Abschnitt all agree. A number-only
  match stays an internal candidate for review (`TOC_ENTRY_UNRESOLVED`).
- **Not legal text:** TOC entries are never part of `structure` or `sentences`.
