# Legal parsing

The parser converts Docling extraction into a canonical `DocumentModel`. German-law and EU profiles share one processing lifecycle, while each profile defines its own heading vocabulary, hierarchy and recognition rules.

## Entry point and profile selection

```python
from odos.parsing import parse_document

model = parse_document("output/law/docling_raw.json", "german_law")
```

`parse_document` takes an explicit profile. The CLI also requires an explicit mode for `process`. The web pipeline attempts the configured profiles and accepts a document only when exactly one recognizes its legal structure. This selection is based on document structure, not the uploaded filename.

The profiles were developed around German legislation and German-language EU legislation, including the MBO and Regulation (EU) 2023/1230. Recognition of a new document does not guarantee a correct parse; review warnings and representative passages.

## Processing stages

| Stage | Main responsibility |
|---|---|
| Read source | Load Docling items, text and page information |
| Load evidence | Read PDF text-layer evidence bound to the extraction |
| Preprocess | Handle repeated headers/footers, reading order, evidence-based text restoration and source segmentation; derive highlight geometry |
| Parse structure | Use the profile recognizer to create legal units and assign element IDs |
| Finalize structure | Move remaining page furniture out of the legal tree |
| Resolve footnotes | Associate reference marks with footnote content when supported by evidence |
| Segment sentences | Derive logical sentences as text ranges, including sentences spanning list items |
| Normalize TOC | Reconstruct logical table-of-contents entries and resolve supported targets |

Validation and public JSON export follow parsing. They inspect the finished model; they are not legal-rule interpretation.

## Modules

| Location under `backend/src/odos/` | Purpose |
|---|---|
| `normalization/docling_reader.py` | Docling items and source text |
| `normalization/reading_order.py` | PDF evidence and reading-order handling |
| `normalization/hygiene.py` | Preprocessing orchestration |
| `normalization/source_text.py` | Evidence-based restoration of text differences |
| `normalization/source_marks.py` | Superscript marks and their roles |
| `normalization/highlight.py` | PDF highlight geometry |
| `parsing/engine.py` | Shared lifecycle |
| `parsing/builder.py` | Element construction, IDs and hierarchy |
| `parsing/profiles/german_law/` | German legal recognition and mappings |
| `parsing/profiles/eu_legislation/` | EU legal recognition and mappings |
| `parsing/sentences.py`, `footnotes.py`, `toc.py` | Derived annotations and links |
| `parsing/accounting.py` | Content accounting and report writing |

## Text that runs over a page break

A page break is a layout event, never a legal boundary. Docling delivers the tail of a unit cut by the page end as a separate item on the next page. `parsing/continuation.py` holds the one rule both profiles apply when a recognizer meets such an unmarked item: it is appended to the element that was open at the end of the previous page (`StructureBuilder.extend`), so the element keeps its complete own text, every page that carries it (`pages: [9, 10]`), one source reference, provenance box and source span per piece, and exact highlight rectangles on each page. IDs are those of the element; no `txt-n` is allocated for the fragment, and genuine children (numbered items, letters) stay separate.

No single signal decides. The element must be text-bearing with no child yet and still the innermost open container; the item must start on a later page, carry no legal marker (Absatz, Nummer, Buchstabe, Satz number, heading, EU point), have intact segmentation and reading order, sit at the page head while the element ends at the page foot (box geometry), and the text must support it: the element is not closed (no sentence end, colon or semicolon; abbreviations like "Abs." do not close it) and the item starts in lowercase, or the element ends in an unfinished phrase (comma, hyphen, dangling article/preposition/conjunction) or a sentence-sized text without any end and the geometry confirms the page boundary. A footnote or bare number labelled as body text never hosts a continuation. Page-foot notes that Docling labelled as body text (the Docker run does this for the MBO: "1 nach Landesrecht") are recognised conservatively (a run of numbered short lines in the foot zone of one page, numbered consecutively, below the text) and skipped when looking for the open text: the continuation joins the text above them, and the notes stay separate elements (flag `page_foot_note_labelled_as_body_by_docling`) or page furniture, never part of a paragraph's text. They are not retyped to `footnote`: that needs Docling's `footnote` label or reference-mark evidence (`parsing/footnotes.py`). Merged elements carry the hygiene flag `page_break_continuation_merged_confirmed`; a line-end hyphen at the break is kept as printed (`page_break_line_end_hyphen_kept`). Items that look like continuations but fail a condition stay separate and flagged (`continuation_across_page_break_attached_to_previous_element`, `possible_continuation_of_previous_element`).

Running page numbers and headers that Docling labelled as body text are found by the hygiene layer (`furniture_labelled_as_body_by_docling`) and treated as furniture by both recognizers (`SourceItem.is_page_furniture`) before any structural decision, so they cannot stand between a text and its continuation. Docling's labels differ between machines (the Docker image renders non-embedded fonts with Liberation fonts; see `DOCKER.md`), so the structure must not depend on them.

## Preservation and uncertainty

Preserve source text and source references while adding structure. Merge fragments only where supported by the evidence above; retain ambiguous continuations and warnings.

Text-layer evidence can support repairs to hyphenation and typography. It does not justify paraphrasing. Keep Docling's raw output unchanged and record repair decisions in the model.

Unknown headings, ambiguous sentence boundaries and unresolved footnote/TOC links must remain visible in diagnostics. Review those diagnostics when judging a result.

## Extending a profile

Update its recognizer and declarations for hierarchy, public types, sentence units and TOC vocabulary. Preserve coherent IDs and source links. For a new profile, also register it and add the processing mode and output mappings.

Before claiming support, manually compare representative PDFs with the structure and JSON output, including lists, page breaks, tables, footnotes and annexes. Other languages and layouts need additional work; they are not supported merely because they use a similar legal hierarchy.
