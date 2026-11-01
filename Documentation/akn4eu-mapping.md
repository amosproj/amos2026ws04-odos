# AKN4EU export profile (`akn4eu`)

A separate export profile for EU legislation, next to (not replacing) the generic AKN exports
([akn-mapping.md](akn-mapping.md) for German law, [akn-eu-mapping.md](akn-eu-mapping.md) for EU legislation). Code:
`odos.akn.akn4eu` (generator), `odos.akn.akn4eu_checks` (sample rules), `odos.akn.akn4eu_artifacts`
(files, package, report). CLI: `odos akn4eu <document_model.json> [--eli URI]`. API:
`POST /api/documents/{id}/exports/akn4eu`, `GET .../exports/akn4eu/{package|report|traceability|text_report}`.

## What "valid" means here

| Layer | Status for Regulation (EU) 2023/1230 | What it proves |
|---|---|---|
| OASIS AKN 3.1 XSD (`backend/schemas/akn-3.1-os`, OASIS Standard 2026-10-02, pinned by SHA-256 = OASIS manifest) | all 13 files valid | schema validity against the base AKN4EU 5.x builds on |
| AKN4EU sample rules (`akn4eu_checks`, 16 rules) | all hold | built like the official samples; each rule holds for all 60 official sample files |
| Official AKN4EU validation (AKN4EU schema/Schematron) | **not performed** | nothing: no official AKN4EU validation artefacts were available |
| Text and order against the Internal Document Model | identical | no text lost, altered or reordered by the conversion |

The report (`akn4eu_validation_report.json`) keeps these layers apart. Its status is at best
"sample-compatible AKN4EU (not officially verified AKN4EU conformance)". It never says "AKN4EU valid".

## Reference material

- AKN4EU 5.0.1.0 sample package (Publications Office). The XML files are in
  `backend/tests/fixtures/akn4eu-5.0.1.0-samples` (SHA-256 manifest in that folder). There are 25 sets and 60 XML files,
  English only, and every file declares `akn4euVersion 5.0.0.1`:
  - 3 published acts: Implementing Regulation (EU) 2025/864, Implementing Directive (EU) 2022/905 and
    Implementing Decision (EU) 2022/1461;
  - 9 Commission drafts (`bill`);
  - annexes, explanatory memoranda, and opinions of the Committee of the Regions and the EESC;
  - Official Journal and collection wrappers.

  None of them is a regulation of the European Parliament and of the Council with chapters. 2025/864 is
  the closest reference.
- AKN4EU 5.x is based on AKN 3.1 (Publications Office, EU Vocabularies, Schemas page). All 60 samples
  validate against the AKN 3.1 OS schema. 29 of them failed the former AKN 3.0 schema, because of `FRBRlanguage/@refersTo`, `annex`,
  `thead`/`tbody`, `crossHeading` positions and nested `recitals`. AKN 3.1 keeps the namespace
  `http://docs.oasis-open.org/legaldocml/ns/akn/3.0`.

## Gap analysis: generic EU export vs. the AKN4EU samples

| Area | generic EU export (`eu_generator`) | AKN4EU samples | `akn4eu` profile |
|---|---|---|---|
| Schema | AKN 3.0 until 2026-10-29, now AKN 3.1 | AKN 3.1 | AKN 3.1 |
| Namespaces | `akn/3.0` + `odos:` attributes on most nodes | `akn/3.0`; `akn4eu:` (`http://imfc.europa.eu/akn4eu`) only in `preservation`; no foreign attributes | as the samples; provenance moves to `akn4eu_traceability.json` |
| Document element | `act name="regulation"` | resource-type codes: `act name="REG_IMPL"`, `bill name="REG"`, `doc name="ANNEX"` | `act name="REG"` (from the printed "VERORDNUNG"; table `RESOURCE_TYPE`) |
| Identifiers | `eId` everywhere, OASIS style `chp_1__art_2__para_2` | `xml:id` on (nearly) every element; `eId` only `art_N`, `art_N/unp_N`, `rct_N`, `cit_N`, `pbl_N`, `ent_N`, `fnp_N`, `tit_N`, `anx/par_N[/tab_N…]` | deterministic `xml:id` on every content element; `eId` only in the sample patterns |
| FRBR Work | ODOS-derived `/akn/eu/act/regulation/…`, country `eu` | ELI `…/eli/reg_impl/2025/864/oj` (drafts: empty), `FRBRcountry EU`, adoption and publication dates, `FRBRsubtype`, `FRBRnumber` (printed number; ELI path with `refersTo="#ELI"`), `FRBRprescriptive` | layout as the samples; ELI only if supplied and consistent (below), else empty values |
| FRBR Expression | `…/deu@date`, `FRBRlanguage deu` | `…/oj/eng`, date `2999-01-01`, `FRBRlanguage language="en" refersTo="~ENG"` | `…/oj/deu` or empty, `2999-01-01`, `language="de" refersTo="~DEU"` |
| FRBR Manifestation | ODOS URIs | `…/oj/eng/akn4eu`, `preservation/akn4eu:akn4euVersion` + `akn4euDocumentation` | same; the date is the real conversion date and the author `#ODOS` (deviation: the samples use placeholders) |
| References | ODOS placeholder organisations | EU authority tables (corporate-body, resource-type, language, place, role, subdivision) | same, for EP, CONSIL, COM, DEU, REG…, FRA_SXB/BEL_BRU/LUX_LUX, PRESID, INP, mapped only from printed text |
| Publication | `name="OJ" number="L 165/1"` | `name="Official Journal of the European Union" showAs="OJ L, 2025/864, 6.5.2025"` | printed journal name, number `L 165/1`, `showAs` composed of the printed header parts |
| Preface | `p/docTitle`, `p/docDate` | `longTitle/p` with `docType`, `docNumber`, `date`, `docPurpose`; `container[@name='eeaRelevance']` | same; inline markup only where it matches the extracted text exactly |
| Preamble | `formula name="openingFormula"` | `formula name="actingEntity"`, `citations/citation`, `recitals/intro`, `recital`, `formula name="enactingFormula"` | same |
| Articles | `paragraph`, `intro` + `point`, or `content` | `paragraph > list > (subparagraph refersTo="~INP", point…)`; unnumbered text as `paragraph eId="art_N/unp_N"` | same; text after the points as following `subparagraph`s |
| Binding clause | `conclusions/formula name="finalFormula"` | `body/clause` | `body/clause` |
| Conclusions | `formula doneAt` + signature table | `p` "Done at `<location>`, `<date>`"; `block name="signatory"/signature(organization, role, person)` | same where the text matches exactly; otherwise kept as `p`/table with a warning |
| Footnotes | `meta/notes/note` + `odos:anchor` | inline `authorialNote marker="n" placement="bottom"` at the reference | same; see "Footnotes" |
| Annexes | inline `attachment/doc name="annex"` | separate `doc name="ANNEX"` files (`mainBody/annex`, own meta, `FRBRuri` = the act's), linked by `attachments/attachment/documentRef` | same, one file per annex |
| Tables | `table/tr/td` | `hcontainer TAB/TAB_CONTAINER`, `thead`/`tbody` | `table/tr/td` (valid in 3.1; no header information in the model) |
| Package | one XML file | `.leg` ZIP with an Official Journal or collection wrapper as `main-…xml` | `akn4eu_package.zip` (act + annexes); no OJ wrapper (the cover data is not in the model) |

## Rules that keep the conversion honest

- **No invented metadata.**
  - The ELI is not printed in the 2023/1230 PDF, so `FRBRthis`/`FRBRuri` stay empty, as in the drafting samples.
  - A caller may pass `--eli`. It is used only if it equals `http://data.europa.eu/eli/<type>/<year>/<number>/oj` for the printed type and number; otherwise the export is refused.
  - With several annexes, the annex ELIs are unknown and stay empty (warning `ANNEX_ELI_UNKNOWN`).
  - Authority codes come from small fixed tables applied to printed text (e.g. "Straßburg" → `FRA_SXB`, "Im Namen des Rates" → `CONSIL`). Anything not matched gets no reference.
- **Verbatim text.** Every node carries the model's `content_text` / `title` / `marker`. `verify_akn4eu` rebuilds each element's text from the XML and compares it with the model, together with document order and footnote order.
- **Two recorded rearrangements**, both reversible:
  1. A footnote reference "( n )" is moved from the running text into `authorialNote/@marker`, where the samples carry it.
  2. The footnote's own text loses its leading "( n ) ".

  Both are stored per element in the traceability file (`reference_text`, `stripped_prefix`), and the text check puts them back. If a reference is not found exactly once, the text stays unchanged and the note is appended (warning `FOOTNOTE_REFERENCE_NOT_LOCATED`).
- **The binding clause moves** from the conclusions to `body/clause`. Document order is preserved; only the empty conclusions shell now comes after it.
- **Uncertainty is not dropped.** The XML has no `odos:` markup, but the file comment states how many elements are uncertain, and `akn4eu_traceability.json` lists each one with its reasons, Docling references, pages, boxes and character spans.
- **Reviewed text is not claimed to be verbatim.** In a reviewed model, corrected values are exported and the trace keeps `reviewed` (with `verbatim_from_source: false`) and the original source text.

## ODOS additions and deviations (documented, not in the samples)

- `coverPage/container[@name='ojSectionHeadings']` holds the OJ section headings printed above the title ("I", "(Gesetzgebungsakte)", "VERORDNUNGEN"). They belong to the Official Journal issue, but no text is dropped.
- `identification/@source="~ODOS"` and a `TLCOrganization` ODOS with an ODOS-local `href`, because the converter is not the Publications Office (`~PUBL`).
- FRBRManifestation: real conversion date (`name="conversion"`) and author `#ODOS` instead of placeholders.
- `@xml:id` values are readable paths (`art_3__unp_1__point_1__point_a`) instead of generated ids (`d1e148`).

## Limitations

- **Official AKN4EU conformance is not verified.** The official AKN4EU artefacts are not in the sample ZIP, and the Publications Office download page blocks automated access. Once available, add them as a fourth layer.
- **German-language EU acts only.** The EU parser reads German acts; the language is fixed to `de`/`DEU`.
- **Sample coverage is thin.** Mappings with no sample evidence are marked as such:
  - eIds of numbered article paragraphs, chapters and points (none are given);
  - nested points (`point > list`);
  - text after a list (`subparagraph` after the `list`).
- **Not modelled:**
  - no OJ/collection wrapper and no `.leg` file;
  - no `analysis/activeModifications` (amendment relations are not in the model);
  - no `thead`, because the model has no header rows;
  - `refersTo` on citations (legal basis) and articles (`ART_DEF`, `ART_AMEND`) is not inferred.
- **Not in the review workflow.** The human review regenerates the generic export; the AKN4EU export is generated on request.
