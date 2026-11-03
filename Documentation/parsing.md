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

## Preservation and uncertainty

Preserve source text and source references while adding structure. A page break does not necessarily end a legal unit. Merge fragments only where supported by the recognizer's conditions and evidence; retain ambiguous continuations and warnings.

Text-layer evidence can support repairs to hyphenation and typography. It does not justify paraphrasing. Keep Docling's raw output unchanged and record repair decisions in the model.

Unknown headings, ambiguous sentence boundaries and unresolved footnote/TOC links must remain visible in diagnostics. Review those diagnostics when judging a result.

## Extending a profile

Update its recognizer and declarations for hierarchy, public types, sentence units and TOC vocabulary. Preserve coherent IDs and source links. For a new profile, also register it and add the processing mode and output mappings.

Before claiming support, manually compare representative PDFs with the structure and JSON output, including lists, page breaks, tables, footnotes and annexes. Other languages and layouts need additional work; they are not supported merely because they use a similar legal hierarchy.
