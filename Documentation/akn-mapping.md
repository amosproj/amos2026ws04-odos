# German statute structure → Akoma Ntoso

Target: Akoma Ntoso (namespace `http://docs.oasis-open.org/legaldocml/ns/akn/3.0`), validated against the
unmodified OASIS **AKN 3.1** XSD (OASIS Standard, 2 October 2026) pinned in `backend/schemas/akn-3.1-os/`.
Until 2026-10-29 the exports were validated against AKN 3.0 (2018); the XML itself did not change with the
migration (byte-identical output, valid under both).
Document type: `<act>`.

## Why names do not transfer

The OASIS XSD documents every hierarchical element identically: *"this element is a
hierarchical container called 'X' either explicitly or due to the local tradition"*.
The element names are therefore **labels chosen by tradition, not legal definitions**.
The German word *Paragraph* (§) and the AKN element `<paragraph>` do **not** denote the same
thing:

| German | Meaning in German law | AKN element chosen | Reason |
|---|---|---|---|
| Teil | top-level division | `part` | Direct equivalent of a "Part". |
| Kapitel | division of a Teil | `chapter` | Direct equivalent. |
| Abschnitt | division of a Kapitel | `section` | Same position in the tree as AKN `section` used below `chapter`. A German **§ is not** a `section`. |
| Unterabschnitt | division of an Abschnitt | `subsection` | Not present in BDSG; mapped for reuse. |
| **§ (Paragraph)** | basic numbered provision, has a title | **`article`** | `article` is AKN's basic numbered provision unit (heading + numbered sub-paragraphs). Using `<paragraph>` for § would collide with Absatz and put the wrong legal level under `chapter`. |
| **Absatz (1), (2)** | numbered sub-division of a § | **`paragraph`** | AKN `paragraph` is the numbered sub-division of an `article`. |
| Nummer 1., 2. | enumeration in an Absatz | `point` | Numbered enumerated item. |
| Buchstabe a), b) | enumeration inside a Nummer | `point` (nested in `point`) | Same element, nesting expresses the level. |
| Anlage | annex at the end of the law | `hcontainer name="anlage"` in `body` | AKN's generic hierarchical container; `attachments/attachment` would need a nested `doc` and is not used. Content (text, Nummern) is kept under it. |
| Satz (sentence) | not modelled | – | The source gives no Satz boundaries; none are invented. |
| unnumbered text | continuation / closing sentence | `p` in `content`, `intro` or `wrapUp` | See below. |
| Fußnote | editorial note block ("Textnachweis", "Zur Anwendung vgl.") | `meta/notes/note` | See below. |
| table | tabular content | `table/tr/td/p` | Cells copied verbatim; no header (`th`) is guessed. |

This choice is my reading of the AKN specification and its naming "by tradition"; it
should be confirmed against the German LegalDocML profile (LegalDocML.de) before it is
treated as final. I could not retrieve that profile in this environment.

## Content models used

`hierarchy` elements (`part`, `chapter`, `section`, `article`, `paragraph`, `point`, `list`)
take `num`, `heading`, then **either** `content` **or** `[intro?, sub-hierarchy*, wrapUp?]`.

* **Absatz/Nummer without enumeration** → `<num>` + `<content><p>text</p></content>`.
* **With enumeration (one run)** → `<num>`, `<intro><p>own text</p></intro>`, `<point>`…, optional
  `<wrapUp>` containing the unnumbered text that follows the list (e.g. BDSG § 1 (1): "Für
  nichtöffentliche Stellen gilt …").
* **Enumeration interrupted by text** (e.g. BDSG § 4 (1)) → one `<list>` per run; text between runs
  becomes the `wrapUp` of the preceding list. That text could equally be the `intro` of the next
  list; the parser flags it uncertain and it is kept in document order.
* § without Absätze → `<article>` with `<content>`; text before enumerations → `<intro>`.
* Teil/Kapitel/Abschnitt wrapping an excerpt contain only `num` + `heading`.

## Numbering and headings

`<num>` holds the marker verbatim (`§ 1`, `(2)`, `3.`, `a)`, `Teil 1`). `<heading>` holds the title
text verbatim. Nothing is renumbered or normalised. Unnumbered text carries no `<num>`.

## eIds

`eId` follows the AKN naming convention (`__` separates levels) and is derived only from the
legal numbers, so it is deterministic: `part_1__chp_1__art_1__para_1__point_2__point_a`.
Prefixes: `part chp sec subsec art para point list`; helper nodes use `__num`, `__heading`,
`__content`, `__intro`, `__wrapup`, `__p_n`, `__table_n__tr_r__td_c`. A repeated number under the
same parent (a genuine list restart) gets the suffix `-2`, `-3`. The XSD enforces uniqueness
(`xsd:unique` on `@eId` in `<act>`).

## Footnotes (continued)

Docling's own `footnote` items (page footnotes such as "1 siehe Landesrecht") become
`meta/notes/note` with one `p`. They are anchored by `odos:anchor` to the nearest enclosing §/Teil/Anlage
only: the position of the note mark inside the text is not known, so they are flagged uncertain.

## Footnotes

The "Fußnote" blocks in gesetze-im-internet.de PDFs are editorial notes that are **not anchored**
to a word in the text. AKN `authorialNote` needs an in-text anchor; inventing one would add
content. They are therefore emitted as `meta/notes/note` (heading "Fußnote" + one `p` per
paragraph) with `odos:anchor` pointing to the eId of the § they follow. Not exercised by §§ 1–2.

## Documents without an enactment date (e.g. a model regulation)

`FRBRdate/@date` is typed `xsd:date | xsd:dateTime` in the official XSD: a **full day** is required and
`2002-11` is rejected. `FRBRdate` is mandatory in Work, Expression and Manifestation. The Musterbauordnung
states only "Fassung November 2002 … zuletzt geändert durch Beschluss … vom 26./27.9.2024" – no
Ausfertigungsdatum and no unambiguous day. Therefore:

* By default (`undated_policy="refuse"`, CLI without `--allow-undated`) generation **refuses** instead of
  inventing a date.
* With the explicit opt-in (`processing_date`, used by the web pipeline) `FRBRWork/FRBRdate` holds the *real
  processing date* and its `name` says so: `ODOS-Verarbeitungsdatum (kein Rechtsdatum)`. This fills the
  mandatory slot without claiming a legal date. The XML comment, `odos:undated legal-date="false"` and a
  `WORK_DATE_NOT_LEGAL` warning repeat it.
* The statement found in the document is stored verbatim in `FRBRalias name="stated-version"`.
* The Work URI uses the stated "FASSUNG NOVEMBER 2002" as `2002-11`. This is a provisional identifier,
  not checked by the XSD, and not an official URI.
* "26./27.9.2024" is never converted to a day.

Limitation: consumers that read `FRBRWork/FRBRdate` as an enactment date must check `@name`.
I could not consult the German LegalDocML profile for its recommended handling of undated model texts.

## Metadata (nothing authoritative is invented)

| Field | Value | Source |
|---|---|---|
| Work date (`Ausfertigung`) | 2017-06-30 | "Ausfertigungsdatum" in the PDF |
| Work/Expression author | `#unspecified` ("Not determined from the source") | not in the model |
| Manifestation author | `#odos` | the converter |
| Expression/Manifestation date | 2026-10-27 (`Abruf`, `Konvertierung`) | download date in `backend/data/input/SOURCE.md` |
| Country, language | `de`, `deu` | assumption: German federal law in German |
| Work URI | `/akn/de/act/2017-06-30/bdsg` | convention applied to the above; not an official identifier |

The excerpt is declared as such in an XML comment, in `FRBRalias`, in
`meta/proprietary/odos:excerpt complete="false"` and in the reports.

## Traceability and uncertainty (ODOS extension namespace)

Attributes from the ODOS namespace are allowed by the schema (`anyAttribute ##other lax`):
`odos:src` = Docling item reference(s) (`#/texts/88`), `odos:uncertain` = reasons from the
Internal Document Model. `akn_traceability.json` maps each eId to the model id, Docling refs, pages,
bounding boxes, original text and uncertainty flags, and lists every model element **not** in the
excerpt by reason.

Uncertain elements are never dropped, merged or reordered: they appear at their document position
(currently `wrapUp` paragraphs for "text after list") with `odos:uncertain` set.

## Not mapped

Table of contents, front matter (apart from the title in `preface/docTitle`), page headers/footers and
all content outside the excerpt are excluded and counted in `akn_traceability.json`.
