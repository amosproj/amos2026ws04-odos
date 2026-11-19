# Legal and technical-standard parsing

The parser converts Docling extraction into a canonical `DocumentModel`. The German-law, EU-legislation and technical-standard profiles share one processing lifecycle, while each profile defines its own heading vocabulary, hierarchy and recognition rules.

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
| `parsing/profiles/technical_standard/` | Technical-standard recognition (DIN, DIN EN, DIN ISO, DIN EN ISO, DIN VDE, DIN SPEC, ISO, IEC, EN) |
| `parsing/sentences.py`, `footnotes.py`, `toc.py` | Derived annotations and links |
| `parsing/accounting.py` | Content accounting and report writing |

## Technical-standard parser (`technical_standard`)

A generic structural parser for the layout shared by DIN, DIN EN, DIN ISO, DIN EN ISO, DIN VDE, DIN SPEC and standalone ISO / IEC / EN standards. It extracts structure only; the technical meaning is not interpreted. Run it with `odos process <pdf> -o <dir> --mode technical_standard`.

| Structure | How it is recognised |
|---|---|
| Title block, issue | `DIN EN ISO 12100`, `DIN VDE 0100-200:2023-06`, `ISO 9001:2015` ...; an issue printed as a running cover header ("März 2011") becomes `version.date` |
| Cover of an adopted EN/ISO text | a second title block (`EUROPÄISCHE NORM`, `EN ISO 12100`) is front matter with its own `standardTitle` |
| Forewords, introduction | `Nationales Vorwort`, `Vorwort`, `Foreword`, `Einleitung`, `Introduction`; unnumbered sub-headings inside are kept as text and flagged |
| Table of contents | `Inhalt`/`Contents` becomes `tableOfContents`; entries are rebuilt and linked to clauses (dot leaders and page numbers are not part of the title) |
| Clauses | hierarchy follows the printed number: `1` > `1.1` > `1.1.1`; annex clauses `A.1` > `A.1.1` |
| Definitions | in the terms-and-definitions clause a numbered entry with a term is a `definition`. `3.1` and its term may be two headers. An entry with numbered entries below it is a group heading (`clause`) |
| Notes, examples | `ANMERKUNG [n]`, `NOTE [n]`, `BEISPIEL`, `EXAMPLE` (capitals only, so running prose never matches) |
| Figures, tables | captions `Bild N - ...`, `Tabelle N - ...`, `Tabelle N (fortgesetzt)`; a caption Docling nests under its picture/table joins it. A table on the page after a table with the same column count carries `table_continues:<id>` |
| Annexes | `Anhang A (informativ)` on one or several lines, `Nationaler Anhang NA`; `classification` is `normative`/`informative`. A national annex holds its own bibliography |
| Bibliographies, footnotes, lists, formulas | `Literaturhinweise`/`Bibliography`; Docling footnotes; `—`, `⎯`, `a)`, `1)`, `ii)` items; numbered formulas |

Reading order and page breaks: a zone heading whose box lies entirely above every earlier item of its page is moved before them (flag `reading_order_repaired_heading_moved_before_lower_page_items`); unmarked text that runs over a page break joins its element through the shared continuation rule. Nothing is invented: unnumbered headings, definitions Docling split mid-sentence and entries whose start is not recognised stay as flagged text.

Docling keeps captions only as children of their table or picture. `read_docling_json(path, include_nested=True)` reads them; the German and EU profiles do not (`LegalProfile.read_nested_items`), so their output is unchanged.

**Automatic recognition.** An upload runs every profile and accepts the document only when exactly one finds its structure. A technical standard needs numbered clauses **and** either a standard identifier or the Scope / Normative-references clauses of the ISO/IEC drafting rules; numbered clauses alone (a manual, a contract) are refused. An excerpt that holds only an identified standard's table of contents is accepted (structure empty, `tableOfContents` filled). The identifier is read from the title line (`DIN EN ISO 12100:2011-03`, `DIN SPEC 91345:2016-04 (D)`, `ETSI EN 303 645 V2.1.1 (2020-06)`, `DIN VDE 0100-200 (VDE 0100-200):2023-06`, `ISO/IEC 27000:2018(E)`), or from the most frequent running header when the cover has none; the edition from `März 2011` / `Edition 2.0 2010-04`.

**Also handled:** nested lists by indentation (`⎯` > `1)` > `a)` > `ii)`), numbered paragraphs without title (`6.4.1.1 Das Abfassen ...`, kept only when the number continues the open clause), introduction numbering `0.1`, bilingual PDFs (the second language restarts at `1` and is flagged `numbering_restarts_second_part`), a cover table or logo as front matter, `table_continues:<id>` links across pages.

**Also handled (from standards inspected in the VDE NormenBibliothek viewer):** IEV-style terminology (`826-11-01`) as definitions under `HAUPTABSCHNITT 826-11 – …` divisions, with the English and French headings of a division kept beside it (`parallel_language_heading`) and `[IEV …]` source lines flagged; part-prefixed numbering without `1 Scope` (`410`, `410.1`, `411.3.2.1`); a paragraph number alone on its line (`411.3.2.5`); forewords to amendments (`Europäisches Vorwort zur Änderung A11`); `Stichwortverzeichnisse` as an `index` unit; identifiers such as `DIN VDE 0833-4 (VDE 0833-4) Berichtigung 1:2026-12`, `DIN CLC/TS 50711 (VDE V 0115-711)`, `VDE-AR-N 4105 (VDE-AR-N 4105) Anwendungsregel:2026-03`, `DIN EN ISO 9001:2015-11 (D/E)`. A contents list that Docling puts in one table (heading inside the table) is recognised by its dot-leader rows.

**Document variants.** Drafts (`E DIN …`, trailing `Entwurf`), amendments (`/A1`, `/AA`, glued `…443A3`), corrigenda (`Berichtigung 1`, `Ber1 zur Anwendungsregel`), supplements (`Beiblatt 2`) and pre-standards (`DIN VDE V …`) carry the base standard's number, so the variant is recorded in `metadata.document_variant` and becomes part of the document id and `shortTitle` (`din-vde-0100-520-beiblatt-1`, not the id of the base standard). An identified document is accepted even without clauses when it has a foreword, annex, bibliography, table or contents list, because corrigenda, amendment drafts and supplements often consist of nothing else. An amendment's instruction lines (`Ändere Abschnitt 443.6.2 … wie folgt:`) and quoted old/new text stay text: a number only becomes a clause when it continues the open clause's numbering.

**Language editions.** A language mark printed with the identifier, or in a running header that carries the same number (`(D)`, `(E)`, `(F)`, `(D/E)`, `(D/E/F)`) is the language edition of that file: it goes into `metadata.language`, the exported `language` and the document id (`din-spec-91345-de` vs `din-spec-91345-en`). Without a mark the id is unchanged and the exported `language` is read from the document's own unit headings (Vorwort / Foreword / Avant-propos, Scope / Anwendungsbereich ...; at least two per language; both languages are listed for a bilingual file, e.g. `en,fr`).

**Bilingual parallel columns.** A bilingual edition (`Deutsche und Englische Fassung`, e.g. DIN EN ISO 9001) sets German and English side by side. A column-aware reading order alternates them page by page, which cuts both hierarchies in half. When consecutive pages have at least three items in each column and a heading stands in both (the same clause number, or `Vorwort`/`Foreword`), the run is reordered into two complete editions (the whole left column, then the whole right column). Every item keeps its page and gets the flag `parallel_edition:1` or `:2`, and the second edition's top-level clauses carry `numbering_restarts_second_part`. Without a repeated heading the reading order is left alone. Newer DIN covers print the issue as a bare `2020-01`; that is read as the issue too.

**Amendments.** Instruction lines (`Ändere Abschnitt 443.6.2 … wie folgt:`, `Replace Clause 5.1.1 as follows:`) end the foreword or front matter. They and the text after them are top-level `text` units flagged `amendment_instruction` / `amendment_base_title`; no clause or other hierarchy is invented. The foreword keeps what belongs to it (its text, the comment table, the list of changes). An instruction inside an open clause stays where it is printed and is only flagged. Identifiers such as `EN ISO 9001:2015/A1:2024` and `ISO 9001:2015/Amd 1:2024` carry the amendment as the variant.

**Verification status.**

| Family / document | Evidence |
|---|---|
| DIN EN ISO 12100:2011-03 | complete real PDF (98 pp), checked against its contents list and text layer |
| ETSI EN 303 645 V2.1.1 | complete real PDF (34 pp, free from etsi.org) |
| IEC 61508-1 ed. 2.0, ISO/IEC 27000:2018 | official preview PDFs (VDE Verlag) |
| DIN SPEC 91345; DIN EN ISO 9001, DIN ISO 31000, DIN EN 619, DIN EN ISO/IEC 27001, DIN ISO/IEC 27001, ISO/IEC 27001 | official table-of-contents PDFs (din.de / DIN Media) |
| DIN VDE 0100-200:2023-06, 0100-410:2018-10, 0100-100:2009-06, VDE-AR-N 4105:2026-03; DIN VDE 0100-443/A3 (draft amendment), 0100-560 Berichtigung 1, VDE 0100 Beiblatt 2, DIN VDE 0100-420 (draft), DIN VDE V 0100-551-2, DIN EN IEC 61439-1 | browser view (VDE NormenBibliothek): contents list, front matter and markup of sample sections; no PDF was parsed |
| DIN, DIN ISO, ISO | synthetic fixtures built from documented conventions |

Contents tables: a cell that holds two numbers (`7.4 7.5`) becomes two entries, and a row that prints two languages side by side (the number repeated in the middle of the row) becomes two entries with clean titles. Rows without a number (`Vorwort | … | Foreword`) stay one entry.

Limits that come from the extraction, not the parser: Docling's table model sometimes fuses two PDF rows and drops one title (the text is in the PDF text layer but not in Docling's output), shifts a page number into the number column, or splits one annex title over several rows. The parser keeps what Docling delivers and does not invent the rest. Not supported: tables or figures that Docling reports as neither table nor picture.

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
