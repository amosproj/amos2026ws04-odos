"""Deterministic technical-standard parser (processing mode ``technical_standard``).

Recognises the structure shared by DIN, DIN EN, DIN ISO, DIN EN ISO, DIN VDE, DIN SPEC and standalone ISO / IEC /
EN standards. Text is never rewritten: every Docling item becomes (part of) exactly one element, and whatever
cannot be placed with certainty is kept and flagged uncertain.

The hierarchy is driven by the printed dotted number (``1`` -> ``1.1`` -> ``1.1.1``; annex clauses ``A.1`` ->
``A.1.1``), not by font sizes or Docling heading levels. Items that Docling prints on several lines are joined by
evidence from the item sequence: a bare number (``3.1``) with its title on the next header, an annex heading
(``Anhang A`` / ``(informativ)`` / title), a caption nested under its table or picture.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import NamedTuple

from odos.document_model import DocumentMetadata, DocumentModel, Element, ElementType as T, ParserWarning
from odos.normalization.docling_reader import SourceItem
from odos.normalization.lang_de import MONTHS
from odos.parsing import continuation
from odos.parsing.builder import ROOT_ID, StructureBuilder, furniture_element

PROFILE = "technical_standard"

# --- title and metadata ----------------------------------------------------------------------------------
_ORG = r"(?:ETSI|DIN|CEN|CENELEC|DKE|VDMA)"
_KIND = r"(?:VDE-AR(?:-[A-Z])?|EN|ISO|IEC|VDE(?:\s+V)?|SPEC|CLC|TS|TR|PAS|ES|EG)(?:/(?:IEC|ISO|TS|TR))?"
LANGUAGES = {"D": "de", "E": "en", "F": "fr"}
_AMEND = r"/?[A-Z]{1,3}\d*"  # "/A1", "/AA", "/AC1", and glued "A3" ("0100-443A3")
# A standard identifier on its own line: "DIN EN ISO 12100:2011-03", "E DIN EN ISO 13849-1:2026-03" (draft), "DIN SPEC 91345:2016-04 (D)",
# "DIN VDE V 0100-551-1 (VDE V 0100-551-1):2018-05", "DIN VDE 0100-443/A3 (VDE 0100-443/A3):2022-09", "ETSI EN 303 645 V2.1.1 (2020-06)",
# "DIN VDE 0100-520 (VDE 0100-520) Beiblatt 1:2014-07", "VDE-AR-N 4110 (VDE-AR-N 4110) Ber1 zur Anwendungsregel:2024-11".
TITLE_RX = re.compile(
    rf"^(?:E\s+)?(?P<family>(?:{_ORG}\s+)?(?:{_KIND}\s+)*{_KIND}|{_ORG})\s+"
    r"(?P<number>\d+(?:[‑-]\d+)*(?: \d{3})*)"
    rf"(?P<amend>{_AMEND})?"
    rf"(?:\s*\(\s*VDE(?:-AR(?:-[A-Z])?)?(?:\s+V)?\s+[\d-]+(?:{_AMEND})?\s*\)|\s*;\s*VDE(?:\s+V)?\s+[\d-]+(?=:))?"
    r"(?:\s*[-–]?\s+(?P<variant>(?:Berichtigung|Corrigendum|Beiblatt)\s+\d+|Ber\d+\s+zur\s+Anwendungsregel|Anwendungsregel|Vornorm|Entwurf))?"
    r"(?::(?P<issue>\d{4}(?:-\d{2}(?:-\d{2})?)?))?"
    r"(?:/(?P<amend2>(?:A|AMD|Amd|AC|COR|Cor)\s?\d*)(?::(?P<issue3>\d{4}(?:-\d{2})?))?)?"  # "EN ISO 9001:2015/A1:2024"
    r"(?:\s+V(?P<version>\d+(?:\.\d+){1,2}))?"
    r"(?:\s*\((?P<issue2>\d{4}-\d{2})\))?"
    r"(?:\s*\((?P<lang>[DEF](?:/[DEF]){0,2})\))?"
    r"\s*$"
)
EDITION_RX = re.compile(r"^Edition\s+\d+(?:\.\d+)?\s+(\d{4}-\d{2})$")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f﻿​]")


def _clean(text: str) -> str:
    """The text as the rules read it: no control characters (Docling keeps e.g. a backspace in "Contents")."""
    return _CONTROL.sub("", text or "").strip()


def _ident(t: str):
    """The identifier match of a line, or of its first line when the item carries the edition on further lines."""
    return TITLE_RX.match(t) or (TITLE_RX.match(t.splitlines()[0].strip()) if "\n" in t else None)


MONTH_YEAR_RX = re.compile(r"^(\w+)\s+(\d{4})$")

# --- zones -------------------------------------------------------------------------------------------------
FOREWORD_RX = re.compile(r"^(Nationales\s+Vorwort|Europäisches\s+Vorwort|Vorwort|National\s+foreword|European\s+foreword|Foreword)(?:\s+(?:zu[rm]?|to)\s+(?:der\s+)?(?:Änderung|Berichtigung|amendment|corrigendum)\s+\S+)?\s*$", re.I)
INTRO_RX = re.compile(r"^(Einleitung|Introduction)\s*$", re.I)
INDEX_RX = re.compile(r"^(Stichwortverzeichnis(?:se)?|Sachwortverzeichnis|Alphabetisches\s+(?:Stichwort)?verzeichnis|Alphabetical\s+index|Index)\s*$", re.I)
BIBLIO_RX = re.compile(r"^(Literaturhinweise|Literaturverzeichnis|Bibliography|Bibliographie|References)\s*$", re.I)
TOC_RX = re.compile(r"^(Inhalt|Inhaltsverzeichnis|Contents|Table\s+of\s+contents|Sommaire)\s*$", re.I)
COVER_RX = re.compile(r"^EUROPÄISCHE\s+NORM\b|^EUROPEAN\s+STANDARD\b|^INTERNATIONAL\s+STANDARD\b")  # cover of an adopted EN / ISO
BLANK_PAGE_RX = re.compile(r"^\W*(Leerseite|Blank\s+page)\W*$", re.I)
# An amendment's instruction line: "Ändere Abschnitt 443.6.2 der DIN VDE 0100-443 wie folgt:", "Replace Table 2 by the following:". It
# starts with an imperative, names a unit of the base standard and ends with a colon or "wie folgt" / "as follows".
INSTRUCTION_RX = re.compile(
    r"^(?:Ändere|Ändern|Ersetze|Ersetzen|Ergänze|Ergänzen|Streiche|Streichen|Lösche|Löschen|Füge|Fügen|Replace|Add|Delete|Insert|Change|Amend|Modify|Renumber)\b"
    r"[^\n]{0,200}?\b(?:Abschnitt|Unterabschnitt|Absatz|Anhang|Tabelle|Bild|Anmerkung|Satz|Literaturhinweise|Titel|Clause|Subclause|Annex|Table|Figure|Note|Bibliography|Title)\b"
    r"[^\n]{0,200}?(?:wie folgt|as follows|:)\s*$", re.S)
LEADER_RX = re.compile(r"\.{3,}|\u2026")  # dot leaders: a table-of-contents line, never a heading
NORMATIVITY_RX = re.compile(r"^\(\s*(normativ|informativ|normative|informative)\s*\)$")
ANNEX_RX = re.compile(
    r"^((?i:(?:Nationaler\s+|National\s+)?(?:Anhang|Annexe?)))\s+([A-Z]{1,3})\b(?!\.\d)\s*"
    r"(?:\(\s*((?i:normativ|informativ|normative|informative|normatif|informatif))\s*\))?\s*(.*)$",
    re.S,
)
DEFINITIONS_TITLE_RX = re.compile(r"(Begriffe|Terms\s+and\s+definitions|Begriffsbestimmungen|Definitionen|Terminologie)", re.I)

# --- numbered units ---------------------------------------------------------------------------------------
IEV = r"\d{3}-\d{2}(?:-\d{2})?"  # IEC 60050 style: chapter-section[-entry], "826-11", "826-11-01"
NUM = rf"(?:{IEV}|\d+(?:\.\d+)*|[A-Z]{{1,2}}(?:\.\d+)+)"  # "3", "3.1.2", "A.1", "ZA.2", "826-11-01"
IEV_RX = re.compile(IEV)
# "HAUPTABSCHNITT 826-11 – SPANNUNGEN UND STRÖME", "SECTION 826-11 – VOLTAGES AND CURRENTS": a titled division of a clause
DIVISION_RX = re.compile(r"^([A-Za-zÄÖÜäöüÉéÈè]+)\s+(\d{3}-\d{2})\s*[\u2013\u2014-]\s*(\S.*)$", re.S)
SOURCE_REF_RX = re.compile(r"^\[(?:IEV|SOURCE|QUELLE|SOURCE\s*:|ISO|IEC)[^\]]*\]$")
CLAUSE_RX = re.compile(rf"^({NUM})\s+(\S.*)$", re.S)
NUMBER_ONLY_RX = re.compile(rf"^({NUM})$")
# Notes and examples are printed in capitals; "Beispiele für ..." or "Notebook" in running text must not match.
NOTE_RX = re.compile(r"^(ANMERKUNG|NOTE)\b(?:\s+(\d+))?(?:\s+zum\s+Eintrag|\s+to\s+entry)?\s*(?:[:.]\s*)?(.*)$", re.S)
EXAMPLE_RX = re.compile(r"^(BEISPIEL|EXAMPLE)\b(?:\s+(\d+))?\s*(?:[:.]\s*)?(.*)$", re.S)
CONTINUED = r"(?:\s*\(\s*(fortgesetzt|Fortsetzung|continued)\s*\))?"
FIGURE_CAPTION_RX = re.compile(rf"^(Bild|Figur|Figure|Abbildung)\s+(\S+?)(?:\s*[—–\-:]\s+(.+?))?{CONTINUED}\s*$", re.S)
TABLE_CAPTION_RX = re.compile(rf"^(Tabelle|Table)\s+(\S+?)(?:\s*[—–\-:]\s+(.+?))?{CONTINUED}\s*$", re.S)
FORMULA_TAIL_RX = re.compile(r"\(\s*(\d+(?:\.\d+)?)\s*\)\s*$")
DASH_RX = re.compile(r"^[—–⎯\-]\s+(\S.*)$", re.S)  # em/en dash, "⎯" (U+23AF, DIN list dash), hyphen
LETTER_RX = re.compile(r"^([a-z])\)\s+(\S.*)$", re.S)
NUM_LIST_RX = re.compile(r"^(\d+)\)\s+(\S.*)$", re.S)
ROMAN_LIST_RX = re.compile(r"^([ivx]{2,})\)\s+(\S.*)$", re.S)  # "ii)", "iii)", "iv)"; a lone "i)" is read as the letter list
FOOTNOTE_RX = re.compile(r"^(\d+)\)\s*")

LEVELS: dict[T, int | float] = {
    T.STANDARD_TITLE: 0.5, T.FOREWORD: 1, T.INTRODUCTION: 1, T.STANDARD_ANNEX: 1, T.BIBLIOGRAPHY: 1,
    T.CLAUSE: 2, T.DEFINITION: 2, T.BIBLIOGRAPHIC_ENTRY: 2,
    T.LIST_ITEM: 10, T.DASH_ITEM: 10, T.NOTE: 11, T.EXAMPLE: 11, T.FIGURE: 11, T.FORMULA: 11,
}  # fmt: skip
SLUG = {
    T.FOREWORD: "foreword", T.INTRODUCTION: "intro", T.STANDARD_ANNEX: "annex", T.BIBLIOGRAPHY: "bib",
    T.CLAUSE: "c", T.DEFINITION: "c", T.NOTE: "note", T.EXAMPLE: "ex", T.FIGURE: "fig", T.FORMULA: "f",
    T.BIBLIOGRAPHIC_ENTRY: "e", T.LIST_ITEM: "li", T.DASH_ITEM: "d", T.TABLE: "tab", T.PICTURE: "pic",
    T.FOOTNOTE: "fn",
}  # fmt: skip
CONTINUABLE = (T.TEXT, T.LIST_ITEM, T.DASH_ITEM, T.NOTE, T.EXAMPLE)
WARNING_CATEGORY = {"TS_CLAUSE_NUMBER_GAP": "needs_review", "TS_ANNEX_WITHOUT_CLASSIFICATION": "extraction_uncertainty",
                    "LINE_END_HYPHEN_UNRESOLVED": "extraction_uncertainty"}  # fmt: skip


def _annex_heading(item: SourceItem, t: str, am: re.Match) -> bool:
    """"Annex A (informative): Title" is a heading; "Annex A (informative) of the present document has been included to
    ..." is a sentence. A heading is a header or carries its normative/informative statement, and does not run on in
    lower case."""
    rest = am.group(4).strip().lstrip(":.–—- ").strip()
    if len(t) > 200 or (rest and rest[0].islower()):
        return False
    return item.label == "section_header" or bool(am.group(3))


def depth_of(number: str) -> int:
    """'3' -> 1, '3.1.2' -> 3; annex clauses count from the letter: 'A.1' -> 1, 'A.1.2' -> 2. An IEV number ("826-11-01")
    counts its hyphen parts; its level is set relative to the enclosing clause (see `_TsBuilder.number_level`)."""
    if IEV_RX.fullmatch(number):
        return len(number.split("-"))
    parts = number.split(".")
    return len(parts) - 1 if parts[0].isalpha() else len(parts)


class _TsBuilder(StructureBuilder):
    def __init__(self, page_sizes):
        super().__init__(dict(LEVELS))
        self.zone = "front"  # front | foreword | introduction | body | annex | bibliography
        self.items: list[SourceItem] = []
        self.consumed: set[int] = set()
        self.page_sizes = page_sizes or {}
        self.notes: list[ParserWarning] = []
        self.definitions_clause: str | None = None  # number of the terms-and-definitions clause
        self.national_annex_open = False
        self.runs: dict[tuple[str, str], int] = defaultdict(int)
        self.by_ref: dict[str, int] = {}
        self.margin: dict[int, float] = {}  # page -> left edge of the body text
        self.list_stack: list[tuple[Element, float | None]] = []  # open list items and their indentation

    def at(self, ref: str) -> int:
        return self.by_ref[ref]

    def warn(self, code, message, el=None, item=None, severity="warning"):
        super().warn(code, message, el=el, item=item, severity=severity)
        self.warnings[-1].category = WARNING_CATEGORY.get(code, "needs_review")

    def note(self, code, message, el=None) -> None:
        self.notes.append(ParserWarning(code=code, message=message, severity="info", category="valid_structure",
                                        element_id=el.id if el else None))  # fmt: skip

    def level(self, el: Element) -> int | float:
        if el.type in (T.CLAUSE, T.DEFINITION) and el.number:
            if IEV_RX.fullmatch(el.number) and el.parent_id in self.index and el.parent_id != ROOT_ID:
                return self.level(self.index[el.parent_id]) + 1  # an IEV unit sits one level below what holds it
            return 1 + depth_of(el.number)
        return LEVELS.get(el.type, 0)

    def number_level(self, number: str) -> int | float:
        """Level a unit with this printed number would take: dotted numbers by depth, an IEV number below the nearest open
        clause that is not itself an IEV unit ("826-11" under "3", "826-11-01" under "826-11")."""
        if IEV_RX.fullmatch(number):
            base = next((e for e in reversed(self.stack) if e.type in (T.CLAUSE, T.DEFINITION) and not IEV_RX.fullmatch(e.number or "")), None)
            return (self.level(base) if base is not None else 1) + len(number.split("-")) - 1
        return 1 + depth_of(number)

    def top(self) -> Element:
        return self.stack[-1] if self.stack else self.index[ROOT_ID]

    def local(self, parent: Element, base: str) -> str:
        """`base`, or `run<n>-base` when the parent already has that local id (a restarted list, a repeated note number)."""
        if f"{parent.id}/{base}" not in self.index:
            return base
        self.runs[(parent.id, base)] += 1
        n = self.runs[(parent.id, base)] + 1
        while f"{parent.id}/run{n}-{base}" in self.index:
            n += 1
        return f"run{n}-{base}"

    def next_index(self, i: int) -> int | None:
        j = i + 1
        while j < len(self.items) and (j in self.consumed or self.items[j].is_page_furniture):
            j += 1
        return j if j < len(self.items) else None


def _structural(t: str) -> bool:
    """A line that starts a unit of its own (so it can neither be a title line nor continue a text)."""
    return bool(CLAUSE_RX.match(t) or NUMBER_ONLY_RX.match(t) or ANNEX_RX.match(t) or FOREWORD_RX.match(t)
                or INTRO_RX.match(t) or BIBLIO_RX.match(t) or NOTE_RX.match(t) or EXAMPLE_RX.match(t)
                or FIGURE_CAPTION_RX.match(t) or TABLE_CAPTION_RX.match(t) or DASH_RX.match(t)
                or LETTER_RX.match(t) or NUM_LIST_RX.match(t) or ROMAN_LIST_RX.match(t))  # fmt: skip


# =====================================================================================================
def _margins(items: list[SourceItem]) -> dict[int, float]:
    """Left edge of the body text per page: the leftmost box of a text item that is not furniture."""
    out: dict[int, float] = {}
    for it in items:
        if it.is_page_furniture or it.table is not None or it.label in ("picture", "footnote"):
            continue
        for p in it.provenance:
            if p.bbox is not None:
                out[p.page_no] = min(out.get(p.page_no, p.bbox.l), p.bbox.l)
    return out


def _indent(b: _TsBuilder, item: SourceItem) -> float | None:
    """Indentation of an item in points from its page's body margin (None when its position is unknown or it is a
    segment of a larger Docling item)."""
    p = next((p for p in item.provenance if p.bbox is not None), None)
    if p is None or p.page_no not in b.margin or item.span is not None:
        return None
    return p.bbox.l - b.margin[p.page_no]


def _column(it: SourceItem, page_sizes) -> str | None:
    """'left', 'right' or 'wide' by the item's box on its page; None without a box or page size."""
    page, box = _box(it)
    if box is None or page not in page_sizes:
        return None
    width = page_sizes[page][0]
    mid, tol = width / 2, 0.04 * width
    if box.l < mid - tol and box.r > mid + tol:
        return "wide"
    return "left" if (box.l + box.r) / 2 < mid else "right"


def _heading_keys(it: SourceItem) -> set:
    """What a heading names independently of its language: its number, or the position of its standard word (Vorwort = Foreword)."""
    t = _clean(it.orig)
    if it.label != "section_header":
        return set()
    if (m := CLAUSE_RX.match(t)) or (m := NUMBER_ONLY_RX.match(t)):
        return {("n", m.group(1))}
    low = t.lower()
    return {("w", i) for i, (de, en) in enumerate(zip(LANGUAGE_HEADINGS["de"], LANGUAGE_HEADINGS["en"]))
            if low in (de, en) or low.startswith((de + " ", en + " "))}  # fmt: skip


def _split_parallel_editions(items: list[SourceItem], page_sizes) -> list[SourceItem]:
    """A bilingual edition ("Deutsche und Englische Fassung") sets the two languages side by side. A column-aware reading order
    then alternates them page by page, which cuts both hierarchies in half. Evidence that the columns are two editions and not
    one two-column text: on consecutive pages with at least three items in each column, a heading (the same clause number, or
    Vorwort/Foreword) stands in both. The run's items are then reordered: the whole left column, then the whole right column."""
    pages: dict[int, dict[str, list[int]]] = {}
    for k, it in enumerate(items):
        if it.is_page_furniture or (col := _column(it, page_sizes)) is None:
            continue
        pages.setdefault(_box(it)[0], {"left": [], "right": [], "wide": []})[col].append(k)
    both = sorted(p for p, c in pages.items() if len(c["left"]) >= 3 and len(c["right"]) >= 3)
    runs: list[list[int]] = []
    for p in both:
        if runs and p == runs[-1][-1] + 1:
            runs[-1].append(p)
        else:
            runs.append([p])
    out = list(items)
    for run in runs:
        left_keys = set().union(*(_heading_keys(items[k]) for p in run for k in pages[p]["left"]))
        right_keys = set().union(*(_heading_keys(items[k]) for p in run for k in pages[p]["right"]))
        if not left_keys & right_keys:
            continue  # no repeated heading: an ordinary two-column text, whose reading order is already right
        slots = sorted(k for p in run for col in pages[p].values() for k in col)
        stream_a = [k for k in slots if k in {j for p in run for j in pages[p]["left"] + pages[p]["wide"]}]
        stream_b = [k for k in slots if k in {j for p in run for j in pages[p]["right"]}]
        for slot, k in zip(slots, stream_a + stream_b):
            out[slot] = items[k]
        for n, ks in ((1, [k for k in stream_a if k not in {j for p in run for j in pages[p]["wide"]}]), (2, stream_b)):
            for k in ks:
                items[k].hygiene_flags.append(f"parallel_edition:{n}")
    return out


def _box(it: SourceItem):
    p = next((p for p in it.provenance if p.bbox is not None), None)
    return (p.page_no, p.bbox) if p else (None, None)


def _opens_unit(it: SourceItem) -> bool:
    t = _clean(it.orig)
    return it.label == "section_header" and bool(
        ANNEX_RX.match(t) or FOREWORD_RX.match(t) or INTRO_RX.match(t) or BIBLIO_RX.match(t) or TOC_RX.match(t)
        or (CLAUSE_RX.match(t) and not LEADER_RX.search(t)) or NUMBER_ONLY_RX.match(t))  # fmt: skip


def _repair_heading_order(items: list[SourceItem]) -> list[SourceItem]:
    """Docling sometimes emits the heading that opens a page after the content printed below it (an annex heading read
    after its first figure). Evidence: the heading's own box lies entirely above the boxes of every earlier item on
    that page. The heading, with its normativity line and title line, is then moved before those items."""
    out = list(items)
    i = 0
    while i < len(out):
        it = out[i]
        page, box = _box(it)
        if box is None or not _opens_unit(it):
            i += 1
            continue
        group = [i]
        for k in (i + 1, i + 2):  # "(informativ)" and the title line of an annex heading belong to the heading
            if k < len(out) and out[k].label in ("text", "section_header") and _box(out[k])[0] == page and not out[k].is_page_furniture:
                u = out[k].orig.strip()
                if NORMATIVITY_RX.match(u) or (out[k].label == "section_header" and not _structural(u) and ANNEX_RX.match(it.orig.strip())):
                    group.append(k)
                    continue
            break
        prior = []
        j = i - 1
        while j >= 0 and (out[j].is_page_furniture or _box(out[j])[0] == page):
            if not out[j].is_page_furniture:
                prior.append(j)
            j -= 1
        if prior and all(_box(out[p])[1] is not None and _box(out[p])[1].t <= box.b + 1.0 for p in prior):
            first = min(prior)
            moved = [out[g] for g in group]
            for g in sorted(group, reverse=True):
                del out[g]
            out[first:first] = moved
            for x in moved:
                x.hygiene_flags.append("reading_order_repaired_heading_moved_before_lower_page_items")
            i += len(group)
        i += 1
    return out


def parse_ts_items(info, items: list[SourceItem], page_sizes: dict[int, tuple[float, float]]) -> DocumentModel:
    items = _repair_heading_order(_split_parallel_editions(items, page_sizes or {}))
    b = _TsBuilder(page_sizes)
    b.items = items
    b.by_ref = {it.ref: k for k, it in enumerate(items)}
    b.margin = _margins(items)
    meta = DocumentMetadata()
    prov: dict[str, list[str]] = {}
    furn_counter: dict[tuple[int, str], int] = defaultdict(int)
    running: dict[tuple, list] = {}

    def note_field(field: str, el: Element) -> None:
        prov.setdefault(field, []).append(el.id)

    for i, item in enumerate(items):
        if i in b.consumed:
            continue
        t = _clean(item.orig)

        if item.is_page_furniture:
            kind = T.PAGE_FOOTER if item.label == "page_footer" or "running_footer" in item.hygiene_flags else T.PAGE_HEADER
            page = item.pages[0] if item.pages else 0
            furn_counter[(page, kind.value)] += 1
            el = furniture_element(item, f"furniture/p{page}-{kind.value}-{furn_counter[(page, kind.value)]}", kind)
            b.furniture.append(el)
            if page <= 3 and kind == T.PAGE_HEADER:
                _issue_from_header(meta, el, t, note_field)
            if (fm := _ident(t)) is not None:  # a running header/footer that carries the identifier
                running.setdefault((fm["family"], fm["number"], fm["issue"] or fm["issue2"]), [0, fm, t, el])[0] += 1
            continue

        region = _region(b)
        # tables and pictures first: Docling gives them no text
        if item.table is not None:
            if b.zone != "toc" and "doc/toc" not in b.index and _is_toc_table(item):
                b.zone, b.stack = "toc", []
                b.add(None, T.TOC, b.index[ROOT_ID], "toc", local="toc")  # the table itself is the contents list
            if b.zone == "toc":
                toc = b.index["doc/toc"]
                b.add(item, T.TABLE, toc, "toc", local=b.seq_local(toc, "entry"))
            else:
                _table(b, i, item)
            continue
        if item.label == "picture":
            _picture(b, i, item, region)
            continue
        if item.label == "footnote":
            _footnote(b, item, t, region)
            continue
        if BLANK_PAGE_RX.match(t):
            parent = b.top()
            if b.zone in ("front", "cover"):
                b.add(item, T.FRONT_MATTER, b.index[ROOT_ID], "front", local=b.seq_local(b.index[ROOT_ID], "front")).hygiene_flags.append("blank_page_marker")
            else:
                b.add(item, T.TEXT, parent, region, local=b.seq_local(parent, "txt")).hygiene_flags.append("blank_page_marker")
            continue
        if not t:
            parent = b.top()
            b.add(item, T.TEXT, parent, region, local=b.seq_local(parent, "txt"), reasons=["empty_text_item"])
            continue

        # --- table of contents: opens in any zone (a cover may be followed directly by the contents) -------------
        if item.label in ("section_header", "text", "title") and TOC_RX.match(t) and "doc/toc" not in b.index:
            b.zone, b.stack = "toc", []
            b.add(item, T.TOC, b.index[ROOT_ID], "toc", local="toc", title=t, content=t)
            continue

        # --- amendment body: instruction lines are not foreword text ---------------------------------------------------------------
        if b.zone in ("front", "foreword", "introduction", "cover") and "doc/title" in b.index and (
                _is_instruction(t) or (item.label == "section_header" and _precedes_instruction(b, i))):
            b.zone, b.stack = "body", []  # what follows is the amendment itself: top-level text, no hierarchy is invented
            parent = b.top()
            el = b.add(item, T.TEXT, parent, "body", local=b.seq_local(parent, "txt"))
            el.hygiene_flags.append("amendment_instruction" if _is_instruction(t) else "amendment_base_title")
            continue

        # --- front matter: title block and metadata ---------------------------------------------------
        if b.zone == "front":
            if (m := _ident(t)) and meta.document_number is None:
                _title(b, item, m, t, meta, note_field)
                continue
            if FOREWORD_RX.match(t):
                _open_foreword(b, item, t)
                continue
            if INTRO_RX.match(t):
                _open_introduction(b, item, t)
                continue
            if (hm := _heading(b, i)) is not None and item.label == "section_header" and (hm.number == "1" or "." in hm.number):
                b.zone = "body"  # the body starts without foreword/introduction
            elif (am := ANNEX_RX.match(t)) and _annex_heading(item, t, am):
                _open_annex(b, i, am)
                continue
            else:
                el = b.add(item, T.FRONT_MATTER, b.index[ROOT_ID], "front", local=b.seq_local(b.index[ROOT_ID], "front"))
                _issue_from_header(meta, el, t, note_field)
                continue

        # --- zone openers (any zone) ------------------------------------------------------------------
        if item.label in ("section_header", "text", "title"):
            if FOREWORD_RX.match(t):
                _open_foreword(b, item, t)
                continue
            if INTRO_RX.match(t):
                _open_introduction(b, item, t)
                continue
            if BIBLIO_RX.match(t):
                _open_bibliography(b, item, t)
                continue
            if INDEX_RX.match(t) and item.label == "section_header":
                _open_zone(b, item, T.INDEX, "index", t, "index")
                continue
            if (am := ANNEX_RX.match(t)) and _annex_heading(item, t, am):
                _open_annex(b, i, am)
                continue

        if item.label == "section_header" and (COVER_RX.match(t) or (_ident(t) and "doc/title" in b.index and b.zone != "front")):
            if b.zone != "cover":  # the cover sheet of an adopted EN / ISO text opens its own front matter
                b.zone, b.stack = "cover", []
        if b.zone == "cover":
            if item.label == "section_header" and _ident(t):
                b.add(item, T.STANDARD_TITLE, b.index[ROOT_ID], "front", local=b.local(b.index[ROOT_ID], "title"),
                      reasons=[], content=t).hygiene_flags.append("embedded_standard_cover")
            else:
                b.add(item, T.FRONT_MATTER, b.index[ROOT_ID], "front", local=b.seq_local(b.index[ROOT_ID], "front"))
            continue
        if b.zone == "toc":
            toc = b.index["doc/toc"]
            if not ((hm := _heading(b, i)) is not None and hm.number == "1"):  # "1 Anwendungsbereich" without leaders: the body
                b.add(item, T.TOC_ENTRY, toc, "toc", local=b.seq_local(toc, "entry"))
                continue
            b.zone, b.stack = "body", []
        if b.zone == "bibliography":
            _bibliographic_entry(b, i, item, t)
            continue

        # --- titled IEV divisions ("HAUPTABSCHNITT 826-11 – ...") and their translations -----------------------------------
        if item.label in ("section_header", "text") and (dm := DIVISION_RX.match(t)) and b.definitions_clause is not None and b.zone == "body":
            num = dm.group(2)
            held = next((e for e in reversed(b.stack) if e.number == num), None)
            if held is not None:  # the same division printed in another language: kept beside the first, not a new unit
                b.add(item, T.TEXT, held, region, local=b.seq_local(held, "txt")).hygiene_flags.append("parallel_language_heading")
            else:
                _open_numbered(b, i, item, _Head(num, re.sub(r"\s+", " ", dm.group(3)).strip(), [], ["division_heading"], None, f"{dm.group(1)} {num}"))
            continue

        # --- numbered headings ------------------------------------------------------------------------
        if (hm := _heading(b, i)) is not None:
            if b.zone in ("foreword", "introduction") and not (b.zone == "introduction" and hm.number.split(".")[0] == "0"):
                b.zone, b.stack = "body", []  # "0.1 Overview" stays in its introduction; "1 Scope" closes it
            _open_numbered(b, i, item, hm)
            continue

        if b.zone == "index":
            parent = b.top()
            b.add(item, T.TEXT, parent, "body", local=b.seq_local(parent, "txt"))
            continue
        if b.zone in ("foreword", "introduction") and item.label == "section_header":
            _text_in_zone(b, item, t)
            continue

        region = _region(b)
        if SOURCE_REF_RX.match(t):
            _attach_text(b, item, t, region)
            b.index[b.top().children_ids[-1]].hygiene_flags.append("source_reference") if b.top().children_ids else None
            continue
        if (m := FIGURE_CAPTION_RX.match(t)):
            _standalone_caption(b, i, item, m, T.FIGURE, region)
            continue
        if (m := TABLE_CAPTION_RX.match(t)):
            _standalone_caption(b, i, item, m, T.TABLE, region)
            continue
        if (m := NOTE_RX.match(t)):
            _note_or_example(b, item, T.NOTE, m.group(2), m.group(3), region, t[: m.start(3)].strip())
            continue
        if (m := EXAMPLE_RX.match(t)):
            _note_or_example(b, item, T.EXAMPLE, m.group(2), m.group(3), region, t[: m.start(3)].strip())
            continue
        if item.label == "formula" or (item.label == "text" and "=" in t and len(t) < 160 and FORMULA_TAIL_RX.search(t)):
            fm = FORMULA_TAIL_RX.search(t)
            _formula(b, item, fm.group(1) if fm else None, t, region)
            continue
        if (m := DASH_RX.match(t)):
            _list_item(b, item, T.DASH_ITEM, None, m.group(1), region, marker=t[: m.start(1)].strip())
            continue
        if (m := LETTER_RX.match(t)) or (m := NUM_LIST_RX.match(t)) or (m := ROMAN_LIST_RX.match(t)):
            _list_item(b, item, T.LIST_ITEM, m.group(1), m.group(2), region, marker=f"{m.group(1)})")
            continue
        _attach_text(b, item, t, region)

    if meta.document_number and meta.language is None:  # the mark may stand only in the running header ("EN ISO 9001:2015 (D/E)")
        marks = {fm["lang"] for _, fm, _, _ in running.values() if fm["lang"] and fm["number"].replace("\u2011", "-") == meta.document_number}
        if len(marks) == 1:
            meta.language = ",".join(LANGUAGES[c] for c in marks.pop().split("/"))
    _detect_language(meta, b.elements)
    if meta.document_number is None and running:  # no identifier line in the body: the most frequent running header
        count, fm, text, el = max(running.values(), key=lambda v: (v[0], bool(v[1]["issue"] or v[1]["issue2"])))
        _set_identifier(meta, fm, text)
        for f in ("title", "short_title", "document_type", "document_number"):
            note_field(f, el)
    _group_definitions(b)
    _sequence_checks(b)
    meta.metadata_provenance = prov
    return DocumentModel(profile=PROFILE, source=info, metadata=meta, root_id=ROOT_ID, elements=b.elements,
                         furniture=b.furniture, warnings=b.warnings, structure_notes=b.notes)  # fmt: skip


# ---- helpers ------------------------------------------------------------------------------------------------
def _is_toc_table(item: SourceItem) -> bool:
    """A table whose rows are mostly "title ........ page": Docling puts a whole contents list (heading included) in one table."""
    rows = [r for r in (item.table.rows if item.table else []) if any(c.strip() for c in r)]
    leaders = sum(1 for r in rows if any(LEADER_RX.search(c) for c in r))
    return len(rows) >= 4 and leaders >= 0.6 * len(rows)


def _region(b: _TsBuilder) -> str:
    return {"front": "front", "cover": "front", "foreword": "front", "introduction": "front", "annex": "annex", "toc": "toc"}.get(b.zone, "body")


def _issue_from_header(meta: DocumentMetadata, el: Element, t: str, note_field) -> None:
    """The issue as a cover running header: DIN "März 2011", IEC "Edition 2.0 2010-04"."""
    year_month = None
    if (m := MONTH_YEAR_RX.match(t)) and m.group(1) in MONTHS:
        year_month = f"{m.group(2)}-{MONTHS[m.group(1)]:02d}"
    elif m := EDITION_RX.match(t):
        year_month = m.group(1)
    elif re.fullmatch(r"\d{4}-(?:0[1-9]|1[0-2])", t):  # newer DIN covers print the issue as a bare "2020-01"
        year_month = t
    if year_month and meta.version_year_month is None:
        meta.version_year_month, meta.stated_version_text = year_month, t
        note_field("version_year_month", el)
        note_field("stated_version_text", el)


def _set_identifier(meta: DocumentMetadata, m: re.Match, text: str) -> None:
    family, number = m["family"].strip(), m["number"].replace("‑", "-")
    when = m["issue3"] or m["issue"] or m["issue2"]  # an amendment's own year wins over the year of the standard it amends
    # what distinguishes this document from the standard that carries the same number: draft, amendment, corrigendum, supplement
    variant = " ".join(x for x in ("Entwurf" if m.string.startswith("E ") or m["variant"] == "Entwurf" else None,
                                   (m["amend"] or m["amend2"] or "").lstrip("/") or None,
                                   m["variant"] if m["variant"] != "Entwurf" else None) if x) or None
    meta.title, meta.document_type, meta.document_number, meta.document_variant = text.strip(), family, number, variant
    if m["lang"]:  # "(D)", "(E)", "(F)", "(D/E)": the language edition this file is
        meta.language = ",".join(LANGUAGES[c] for c in m["lang"].split("/"))
    meta.short_title = f"{family} {number}" + (f" {variant}" if variant else "") + (f":{when}" if when else "")
    if m["version"] or when:
        meta.stated_version_text = " ".join(x for x in (f"V{m['version']}" if m["version"] else None, f"({when})" if m["issue2"] and not (m["issue"] or m["issue3"]) else when) if x)
    if when and meta.version_year_month is None:
        meta.version_year_month = when[:7]


def _title(b, item, m, t, meta, note_field) -> None:
    el = b.add(item, T.STANDARD_TITLE, b.index[ROOT_ID], "front", local="title")
    _set_identifier(meta, m, m.group(0))
    for f in ("title", "short_title", "document_type", "document_number"):
        note_field(f, el)


class _Head(NamedTuple):
    number: str
    title: str | None
    extra: list
    reasons: list
    content: str | None = None
    marker: str | None = None


def _term_line(b: _TsBuilder, number: str, nxt: SourceItem) -> bool:
    """The line after a lone entry number is its term when we are inside the terms clause and the line is short, unpunctuated
    and not itself structural: "Maschine", "Nennspannung (einer elektrischen Anlage), f"."""
    dc = b.definitions_clause
    if dc is None or not (number.startswith(dc + ".") or IEV_RX.fullmatch(number)):
        return False
    t = _clean(nxt.orig)
    return (nxt.label in ("text", "section_header") and nxt.table is None and 0 < len(t) <= 120 and not t.endswith((".", ";", ":"))
            and not _structural(t) and "\n" not in t)


def _plausible(b: _TsBuilder, number: str) -> bool:
    """A number printed on a running-text line is a clause number only if it continues the numbering of the open
    unit it would belong to: "1.2" after "1.1" under the open clause "1"; "826-11-02" after "826-11-01" under "826-11"."""
    if IEV_RX.fullmatch(number):
        parts = number.split("-")
        if len(parts) != 3:
            return False
        host = next((e for e in reversed(b.stack) if e.number == "-".join(parts[:2])), None)
        sep = "-"
    else:
        parts = number.split(".")
        if len(parts) < 2 or not parts[-1].isdigit():
            return False
        host = next((e for e in reversed(b.stack) if e.type in (T.CLAUSE, T.DEFINITION, T.STANDARD_ANNEX) and e.number == ".".join(parts[:-1])), None)
        sep = "."
    if host is None:
        return False
    sibs = [b.index[c].number for c in host.children_ids if b.index[c].type in (T.CLAUSE, T.DEFINITION) and b.index[c].number]
    prev = sibs[-1].rsplit(sep, 1)[-1] if sibs else "0"
    return prev.isdigit() and parts[-1].isdigit() and int(parts[-1]) == int(prev) + 1


def _heading(b: _TsBuilder, i: int) -> _Head | None:
    """Item i as a numbered unit. A Docling section header is a heading (its title may be on the next header). A line
    labelled text is one only when its number continues the open clause's numbering: a short line is then a heading
    (flagged), a longer one a numbered paragraph ("1.2 In particular, this standard ..."), kept as clause text."""
    item = b.items[i]
    t = _clean(item.orig)
    if LEADER_RX.search(t):
        return None
    if item.label != "section_header":
        if (m := NUMBER_ONLY_RX.match(t)) and _plausible(b, m.group(1)):
            j = b.next_index(i)
            if j is not None and _term_line(b, m.group(1), b.items[j]):  # "826-11-01" / "3.1" and its term on the next line
                return _Head(m.group(1), re.sub(r"\s+", " ", b.items[j].orig).strip(), [b.items[j]], ["heading_by_shape_only"])
            return _Head(m.group(1), None, [], ["numbered_paragraph"], "")  # "411.3.2.5" alone; its paragraphs follow
        m = CLAUSE_RX.match(t)
        if not (m and ("." in m.group(1) or IEV_RX.fullmatch(m.group(1))) and _plausible(b, m.group(1))):
            return None
        body = re.sub(r"\s+", " ", m.group(2)).strip()
        if IEV_RX.fullmatch(m.group(1)):  # "826-11-01 term, f": an entry head, however long or punctuated its term is
            return _Head(m.group(1), body, [], ["heading_by_shape_only"])
        if len(t) <= 80 and "," not in t and body[:1].isupper() and not t.endswith((".", ";", ":", ",")):
            return _Head(m.group(1), body, [], ["heading_by_shape_only"])
        return _Head(m.group(1), None, [], ["numbered_paragraph"], body)
    if m := CLAUSE_RX.match(t):
        return _Head(m.group(1), re.sub(r"\s+", " ", m.group(2)).strip(), [], [])
    if m := NUMBER_ONLY_RX.match(t):
        j = b.next_index(i)  # "3.1" and its term are printed as two headers
        if j is not None and b.items[j].label == "section_header" and not _structural(_clean(b.items[j].orig)):
            return _Head(m.group(1), re.sub(r"\s+", " ", b.items[j].orig).strip(), [b.items[j]], [])
        return _Head(m.group(1), None, [], [])
    return None


def _open_numbered(b: _TsBuilder, i: int, item: SourceItem, head: _Head) -> None:
    number, title, extra, reasons = head.number, head.title, head.extra, list(head.reasons)
    for x in extra:
        b.consumed.add(b.at(x.ref))
    region = _region(b)
    in_defs = (b.definitions_clause is not None and region == "body"
               and (number.startswith(b.definitions_clause + ".") or (len(number.split("-")) == 3 and IEV_RX.fullmatch(number) is not None)))
    type_ = T.DEFINITION if in_defs and title else T.CLAUSE
    b.pop_to_below(b.number_level(number))
    parent = b.top()
    el = b.add(item, type_, parent, region, local=b.local(parent, f"c-{number.replace('.', '_')}"), number=number,
               marker=head.marker or number, title=title, content=title or head.content or "", reasons=reasons, merge=extra or None)  # fmt: skip
    b.stack.append(el)
    if depth_of(number) == 1 and parent.id == ROOT_ID and any(
            e is not el and e.type == T.CLAUSE and e.number == number and e.parent_id == ROOT_ID for e in b.elements):
        el.hygiene_flags.append("numbering_restarts_second_part")  # e.g. the French text after the English one in one PDF
        b.note("NUMBERING_RESTARTS", f"Clause {number} appears again at top level: a second language version or part follows.", el=el)
    if type_ == T.CLAUSE and depth_of(number) == 1 and region == "body" and title and DEFINITIONS_TITLE_RX.search(title):
        b.definitions_clause = number
        el.hygiene_flags.append("clause_opens_terms_and_definitions")


def _group_definitions(b: _TsBuilder) -> None:
    """A numbered entry of the definitions clause that has numbered entries below it ("3.1 allgemeine Begriffe" ->
    "3.1.1 ...") is a group heading, not a definition."""
    for e in b.elements:
        if e.type == T.DEFINITION and any(b.index[c].type == T.DEFINITION for c in e.children_ids):
            e.type = T.CLAUSE
            b.note("DEFINITION_GROUP_HEADING", f"{e.number} groups the definitions below it and is kept as a clause.", el=e)


def _open_zone(b, item, type_, local, t, zone, parent=None) -> Element:
    b.zone = zone
    b.national_annex_open = False
    parent = parent or b.index[ROOT_ID]
    b.stack = [] if parent.id == ROOT_ID else [parent]
    el = b.add(item, type_, parent, "front" if zone in ("foreword", "introduction") else "body",
               local=b.local(parent, local), title=t, content=t)  # fmt: skip
    b.stack.append(el)
    return el


def _open_foreword(b, item, t) -> None:
    kind = "-national" if re.match(r"(?i)(nationales|national)\b", t) else "-european" if re.match(r"(?i)europ", t) else ""
    _open_zone(b, item, T.FOREWORD, f"foreword{kind}", t, "foreword")


def _open_introduction(b, item, t) -> None:
    _open_zone(b, item, T.INTRODUCTION, "intro", t, "introduction")


def _open_bibliography(b, item, t) -> None:
    national = b.national_annex_open and b.stack and b.stack[0].type == T.STANDARD_ANNEX
    parent = b.stack[0] if national else None  # the bibliography of a national annex belongs to that annex
    _open_zone(b, item, T.BIBLIOGRAPHY, "bibliography", t, "bibliography", parent)


def _open_annex(b: _TsBuilder, i: int, m: re.Match) -> None:
    item = b.items[i]
    prefix, letter, norm, rest = m.group(1), m.group(2), m.group(3), m.group(4).strip()
    extra: list[SourceItem] = []
    title = re.sub(r"\s+", " ", rest.lstrip(":.–—- ")).strip() or None
    j = b.next_index(i)
    if norm is None and j is not None and (nm := NORMATIVITY_RX.match(b.items[j].orig.strip())):  # "(informativ)" on its own line
        norm = nm.group(1)
        extra.append(b.items[j])
        j = b.next_index(j)
    if title is None and j is not None and b.items[j].label == "section_header" and not _structural(b.items[j].orig.strip()):
        title = re.sub(r"\s+", " ", b.items[j].orig).strip()
        extra.append(b.items[j])
    for x in extra:
        b.consumed.add(b.at(x.ref))
    national = prefix.lower().startswith(("national", "nationaler"))
    b.zone, b.stack = "annex", []
    el = b.add(item, T.STANDARD_ANNEX, b.index[ROOT_ID], "annex", local=b.local(b.index[ROOT_ID], f"annex-{letter.lower()}"),
               number=letter, marker=f"{prefix} {letter}", title=title, content=title or "", merge=extra or None)  # fmt: skip
    if norm:
        el.classification = "normative" if norm.lower().startswith("normativ") or norm.lower().startswith("normatif") else "informative"
    else:
        b.warn("TS_ANNEX_WITHOUT_CLASSIFICATION", f"{el.marker}: the heading carries no (normativ)/(informativ) statement.", el=el, severity="info")  # fmt: skip
    b.national_annex_open = national
    b.stack = [el]


def _table(b: _TsBuilder, i: int, item: SourceItem, cap: SourceItem | None = None) -> None:
    """A Docling table with its caption: nested under the table (DIN) or the caption item read just before it."""
    region, parent = _region(b), b.top()
    if cap is None:
        cap = _caption_for(b, i, item, TABLE_CAPTION_RX)
    m = TABLE_CAPTION_RX.match(cap.orig.strip()) if cap is not None else None
    if cap is not None:
        b.consumed.add(b.at(cap.ref))
    number = m.group(2) if m else None
    prev = b.elements[-1] if b.elements else None
    el = b.add(item, T.TABLE, parent, region,
               local=b.local(parent, f"tab-{number.replace('.', '_')}" if number else b.seq_local(parent, "tab")),
               number=number, marker=f"{m.group(1)} {number}" if m else None, title=_caption_title(m) if m else None,
               content="", merge=[cap] if cap is not None else None)  # fmt: skip
    if (prev is not None and prev.type == T.TABLE and prev.table and el.table and prev.pages and el.pages
            and el.pages[0] == prev.pages[-1] + 1 and prev.table.num_cols == el.table.num_cols):  # fmt: skip
        el.hygiene_flags.append(f"table_continues:{prev.id}")  # a table over a page break is one Docling table per page


def _caption_title(m: re.Match) -> str | None:
    title = (m.group(3) or "").strip()
    if m.group(4):
        title = f"{title} ({m.group(4)})".strip()
    return re.sub(r"\s+", " ", title) or None


def _caption_for(b: _TsBuilder, i: int, item: SourceItem, rx: re.Pattern) -> SourceItem | None:
    """The caption of a table/picture: Docling nests it as a child of the item (it follows its parent here)."""
    j = i + 1
    while j < len(b.items) and b.items[j].nested_in == item.ref:
        if j not in b.consumed and b.items[j].label == "caption" and rx.match(b.items[j].orig.strip()):
            return b.items[j]
        j += 1
    return None


def _picture(b: _TsBuilder, i: int, item: SourceItem, region: str) -> None:
    parent = b.top()
    cap = _caption_for(b, i, item, FIGURE_CAPTION_RX)
    if cap is None:
        b.add(item, T.PICTURE, parent, region, local=b.local(parent, b.seq_local(parent, "pic")), content="")
        return
    m = FIGURE_CAPTION_RX.match(cap.orig.strip())
    b.consumed.add(b.at(cap.ref))
    b.add(item, T.FIGURE, parent, region, local=b.local(parent, f"fig-{m.group(2).replace('.', '_')}"), number=m.group(2),
          marker=f"{m.group(1)} {m.group(2)}", title=_caption_title(m), content="", merge=[cap])  # fmt: skip


def _standalone_caption(b, i, item, m, type_, region) -> None:
    """A caption Docling printed as a body item. A table caption directly before a table joins that table."""
    parent = b.top()
    if type_ == T.TABLE:
        j = b.next_index(i)
        if j is not None and b.items[j].table is not None:
            b.consumed.add(j)
            _table(b, j, b.items[j], cap=item)
            return
        b.add(item, T.TEXT, parent, region, local=b.seq_local(parent, "txt"), reasons=["table_caption_without_table"])
        return
    b.add(item, T.FIGURE, parent, region, local=b.local(parent, f"fig-{m.group(2).replace('.', '_')}"), number=m.group(2),
          marker=f"{m.group(1)} {m.group(2)}", title=_caption_title(m), content="")  # fmt: skip


def _footnote(b, item, t, region) -> None:
    m = FOOTNOTE_RX.match(t)
    parent = b.top()
    b.add(item, T.FOOTNOTE, parent, region, local=b.local(parent, f"fn-{m.group(1)}" if m else b.seq_local(parent, "fn")),
          number=m.group(1) if m else None, marker=m.group(0).strip() if m else None)  # fmt: skip


def _note_or_example(b, item, type_, number, content, region, marker) -> None:
    parent = b.top()
    local = f"{SLUG[type_]}-{number}" if number else b.seq_local(parent, SLUG[type_])
    b.add(item, type_, parent, region, local=b.local(parent, local), number=number, marker=marker, content=content.strip())


def _formula(b, item, number, text, region) -> None:
    parent = b.top()
    local = f"f-{number.replace('.', '_')}" if number else b.seq_local(parent, "f")
    b.add(item, T.FORMULA, parent, region, local=b.local(parent, local), number=number,
          marker=f"({number})" if number else None, content=text.strip())  # fmt: skip


INDENT_TOL, INDENT_STEP = 3.0, 6.0  # points: same column / clearly indented further


def _list_item(b, item, type_, value, content, region, marker=None) -> None:
    """A list item. Where the PDF shows it indented further than the open item above it, it is that item's child
    (a numbered list under a dash item); otherwise it is a sibling in the enclosing container. Without positions the
    list stays flat."""
    last = b.elements[-1] if b.elements else None
    if last is None or last.type not in (T.LIST_ITEM, T.DASH_ITEM):
        b.list_stack.clear()  # something else stood between: a new list
    x = _indent(b, item)
    parent = b.top()
    if x is None:
        b.list_stack.clear()
    else:
        while b.list_stack and (b.list_stack[-1][1] is None or b.list_stack[-1][1] >= x - INDENT_TOL):
            b.list_stack.pop()
        if b.list_stack and x - b.list_stack[-1][1] >= INDENT_STEP:
            parent = b.list_stack[-1][0]
    base = f"{SLUG[type_]}-{value}" if value else SLUG[type_]
    local = b.local(parent, base) if value else b.seq_local(parent, SLUG[type_])
    el = b.add(item, type_, parent, region, local=local, number=value, marker=marker, content=content.strip())
    if x is not None:
        b.list_stack.append((el, x))
    if parent is not b.top():
        el.hygiene_flags.append("nested_by_indentation")


def _text_in_zone(b, item, t) -> None:
    if _continues_open_text(b, item, _region(b)):
        return
    parent = b.top()
    reasons = ["unnumbered_heading_in_foreword"] if item.label == "section_header" else []
    b.add(item, T.TEXT, parent, _region(b), local=b.seq_local(parent, "txt"), reasons=reasons)


def _bibliographic_entry(b, i, item, t) -> None:
    parent = next(e for e in reversed(b.stack) if e.type == T.BIBLIOGRAPHY)
    starts = bool(re.match(r"^(\[\d+\]|(DIN|ISO|IEC|EN|CEN|CENELEC|VDE|DKE|VDI|ASTM|BS|NF|UL|IEEE)\b|[A-Z][A-Za-z]+\s+[A-Z]*\d)", t))
    if starts or not parent.children_ids:
        b.add(item, T.BIBLIOGRAPHIC_ENTRY, parent, "body", local=b.seq_local(parent, "e"), content=t)
        return
    last = b.index[parent.children_ids[-1]]
    if last.type == T.BIBLIOGRAPHIC_ENTRY and not last.content_text.rstrip().endswith("."):  # run-on line of one entry
        b.extend(last, item)
        last.hygiene_flags.append("run_on_line_joined")
        return
    b.add(item, T.BIBLIOGRAPHIC_ENTRY, parent, "body", local=b.seq_local(parent, "e"), content=t,
          reasons=["entry_start_not_recognised"])  # fmt: skip


def _continues_open_text(b: _TsBuilder, item: SourceItem, region: str) -> bool:
    """Unmarked text that runs on over a page break joins the element open at the end of the previous page
    (shared rule: parsing.continuation)."""
    notes, prev = continuation.trailing_notes((e for e in reversed(b.elements) if e.region != "furniture" and e.type != T.FOOTNOTE), b.page_sizes)  # fmt: skip
    if prev is None or prev.type not in CONTINUABLE or prev.region != region or prev.parent_id != b.top().id:
        return False
    if not continuation.assess(prev, item, b.page_sizes, _structural, {n.id for n in notes}).merge:
        return False
    hyphen = continuation.ends_with_hyphen(prev)
    b.extend(prev, item)
    prev.hygiene_flags.append(continuation.FLAG)
    if hyphen:
        prev.hygiene_flags.append(continuation.HYPHEN_FLAG)
    for n in notes:
        n.hygiene_flags.append(continuation.NOTE_FLAG)
    return True


# the standard drafting headings of each language: enough of them in the document's own units say which language(s) it is written in
LANGUAGE_HEADINGS = {
    "de": ("vorwort", "einleitung", "anwendungsbereich", "normative verweisungen", "begriffe", "literaturhinweise", "anhang"),
    "en": ("foreword", "introduction", "scope", "normative references", "terms and definitions", "bibliography", "annex"),
    "fr": ("avant-propos", "introduction", "domaine d’application", "domaine d'application", "références normatives", "termes et définitions", "bibliographie", "annexe"),
}  # fmt: skip


def _detect_language(meta: DocumentMetadata, elements: list[Element]) -> None:
    """Language(s) of the text from its unit headings; left unset when fewer than two headings of a language are found."""
    heads = [(e.title or e.content_text or "").strip().lower() for e in elements
             if e.type in (T.FOREWORD, T.INTRODUCTION, T.BIBLIOGRAPHY, T.STANDARD_ANNEX, T.CLAUSE) and (e.type != T.CLAUSE or "." not in (e.number or "."))]  # fmt: skip
    heads += [(e.marker or "").lower() for e in elements if e.type == T.STANDARD_ANNEX]
    score = {lang: sum(any(h == w or h.startswith(w + " ") for w in words) for h in heads) for lang, words in LANGUAGE_HEADINGS.items()}
    if "introduction" in heads:  # the same word in English and French: it counts for neither alone
        score["en"] -= 1
        score["fr"] -= 1
    found = [lang for lang, n in score.items() if n >= 2]
    if found:
        meta.language_detected = ",".join(found)


def _is_instruction(t: str) -> bool:
    return bool(INSTRUCTION_RX.match(t))


def _precedes_instruction(b: _TsBuilder, i: int) -> bool:
    """An unnumbered header directly above an instruction line is the title of the standard the amendment changes."""
    j = b.next_index(i)
    return j is not None and _is_instruction(_clean(b.items[j].orig)) and not _structural(_clean(b.items[i].orig))


def _attach_text(b: _TsBuilder, item: SourceItem, t: str, region: str) -> None:
    if _continues_open_text(b, item, region):
        return
    parent = b.top()
    if _is_instruction(t):
        b.add(item, T.TEXT, parent, region, local=b.seq_local(parent, "txt")).hygiene_flags.append("amendment_instruction")
        return
    reasons: list[str] = []
    prev = b.index[parent.children_ids[-1]] if parent.children_ids else None
    if (t[:1].islower() and prev is not None and prev.type == T.TEXT and prev.pages and item.pages and prev.pages[-1] == item.pages[0]
            and not continuation._is_closed(prev.content_text)):  # fmt: skip
        reasons.append("text_starts_lowercase_after_text")  # the text above is unfinished: a paragraph Docling split
    b.add(item, T.TEXT, parent, region, local=b.seq_local(parent, "txt"), reasons=reasons)


# ---- sequence checks ----------------------------------------------------------------------------------------
def _sequence_checks(b: _TsBuilder) -> None:
    """Flag a numbering gap among the numbered siblings of one parent (1, 2, 4 ...); a restart at 1 is a new list."""
    by_parent: dict[str, list[Element]] = defaultdict(list)
    for e in b.elements:
        if e.type in (T.CLAUSE, T.DEFINITION) and e.number:
            by_parent[e.parent_id].append(e)
    for pid, group in by_parent.items():
        last: int | None = None
        for e in group:
            tail = e.number.rsplit(".", 1)[-1]
            if not tail.isdigit():
                continue
            cur = int(tail)
            if last is not None and cur != last + 1 and cur != 1:
                b.warn("TS_CLAUSE_NUMBER_GAP", f"{e.number} follows {last} under {pid}: numbering gap.", el=e, severity="info")
            last = cur
