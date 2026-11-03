# Parsing: one engine, declarative legal profiles

ODOS turns a PDF into one canonical `DocumentModel` (`document_model.json`, see
[document-model.md](document-model.md)). The public output (`document.json`, Custom Legal JSON) is
derived from that model.

German law and EU legislation are parsed by the **same lifecycle** (`backend/src/odos/parsing/engine.py`).
The genuine legal differences live in **profiles** (`backend/src/odos/parsing/profiles/<name>/`): a
declaration of tables and small hooks, plus the profile's recognizer, rules and validation report.

> **Scope.** Two profiles are verified, each on specific documents: German law on the MBO,
> and EU legislation on Regulation (EU) 2023/1230, a German-language Official Journal regulation. A
> synthetic EU regulation (`backend/tests/synthetic_eu.py`) and a synthetic German law
> (`backend/tests/synthetic_german.py`, with a generated PDF) cover both profiles when the partner documents
> are not available.
>
> Sharing one engine does **not** make other documents supported. Each new kind of document needs its
> own verification first (see the end of this page).

## Entry point

```python
from odos.parsing import parse_document

model = parse_document("output/doc/docling_raw.json", "german_law")   # or "eu_legislation"
```

`parse_document(path, mode)` is the one public entry point. It is used by the CLI
(`odos normalize --mode …`), the pipeline (through `engine.parse`) and the tests. An unknown mode is a
`ValueError`, and nothing is auto-detected: the profile is always chosen explicitly (`odos process --mode …`).
See [architecture.md](architecture.md).

## Lifecycle

`engine.parse(docling_json, profile)` runs these stages in this order. Each stage reads only what the
stages before it produced. `engine.STAGES` is the executable list; a test pins the order.

| # | Stage | Module | What it does | Why here |
|---|---|---|---|---|
| 1 | `read_source` | `normalization/docling_reader.py` | Docling items and page sizes | |
| 2 | `load_evidence` | `normalization/reading_order.py` | PDF text layer (`pdf_text_lines.json`): text lines, small marks, glyph lines, region lines | Ignored unless bound to the same PDF and Docling hashes |
| 3 | `preprocess` | `normalization/hygiene.py` | running furniture → layout overlaps → reading-order repair → text restoration (`source_text.py`) → segmentation of merged items → highlight geometry (`highlight.py`) | Reading-order repair works on Docling's text, so it runs before restoration. Restoration runs before segmentation, whose offsets index the canonical text. Highlights need the final segments |
| 4 | `parse_structure` | the profile's `recognizer.py` | builds the legal structure | **The only stage that assigns element IDs** |
| 5 | `finalize_structure` | `parsing/furniture.py` | page furniture that Docling labelled as body text moves to `model.furniture` | After the IDs exist, so nothing is renumbered |
| 6 | `resolve_footnotes` | the profile's hook → `parsing/footnotes.py` | German: `*` notes and superscript reference marks. EU: none here, because the `( n )` marks define the footnote IDs and the recognizer anchors them in stage 4 | Needs the furniture already detached (page-footer marks) |
| 7 | `segment_sentences` | `parsing/sentences.py` | sentences as ranges over element text (units and list types from the profile) | Needs the final tree |
| 8 | `normalize_toc` | `parsing/toc.py` | logical TOC entries linked to body elements (the profile's `TocVocabulary`) | Needs the final body |

**Validation** is not a parsing stage. It reads the finished model and is written by the profile's
`write_reports` hook:

- `parsing/accounting.py`: every Docling item is accounted for, split items are tiled exactly, and the
  text is verbatim.
- the profile's own `report.py`.

## Module structure

```
backend/src/odos/
  document_model.py            the canonical DocumentModel (Pydantic)
  normalization/               the PDF/Docling source layer (stages 1–3)
    docling_reader.py          Docling JSON → reading-ordered source items
    reading_order.py           PDF text-layer evidence; reading-order verification and repair
    hygiene.py                 running furniture, layout overlaps, segmentation, orchestration of stage 3
    source_text.py             restores characters Docling normalised away (from the text layer)
    source_marks.py            classifies small superscript marks (Satz numbers, footnote references, exponents)
    highlight.py               exact per-line highlight rectangles from the PDF glyphs
    lang_de.py, numbering.py   German language data; Roman numerals
  parsing/                     the universal parsing engine
    __init__.py                parse_document(path, mode)
    engine.py                  the lifecycle (stages 1–8)
    builder.py                 StructureBuilder: IDs, stack, warnings, source fields, furniture elements
    furniture.py, footnotes.py stages 5 and 6
    sentences.py, toc.py       stages 7 and 8
    accounting.py              validation shared by every profile's report
    profiles/
      __init__.py              registry: get(mode), for_model(model), for_legal_system(system), structured_modes()
      base.py                  LegalProfile, TocVocabulary
      german_law/              __init__.py (the profile), recognizer.py, rules.py, report.py
      eu_legislation/          __init__.py (the profile), recognizer.py, report.py
```

### Dependency rules

- The dependency direction is `document_model` ← `normalization` ← `parsing` ← exporters
  (`legal_json`) ← `pipeline` ← `cli`.
- **A profile declaration** imports only the model, `profiles.base` and language data at import time.
  Its hooks import its recognizer and its report lazily.
  - So the shared operations and the pipeline can import the registry without an import cycle.
  - A test checks exactly which modules importing the registry loads.
- **Shared operations never branch on a profile name.** They ask the registry: `for_model(model)`, or
  `for_legal_system(doc.legalSystem)` for JSON nesting.
- **Language is not the legal system.** A German-language EU act uses `lang_de`, just as German law does.

## What a profile declares

| Group | Fields |
|---|---|
| Identity | `mode` (the CLI's `--mode` value), `model_profile` (`DocumentModel.profile`: `None` = German law, as stored historically; `"eu_legislation"`), `legal_system` (`legalSystem`), `language` |
| Lifecycle | `recognize` (stage 4), `resolve_footnotes` (stage 6, or `None`) |
| Sentences | `sentence_units`, `units_if_no_subunits`, `list_types` |
| TOC | `toc`: a `TocVocabulary` with kinds, levels, containers, markers, provisions, inline marker and citation rule, ordinals |
| Public JSON | `json_types`, `json_native_terms`, `json_nesting`, `json_document_type`, `json_id_parts` |
| Outputs | `write_reports` |
| Pipeline | `has_structure` with `unsupported_summary` / `unsupported_message`, `summary`, `completed_message` |

## What is shared and what stays profile-specific

**Shared:**

- the lifecycle and the element builder (IDs, `~n` suffixes, stack, warnings)
- source fields on elements (spans, repairs, highlight boxes) and furniture elements
- hygiene, text restoration, reading-order repair, highlight geometry
- page-furniture detachment and the superscript mark classifier
- sentence segmentation and TOC normalization
- content accounting and the validation-report writer
- the public JSON exporter and its structural checks
- the pipeline run
- language data and Roman numerals

**Profile-specific, because the law differs:**

- heading vocabulary and hierarchy levels
- paragraph units
- list recognition: German numbering restarts and colon rules; EU points by indentation evidence
- text placement and continuation checks
- sequence checks and their warning codes
- front matter and metadata
- the footnote strategy
- the validation report sections
- the furniture ID scheme (`furniture/p3-header` vs `furniture/p3-page_header-1`)

## Absatz text across a page break (German profile)

The text of an Absatz can run on over a page break (MBO § 6 Absatz 1: page 9 to 10, followed by the Nummern 1 and 2).
The recognizer (`german_law/recognizer.py`, `_continues_absatz_intro`) merges the next page's item into the Absatz
only when **all** of these hold:

- the previous element is an Absatz without children, and its text ends without sentence-end punctuation
- the item is an unnumbered text on a later page, starts in lowercase, and is plain (not split, no boundary or order flags)
- the Absatz has no source spans of its own yet, and the item raised no uncertainty reasons

`StructureBuilder.extend` then adds the item's text, source reference, provenance box and page to the Absatz (the element
keeps both pages and one reference per item) and the flag `page_break_continuation_merged_confirmed` is recorded. Every other continuation
across a page break stays a separate element, flagged `continuation_across_page_break_attached_to_previous_element`.
Nothing else is merged.

## Adding a profile

1. **Create the folder.** Add `parsing/profiles/<name>/` with a `recognizer.py`:
   `(SourceInfo, preprocessed items, page sizes) -> DocumentModel`, built with `StructureBuilder`. It must:
   - assign every ID
   - set `DocumentModel.profile`
   - leave page-furniture detachment to the engine
2. **Declare the profile.** Put the `LegalProfile` (tables plus lazy hooks) in the folder's
   `__init__.py`, and register it in `PROFILES` (`parsing/profiles/__init__.py`).
3. **Add the processing mode.** Add the mode to `pipeline.ProcessingMode`. The
   registry-consistency test fails until the enum and the registry agree.
4. **Give it outputs.**
   - JSON nesting rules for its `legal_system`
   - a validation report (with `parsing/accounting.py`)
5. **Verify it on real documents** before routing anything to it (below). Add a synthetic fixture so CI
   covers the profile without private files.

## Verification

The real documents are checked in two places: the private test suite (`backend/tests/private/test_api.py`, local only) runs the whole pipeline on the Musterbauordnung
and Regulation (EU) 2023/1230 and validates the result against the JSON schema, and `npm run demo:verify` (frontend)
compares SHA-256 hashes of the fixtures built from both outputs with the committed reference. The synthetic German law
and EU regulation (`tests/synthetic_german.py`, `tests/synthetic_eu.py`) cover both profiles without private files.

**Documents still needed to judge generality:**

- **German:** an Artikelgesetz; a law with Unterabschnitte and `aa)` Doppelbuchstaben; a Verordnung
  with Anlagen and tables; a Landesbauordnung.
- **EU:** a directive; implementing and
  delegated regulations; an act with TITEL in the enacting terms; a consolidated EUR-Lex text (►M
  markers); a pre-2013 two-column Official Journal layout; an English-language act (needs `lang_en`).
