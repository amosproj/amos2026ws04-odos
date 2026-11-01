# EU legislation → Akoma Ntoso (profile `eu_legislation`)

Generator: `backend/src/odos/akn/eu_generator.py`. Validated against the unmodified OASIS AKN 3.1 XSD in
`backend/schemas/akn-3.1-os/` (same pinned files and validator as the German mapping; for the AKN4EU-shaped
export of the same model see [akn4eu-mapping.md](akn4eu-mapping.md)). Tested on Regulation (EU)
2023/1230 (German language version). Element choices were checked against the XSD content models
(quoted in brackets).

| Internal model | Akoma Ntoso | Schema basis |
|---|---|---|
| document (VERORDNUNG/RICHTLINIE/BESCHLUSS) | `act name="regulation"/"directive"/"decision"` | `act` = hierarchicalStructure: meta, preface, preamble, body, conclusions, attachments |
| doc_title, date, subject, OJ labels | `preface` › `p` (title in `docTitle`, date in `docDate date=`) | prefaceopt allows blocks; `docDate` requires `date` |
| preamble_formula / enacting_formula | `preamble` › `formula name="openingFormula"` / `"enactingFormula"` | preambleContainers; `formula` requires `name` |
| citation | `citations` › `citation` › `p` | citationHierarchy; citation = itemType (≥ 1 block) |
| recitals_intro + recital | `recitals` › `intro` + `recital` (`num`, `p`) | recitalHierarchy has optional `intro` |
| chapter / section / article | `chapter` / `section` / `article` (`num`, `heading`) | ANhier |
| article_paragraph | `paragraph` | ANhier |
| numbered_point, point, subpoint | nested `point` (num `1.` / `a)` / `i)`) | ANhier |
| annex | `attachments` › `attachment` (`num`, `heading`) › `doc name="annex"` (own `meta`, `mainBody`) | docContainerType = basehierarchy + documentType; `doc` = openStructure (meta **required**) |
| annex_part | `part` | ANhier |
| annex_heading (1., 1.1, … 1.2.4.1.) | nested `level` | ANhier contains `level` |
| unnumbered text | `content`/`intro`/`wrapUp` › `p`; text **between** numbered units: `hcontainer name="unnumberedParagraph"` › `content` | a hierarchy holds either `content` or `intro`, children, `wrapUp`; `hcontainer` is the hierElement that can carry `content` in sequence |
| table | `table`/`tr`/`td`/`p` | blockElements |
| footnote | `meta/notes/note` (`marker`, `p`) + `odos:anchor` = eId of the element holding "( n )" | `note` = subFlowStructure |
| final_formula | `conclusions` › `formula name="finalFormula"` / `"doneAt"` | basicopt |
| signature (table) | `conclusions` › `container name="signatures"` › `table` | containerType |

## Metadata (from the source text only)

| FRBR | Value | Source |
|---|---|---|
| Work `FRBRdate name="adoption"` | 2023-06-14 | "vom 14. Juni 2023" (title block) |
| Work `FRBRnumber` | 2023/1230 | title line |
| Work `FRBRauthor` → `TLCOrganization showAs` | "DES EUROPÄISCHEN PARLAMENTS UND DES RATES" (verbatim) | title line |
| Work `FRBRsubtype`, `act/@name` | regulation | mapped from the printed "VERORDNUNG" |
| Work `FRBRcountry` | eu | – |
| Expression `FRBRdate name="publication"` | 2023-06-29 | OJ running header "29.6.2023" |
| `publication` | number "L 165/1", showAs "Amtsblatt der Europäischen Union" | OJ running header |
| Manifestation `FRBRdate` | processing date | ODOS |

`FRBRuri`/`FRBRthis` (`/akn/eu/act/regulation/2023-06-14/2023-1230…`) are **derived by ODOS** and declared so in
`meta/proprietary/odos:identifiers`. No ELI or CELEX number is emitted, because neither is printed in the PDF.
Each annex `doc` repeats this metadata with `!annex_n`. Its TLC eIds are prefixed `att_n__`, because
`xsd:unique` on `@eId` applies to the whole `act`, attachments included.

## Traceability

Every node that carries source text has `odos:src` (Docling refs). Segments of split Docling items also carry
`odos:span="#/texts/373@659-1280"`. Uncertain elements carry `odos:uncertain` with the parser's reasons.
`akn_traceability.json` lists every node with its eIds, source refs, character spans, pages, bounding boxes and
uncertainty. `akn_text_preservation.json` compares every num/heading/text node with the model, in order.

## Not verified

The EU Publications Office profile (AKN4EU) and Formex were not consulted. The element names above follow the
generic OASIS schema and should be aligned with AKN4EU before production use.
