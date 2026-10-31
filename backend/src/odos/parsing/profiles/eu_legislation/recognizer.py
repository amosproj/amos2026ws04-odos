"""Deterministic EU legal structure parser (processing mode ``eu_legislation``).

Builds the Internal Document Model for EU acts (tested with Regulation (EU) 2023/1230, German
language version): title block, preamble (formula, citations, recitals, enacting formula), chapters,
sections, articles, paragraphs, points (a), sub-points (i), conclusions and annexes with parts and
numbered headings.

It runs on the output of the shared hygiene layer and reuses the model and builder of the German
parser, but none of its German-law rules. Text is never rewritten: every element keeps the verbatim
Docling text (or the hygiene segment of it) with its provenance. What cannot be placed with certainty
is kept and marked uncertain.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date

from odos.normalization.docling_reader import SourceItem
from odos.document_model import DocumentMetadata, DocumentModel, Element, ElementType as T, ParserWarning
from odos.parsing.builder import ROOT_ID, StructureBuilder, furniture_element
from odos.normalization.lang_de import MONTHS
from odos.normalization.numbering import roman_value

PROFILE = "eu_legislation"
ROMAN = r"[IVXLC]+"
CHAPTER_RX = re.compile(rf"^KAPITEL\s+({ROMAN})$")
SECTION_RX = re.compile(rf"^ABSCHNITT\s+(\d+|{ROMAN})$")
ARTICLE_RX = re.compile(r"^Artikel\s+(\d+[a-z]?)$")
ANNEX_RX = re.compile(rf"^ANHANG(?:\s+({ROMAN}))?$")
PART_RX = re.compile(r"^TEIL\s+([A-Z]|\d+|[IVX]+)$")
PARA_RX = re.compile(r"^\((\d+[a-z]?)\)\s+(\S.*)$", re.S)
NUM_RX = re.compile(r"^(\d+)\.\s+(\S.*)$", re.S)
DOTTED_RX = re.compile(r"^(\d+(?:\.\d+)+)\.?\s+(\S.*)$", re.S)
LETTER_RX = re.compile(r"^([a-z])\)\s+(\S.*)$", re.S)
PAREN_LETTER_RX = re.compile(r"^\(([a-z])\)\s+(\S.*)$", re.S)  # "(l)" printed instead of "l)": kept, flagged
ROMAN_PT_RX = re.compile(r"^((?:x{0,3})(?:ix|iv|v?i{0,3}))\)\s+(\S.*)$", re.S)
OPENING_RX = re.compile(r"^(DAS EUROPÄISCHE PARLAMENT|DER RAT DER EUROPÄISCHEN UNION|DIE EUROPÄISCHE KOMMISSION)\b")
RECITALS_INTRO_RX = re.compile(r"^in Erwägung (nachstehender|folgender) Gründe")
ENACTING_RX = re.compile(r"^(HABEN|HAT) FOLGENDE .+ ERLASSEN:?$")
FINAL_RX = re.compile(r"^Diese (Verordnung|Richtlinie|Beschluss|Entscheidung) ist in allen ihren Teilen verbindlich")
DONE_AT_RX = re.compile(r"^Geschehen zu \S+")
TITLE_RX = re.compile(r"^((?:DURCHFÜHRUNGS|DELEGIERTE )?(?:VERORDNUNG|RICHTLINIE|BESCHLUSS))\s*\((EU|EG|EU, Euratom|EWG)\)\s*(?:Nr\.\s*)?(\d+/\d+)\s+(.+)$")  # fmt: skip
DATE_RX = re.compile(r"^vom (\d{1,2})\. (\w+) (\d{4})$")

LEVELS = {
    T.PREAMBLE: 1, T.CHAPTER: 1, T.ANNEX: 1, T.CONCLUSIONS: 1,
    T.SECTION: 2, T.ANNEX_PART: 2, T.ARTICLE: 3,  # annex headings: 2 + depth (see _EuBuilder.level)
    T.RECITAL: 10, T.ARTICLE_PARAGRAPH: 10, T.NUMBERED_POINT: 11, T.POINT: 12, T.SUBPOINT: 13,
}  # fmt: skip
SLUG = {T.CHAPTER: "chp", T.SECTION: "sec", T.ARTICLE: "art", T.ANNEX: "annex", T.ANNEX_PART: "part",
        T.ANNEX_HEADING: "h", T.RECITAL: "rec", T.ARTICLE_PARAGRAPH: "para", T.NUMBERED_POINT: "pt",
        T.POINT: "pt", T.SUBPOINT: "sub"}  # fmt: skip

# Layout evidence: the Official Journal encodes list nesting by indentation. A body paragraph of a point
# starts right of the point's marker column; text at the marker column belongs to the enclosing unit.
INDENT_TOL = 3.0   # pt: same column
INDENT_STEP = 6.0  # pt: clearly indented further
POINT_TYPES = (T.POINT, T.SUBPOINT, T.NUMBERED_POINT)
SENTENCE_END = (".", ";", "!", "?")
# what a remaining warning means for the reader (see docs: parser errors vs. source uncertainty vs. review)
WARNING_CATEGORY = {
    "UNRECOGNIZED_HEADING": "parser_error",
    "FOOTNOTE_ANCHOR_NOT_FOUND": "extraction_uncertainty",
    "LINE_END_HYPHEN_UNRESOLVED": "extraction_uncertainty",
    "UNNUMBERED_ANNEX_HEADING": "extraction_uncertainty",
}  # everything else: needs_review


class _EuBuilder(StructureBuilder):
    """The shared builder plus what EU recognition needs: look-ahead, layout margins, warning categories."""

    def __init__(self):
        super().__init__(dict(LEVELS))
        self.runs: dict[tuple[str, T], int] = defaultdict(lambda: 1)  # list restarts per (parent, type)
        self.items: list[SourceItem] = []  # the whole document, for look-ahead
        self.pos = 0  # index of the item being parsed
        self.deco: set[str] = set()
        self.margin: dict[int, float] = {}  # page -> left margin of the body text
        self.intro_roman: set[str] = set()  # containers holding a roman list introduced by a text line
        self.notes: list[ParserWarning] = []

    def warn(self, code, message, el=None, item=None, severity="warning"):
        super().warn(code, message, el=el, item=item, severity=severity)
        self.warnings[-1].category = WARNING_CATEGORY.get(code, "needs_review")

    def structure_note(self, code: str, message: str, el: Element | None = None, item: SourceItem | None = None) -> None:
        """A valid structural exception the parser recognised from source evidence: recorded, not a problem."""
        self.notes.append(ParserWarning(code=code, message=message, severity="info", category="valid_structure",
                                        element_id=el.id if el else None, source_ref=item.ref if item else None))  # fmt: skip

    def level(self, el: Element) -> int:
        if el.type == T.ANNEX_HEADING:
            return 2 + (el.number or "").count(".") + 1
        if el.type == T.NUMBERED_POINT:  # "1." < "1.1." < "1.1.1." (dotted points in annexes)
            return LEVELS[T.NUMBERED_POINT] + 0.1 * (el.number or "").count(".")
        return LEVELS.get(el.type, 0)

    def top(self) -> Element:
        return self.stack[-1] if self.stack else self.index[ROOT_ID]


def _is_structural(t: str) -> bool:
    return any(rx.match(t) for rx in (CHAPTER_RX, SECTION_RX, ARTICLE_RX, ANNEX_RX, PART_RX, PARA_RX, NUM_RX,
                                      DOTTED_RX, LETTER_RX, ROMAN_PT_RX, OPENING_RX, ENACTING_RX, FINAL_RX,
                                      RECITALS_INTRO_RX, DONE_AT_RX, PAREN_LETTER_RX))  # fmt: skip


def _is_furniture(it: SourceItem, deco: set[str]) -> bool:
    return it.is_furniture or "furniture_labelled_as_body_by_docling" in it.hygiene_flags or it.ref in deco


def _decorative_pictures(items: list[SourceItem], n_pages: int) -> set[str]:
    """Empty pictures at the same position on many pages (journal page decoration)."""
    pos: dict[tuple[int, int], list[str]] = defaultdict(list)
    for it in items:
        if it.label == "picture" and not it.orig.strip() and it.provenance and it.provenance[0].bbox:
            b = it.provenance[0].bbox
            pos[(round(b.t / 5), round(b.l / 5))].append(it.ref)
    threshold = max(3, int(0.2 * n_pages))
    return {r for refs in pos.values() if len(refs) >= threshold for r in refs}


def _margins(items: list[SourceItem], deco: set[str]) -> dict[int, float]:
    """Left margin of the body text per page (leftmost body item); a page whose margin is far from the
    document's median (e.g. a page with only indented content) uses the median instead."""
    per: dict[int, float] = {}
    for it in items:
        if _is_furniture(it, deco) or it.label in ("footnote", "picture") or it.table is not None:
            continue
        for p in it.provenance:
            if p.bbox is not None:
                per[p.page_no] = min(per.get(p.page_no, p.bbox.l), p.bbox.l)
    if not per:
        return {}
    vals = sorted(per.values())
    median = vals[len(vals) // 2]
    return {pg: (v if abs(v - median) <= 10 else median) for pg, v in per.items()}


def _x_of(b: _EuBuilder, provenance, segment_start: int | None) -> float | None:
    """Indentation (pt from the body margin) of the first line of a text. None if unknown, or if the text is a
    segment inside a merged Docling item (its box is the whole item's, so its own position is not known)."""
    if segment_start:  # > 0: does not start at the item's start
        return None
    p = next((p for p in provenance if p.bbox is not None), None)
    if p is None or p.page_no not in b.margin:
        return None
    return p.bbox.l - b.margin[p.page_no]


def _item_x(b: _EuBuilder, item: SourceItem) -> float | None:
    return _x_of(b, item.provenance, item.span[0] if item.span else None)


def _el_x(b: _EuBuilder, el: Element) -> float | None:
    return _x_of(b, el.provenance, el.source_spans[0].start if el.source_spans else None)


def _next_marker(b: _EuBuilder) -> str | None:
    """The marker of the next lettered/roman point after the current item, if the list is not ended before it
    by a heading or another kind of numbered unit (look-ahead in source order)."""
    for it in b.items[b.pos + 1 : b.pos + 60]:
        if _is_furniture(it, b.deco) or it.label == "footnote":
            continue
        t = it.orig.strip()
        if (m := ROMAN_PT_RX.match(t)) and m.group(1):
            return m.group(1)
        if (m := LETTER_RX.match(t)) or (m := PAREN_LETTER_RX.match(t)):
            return m.group(1)
        if any(rx.match(t) for rx in (ARTICLE_RX, ANNEX_RX, PART_RX, CHAPTER_RX, PARA_RX, NUM_RX, DOTTED_RX)):
            return None
    return None


def _title_line(items: list[SourceItem], i: int, deco: set[str], allow_text: bool) -> int | None:
    """Index of the line that carries the title of the heading at i (EU titles sit on the next line)."""
    j = i + 1
    while j < len(items) and _is_furniture(items[j], deco):
        j += 1
    if j >= len(items):
        return None
    nxt, t = items[j], items[j].orig.strip()
    if not t or _is_structural(t) or nxt.label == "footnote":
        return None
    if nxt.label == "section_header":
        return j
    if allow_text and nxt.label == "text" and len(t) <= 200 and not t.endswith((".", ";", ":")):
        return j
    return None


def parse_eu_items(info, items: list[SourceItem], page_sizes: dict[int, tuple[float, float]]) -> DocumentModel:
    b = _EuBuilder()
    root = b.root
    meta = DocumentMetadata()
    prov: dict[str, list[str]] = {}
    deco = _decorative_pictures(items, max(len(page_sizes), 1))
    zone = "front"
    preamble = conclusions = None
    recitals_started = False
    consumed: set[int] = set()
    furn_counter: dict[tuple[int, str], int] = defaultdict(int)
    b.items, b.deco, b.margin = items, deco, _margins(items, deco)

    def note(field_: str, el: Element) -> None:
        prov.setdefault(field_, []).append(el.id)

    for i, item in enumerate(items):
        if i in consumed:
            continue
        b.pos = i
        t = item.orig.strip()

        # -- furniture: Docling page headers, header lines labelled as text, page decoration ------------
        if _is_furniture(item, deco):
            kind = T.PICTURE if item.label == "picture" else T.PAGE_FOOTER if item.label == "page_footer" or "running_footer" in item.hygiene_flags else T.PAGE_HEADER  # fmt: skip
            page = item.pages[0] if item.pages else 0
            furn_counter[(page, kind.value)] += 1
            el = furniture_element(item, f"furniture/p{page}-{kind.value}-{furn_counter[(page, kind.value)]}", kind)
            if item.ref in deco:
                el.hygiene_flags.append("repeated_page_decoration")
            b.furniture.append(el)
            if page == 1 and kind == T.PAGE_HEADER:
                _publication_meta(meta, el, note)
            continue

        # -- zone transitions -------------------------------------------------------------------------------
        if zone == "front" and OPENING_RX.match(t):
            zone = "preamble"
            preamble = b.add(None, T.PREAMBLE, root, "preamble", local="preamble")
            b.stack = [preamble]
        elif ANNEX_RX.match(t) and zone in ("body", "conclusions", "annex"):
            zone = "annex"
        elif FINAL_RX.match(t) and zone == "body":
            zone = "conclusions"
            conclusions = b.add(None, T.CONCLUSIONS, root, "conclusions", local="conclusions")
            b.stack = [conclusions]

        if item.label == "footnote":
            _footnote(b, item, t)
            continue

        if zone == "front":
            _front(b, item, t, meta, note)
            continue

        if zone == "preamble":
            assert preamble is not None
            if OPENING_RX.match(t):
                b.add(item, T.PREAMBLE_FORMULA, preamble, "preamble", local="formula")
            elif RECITALS_INTRO_RX.match(t):
                b.add(item, T.RECITALS_INTRO, preamble, "preamble", local="recitals-intro")
                recitals_started = True
                b.stack = [preamble]
            elif ENACTING_RX.match(t):
                b.stack = [preamble]
                b.add(item, T.ENACTING_FORMULA, preamble, "preamble", local="enacting-formula")
                zone = "body"
                b.stack = []
            elif not recitals_started:
                b.add(item, T.CITATION, preamble, "preamble", local=b.seq_local(preamble, "citation"))
            elif m := PARA_RX.match(t):
                _numbered(b, item, T.RECITAL, m.group(1), f"({m.group(1)})", m.group(2), "preamble", preamble)
            else:
                _content(b, item, t, "preamble")
            continue

        if zone == "conclusions":
            assert conclusions is not None
            if FINAL_RX.match(t) or DONE_AT_RX.match(t):
                b.add(item, T.FINAL_FORMULA, conclusions, "conclusions", local=b.seq_local(conclusions, "formula"))
            elif item.table is not None:
                b.add(item, T.SIGNATURE, conclusions, "conclusions", local=b.seq_local(conclusions, "signature"))
            else:
                b.add(item, T.TEXT, conclusions, "conclusions", local=b.seq_local(conclusions, "txt"),
                      reasons=["text_in_conclusions_not_classified"])  # fmt: skip
            continue

        region = zone  # "body" or "annex"
        if zone == "body":
            if m := CHAPTER_RX.match(t):
                _heading(b, items, i, consumed, deco, T.CHAPTER, m.group(1), str(roman_value(m.group(1))), region, allow_text=True)  # fmt: skip
                continue
            if m := SECTION_RX.match(t):
                n = m.group(1)
                _heading(b, items, i, consumed, deco, T.SECTION, n, n if n.isdigit() else str(roman_value(n)), region, allow_text=True)  # fmt: skip
                continue
            if m := ARTICLE_RX.match(t):
                _heading(b, items, i, consumed, deco, T.ARTICLE, m.group(1), m.group(1), region, allow_text=True)
                continue
            if (m := PARA_RX.match(t)) and any(e.type == T.ARTICLE for e in b.stack):
                art = next(e for e in reversed(b.stack) if e.type == T.ARTICLE)
                _numbered(b, item, T.ARTICLE_PARAGRAPH, m.group(1), f"({m.group(1)})", m.group(2), region, art)
                continue
        else:
            if (m := ANNEX_RX.match(t)) and m.group(1):
                _heading(b, items, i, consumed, deco, T.ANNEX, m.group(1), str(roman_value(m.group(1))), region, allow_text=True)  # fmt: skip
                continue
            if m := PART_RX.match(t):
                _heading(b, items, i, consumed, deco, T.ANNEX_PART, m.group(1), m.group(1).lower(), region, allow_text=False)  # fmt: skip
                continue
            if (m := PARA_RX.match(t)) and _annex_paragraph_sequence(b, items, i, m.group(1)):
                # "(1) Auf jeder Maschine ... a) ... b) ... (2) Zusätzlich ...": numbered paragraphs inside an annex
                _numbered(b, item, T.ARTICLE_PARAGRAPH, m.group(1), f"({m.group(1)})", m.group(2), region)
                continue
            if m := DOTTED_RX.match(t):
                mk = t[: m.start(2)].strip()  # verbatim, with or without the trailing dot
                if _heading_like(item, m.group(2)):
                    _annex_heading(b, item, m.group(1), m.group(2), marker=mk)
                else:  # "1.1. Sägemaschinen ...;" is a sub-item of point 1, not a heading
                    _dotted_point(b, item, m.group(1), m.group(2), marker=mk)
                continue
            if m := NUM_RX.match(t):
                upper = _heading_like(item, m.group(2), require_upper=True)  # "3. ZUSÄTZLICHE ..." of any length
                if upper or _heading_like(item, m.group(2)):
                    _annex_heading(b, item, m.group(1), m.group(2), [] if upper else ["numbered_line_read_as_heading"], marker=t[: m.start(2)].strip())
                    continue

        if item.table is not None:
            top = b.top()
            b.add(item, T.TABLE, top, region, local=b.seq_local(top, "table"))
            continue
        if m := NUM_RX.match(t):
            h1 = next((e for e in reversed(b.stack) if e.type == T.ANNEX_HEADING and "." not in e.number), None)
            sibling = zone == "annex" and h1 is not None and h1.number.isdigit() and int(m.group(1)) == int(h1.number) + 1
            if sibling:
                b.pop_to_below(b.level(h1))  # "6. Der Hersteller ..." after heading "5. ...": a sibling, not a child
            el = _numbered(b, item, T.NUMBERED_POINT, m.group(1), f"{m.group(1)}.", m.group(2), region)
            if sibling:  # numbered paragraphs and headings share one numbering (conformity modules): verified, valid
                el.hygiene_flags.append("numbered_paragraph_continues_heading_numbering")
                b.structure_note("NUMBERED_PARAGRAPH_CONTINUES_HEADINGS", f"{el.marker} continues the numbering of heading {h1.marker} as a paragraph.", el=el)  # fmt: skip
            continue
        if (m := ROMAN_PT_RX.match(t)) and m.group(1):
            _point(b, item, m.group(1), m.group(2), region)
            continue
        if m := LETTER_RX.match(t):
            _point(b, item, m.group(1), m.group(2), region)
            continue
        if m := PAREN_LETTER_RX.match(t):
            _point(b, item, m.group(1), m.group(2), region, marker=f"({m.group(1)})", reasons=["point_marker_in_parentheses"])
            continue
        if item.label == "section_header":
            top = b.top()
            if zone == "annex":  # an unnumbered sub-title inside an annex: kept as text, flagged
                b.add(item, T.TEXT, top, region, local=b.seq_local(top, "txt"), reasons=["unnumbered_heading_in_annex"])
                b.warn("UNNUMBERED_ANNEX_HEADING", f"Unnumbered heading inside an annex kept as text: {t[:70]!r}", item=item, severity="info")  # fmt: skip
            else:
                b.add(item, T.UNRECOGNIZED, top, region, local=b.seq_local(top, "unrec"), reasons=["unrecognized_section_header"])  # fmt: skip
                b.warn("UNRECOGNIZED_HEADING", f"Section header matches no EU rule: {t[:70]!r}", item=item)
            continue
        _content(b, item, t, region)

    _confirm_numbered_headings(b)
    _sequence_checks(b)
    _link_warnings(b)
    meta.metadata_provenance = prov
    model = DocumentModel(profile=PROFILE, source=info, metadata=meta, root_id=ROOT_ID, elements=b.elements,
                          furniture=b.furniture, warnings=b.warnings, structure_notes=b.notes)  # fmt: skip
    return model  # page furniture is detached by the engine (stage finalize_structure)


def _link_warnings(b: _EuBuilder) -> None:
    """Warnings raised before their element existed carry only the Docling ref: attach the element id."""
    by_ref: dict[str, str] = {}
    for e in b.elements:
        for r in e.source_refs[:1]:
            by_ref.setdefault(r, e.id)
    for w in [*b.warnings, *b.notes]:
        if w.element_id is None and w.source_ref in by_ref:
            w.element_id = by_ref[w.source_ref]


# ---- front matter and metadata ---------------------------------------------------------------------------------
def _front(b: _EuBuilder, item: SourceItem, t: str, meta: DocumentMetadata, note) -> None:
    root = b.index[ROOT_ID]
    if (m := TITLE_RX.match(t)) and meta.document_number is None:
        el = b.add(item, T.DOC_TITLE, root, "front", local="title")
        meta.title, meta.document_type, meta.document_number, meta.issuing_bodies = t, m.group(1), m.group(3), m.group(4)
        for f in ("title", "document_type", "document_number", "issuing_bodies"):
            note(f, el)
        return
    el = b.add(item, T.FRONT_MATTER, root, "front", local=b.seq_local(root, "front"))
    if (m := DATE_RX.match(t)) and meta.adoption_date_text is None and meta.document_number:
        meta.adoption_date_text = t
        note("adoption_date_text", el)
        if m.group(2) in MONTHS:
            meta.adoption_date = date(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1))).isoformat()
            note("adoption_date", el)
    elif meta.adoption_date_text and meta.subject is None and t[:1].islower():
        meta.subject = t
        note("subject", el)
    elif re.fullmatch(r"\(Text von Bedeutung für den EWR\)", t):
        meta.eea_relevance = True
        note("eea_relevance", el)


def _publication_meta(meta: DocumentMetadata, el: Element, note) -> None:
    t = el.original_text.strip()
    if re.fullmatch(r"(ABl\. )?[LC] \d+/\d+", t) and meta.publication_reference is None:
        meta.publication_reference = t
        note("publication_reference", el)
    elif (m := re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", t)) and meta.publication_date_text is None:
        meta.publication_date_text = t
        meta.publication_date = date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        note("publication_date_text", el)
        note("publication_date", el)
    elif t == "Amtsblatt der Europäischen Union" and meta.publication_journal is None:
        meta.publication_journal = t
        note("publication_journal", el)


# ---- headings ----------------------------------------------------------------------------------------------------------
def _heading(b, items, i, consumed, deco, type_: T, printed: str, num: str, region: str, allow_text: bool) -> None:
    item = items[i]
    marker = item.orig.strip()
    j = _title_line(items, i, deco, allow_text)
    absorbed = items[j] if j is not None else None
    if j is not None:
        consumed.add(j)
    merged = [absorbed] if absorbed else []
    if absorbed is not None and type_ == T.ANNEX:
        k = _title_line(items, j, deco, allow_text=False)
        if k is not None and re.fullmatch(r"\([^()]*\)", items[k].orig.strip()):
            merged.append(items[k])
            consumed.add(k)
    title = " ".join(re.sub(r"\s+", " ", x.orig).strip() for x in merged) or None
    reasons: list[str] = []
    untitled_by_layout = False
    if not title:
        untitled_by_layout = _next_line_is_body_text(items, i, deco)
        if not untitled_by_layout:
            b.warn("HEADING_WITHOUT_TITLE", f"{marker!r} has no title line; none invented.", item=item, severity="info")
    b.pop_to_below(LEVELS[type_])
    parent = b.top()
    el = b.add(item, type_, parent, region, local=f"{SLUG[type_]}-{num}", number=printed, marker=marker,
               title=title, content=title or "", reasons=reasons, merge=merged or None)  # fmt: skip
    b.stack.append(el)
    if untitled_by_layout:
        b.structure_note("UNTITLED_HEADING", f"{marker!r} is printed without a title: the next line is body text, not a heading line. No title invented.", el=el)  # fmt: skip


def _next_line_is_body_text(items: list[SourceItem], i: int, deco: set[str]) -> bool:
    """True if the PDF shows that a heading has no title: the next line is running text (not centred like the
    heading, or ending like a sentence/introduction), so it is not a title that the parser failed to take."""
    j = i + 1
    while j < len(items) and _is_furniture(items[j], deco):
        j += 1
    if j >= len(items):
        return False
    head, nxt = items[i], items[j]
    hb = next((p.bbox for p in head.provenance if p.bbox), None)
    nb = next((p.bbox for p in nxt.provenance if p.bbox), None)
    t = nxt.orig.strip()
    if hb is None or nb is None or not t or nxt.label == "section_header" or _is_structural(t):
        return False  # unknown, or another heading follows: nothing to prove
    centred_like_heading = abs((hb.l + hb.r) / 2 - (nb.l + nb.r) / 2) <= 20 and nb.l - hb.l > -INDENT_STEP
    return not centred_like_heading or t.endswith((*SENTENCE_END, ":"))


def _heading_like(item: SourceItem, title: str, require_upper: bool = False) -> bool:
    title = title.strip()
    if require_upper:  # "1. GRUNDLEGENDE ..." is a heading, "1. Der Hersteller ..." is a point
        letters = [c for c in title if c.isalpha()]
        return bool(letters) and all(c.isupper() for c in letters)
    return len(title) <= 160 and not title.endswith((".", ";", ",", ":"))


def _annex_heading(b: _EuBuilder, item: SourceItem, number: str, title: str, reasons: list[str] | None = None,
                   marker: str | None = None) -> None:  # fmt: skip
    depth = number.count(".") + 1
    b.pop_to_below(2 + depth)
    parent = b.top()
    reasons = list(reasons or [])
    if parent.type == T.ANNEX_HEADING and not number.startswith(parent.number + "."):
        reasons.append("heading_number_does_not_continue_parent")
        b.warn("ANNEX_HEADING_NUMBERING", f"Heading {number} under {parent.number}.", item=item)
    el = b.add(item, T.ANNEX_HEADING, parent, "annex", local=f"h-{number}", number=number, marker=marker or f"{number}.",
               title=re.sub(r"\s+", " ", title).strip(), content=title.strip(), reasons=reasons)  # fmt: skip
    b.stack.append(el)


def _dotted_point(b: _EuBuilder, item: SourceItem, number: str, content: str, marker: str | None = None) -> None:
    level = LEVELS[T.NUMBERED_POINT] + 0.1 * number.count(".")
    b.pop_to_below(level)
    parent = b.top()
    reasons = []
    prefix = number.rsplit(".", 1)[0]
    if parent.number != prefix:
        reasons.append("dotted_number_does_not_continue_parent")
    _numbered(b, item, T.NUMBERED_POINT, number, marker or f"{number}.", content, "annex", parent, reasons, level=level)


# ---- numbered units ------------------------------------------------------------------------------------------------------
def _numbered(b, item, type_: T, number: str, marker: str, content: str, region: str, parent: Element | None = None,
              reasons: list[str] | None = None, level: float | None = None) -> Element:  # fmt: skip
    b.pop_to_below(level if level is not None else LEVELS[type_])
    if parent is None or (parent not in b.stack and parent.type not in (T.PREAMBLE,)):
        parent = b.top()
    # a list that starts again under the same parent (after intervening text) gets its own run in the id
    probe = Element(id="", type=type_, region="body", number=number)
    prev = [b.index[c] for c in parent.children_ids if b.index[c].type == type_]
    if prev and _key(probe) is not None and _key(prev[-1]) is not None and _key(probe) <= _key(prev[-1]):
        b.runs[(parent.id, type_)] += 1
    run = b.runs[(parent.id, type_)]
    local = f"{SLUG[type_]}-{number}" if run == 1 else f"run{run}-{SLUG[type_]}-{number}"
    el = b.add(item, type_, parent, region, local=local, number=number, marker=marker,
               content=content.strip(), reasons=list(reasons or []))  # fmt: skip
    b.stack.append(el)
    return el


def _annex_paragraph_sequence(b: _EuBuilder, items: list[SourceItem], i: int, number: str) -> bool:
    """"(n)" in an annex is a numbered paragraph only as part of a sequence: "(1)" if "(2)" follows in the
    same section (before the next heading), "(n)" if paragraph n-1 is open. A lone "(1)" stays text."""
    if not number.isdigit():
        return False
    n = int(number)
    if n > 1:
        return any(e.type == T.ARTICLE_PARAGRAPH and e.number == str(n - 1) for e in b.stack)
    for it in items[i + 1 : i + 200]:
        if _is_furniture(it, b.deco) or it.label == "footnote":
            continue
        t = it.orig.strip()
        if t.startswith("(2) "):
            return True
        if any(rx.match(t) for rx in (ANNEX_RX, PART_RX, DOTTED_RX)) or (NUM_RX.match(t) and it.label == "section_header"):
            return False
    return False


def _roman_or_letter_by_evidence(b: _EuBuilder, item: SourceItem, marker_value: str, last_pt: Element | None) -> str | None:
    """Decide an "i)", "v)" or "x)" that could continue the letters or open/continue a roman list:
    the next point marker ("j)" -> letters, "ii)" -> roman) and the indentation against the letter list
    (same column -> letters, indented -> nested roman list). Returns "alpha", "roman" or None (conflicting
    or no evidence: stays ambiguous)."""
    votes: set[str] = set()
    nxt = _next_marker(b)
    if nxt is not None:
        if nxt == chr(ord(marker_value) + 1) and not ROMAN_PT_RX.match(f"{nxt}) x"):
            votes.add("alpha")
        elif ROMAN_PT_RX.match(f"{nxt}) x") and roman_value(nxt) == roman_value(marker_value) + 1:
            votes.add("roman")
    x, lx = _item_x(b, item), (_el_x(b, last_pt) if last_pt is not None else None)
    if x is not None and lx is not None:
        if abs(x - lx) <= INDENT_TOL:
            votes.add("alpha")
        elif x - lx >= INDENT_STEP:
            votes.add("roman")
    return votes.pop() if len(votes) == 1 else None


def _introduced_by_text(b: _EuBuilder, item: SourceItem) -> Element | None:
    """A roman list that a text line introduces ("... folgenden Bedingungen erfüllen:", "... zumindest"):
    the last element of the current container is such a text, at the same indentation as the list."""
    top = b.top()
    prev = b.index[top.children_ids[-1]] if top.children_ids else None
    if prev is None or prev.type != T.TEXT:
        return None
    if prev.content_text.rstrip().endswith(SENTENCE_END):  # a complete sentence does not introduce a list
        return None
    x, px = _item_x(b, item), _el_x(b, prev)
    if x is None or px is None or not (-INDENT_TOL <= x - px <= INDENT_STEP):
        return None
    return prev


def _point(b: _EuBuilder, item: SourceItem, marker_value: str, content: str, region: str,
           marker: str | None = None, reasons: list[str] | None = None) -> None:  # fmt: skip
    """a) is a POINT, i) a SUBPOINT; "i", "v", "x" are decided by the open lists, the next marker and the
    indentation (see _roman_or_letter_by_evidence)."""
    open_pt = next((e for e in reversed(b.stack) if e.type == T.POINT), None)
    open_sub = next((e for e in reversed(b.stack) if e.type == T.SUBPOINT), None)
    closed_pt = None
    if open_pt is None:  # a list interrupted by text in the same container ("u)", text, text, "v)")
        top = b.top()
        kids = [b.index[c] for c in top.children_ids]
        closed_pt = next((k for k in reversed(kids) if k.type == T.POINT), None)
    if open_sub is not None and open_pt is not None and b.stack.index(open_sub) < b.stack.index(open_pt):
        open_sub = None  # that roman list belongs to an earlier point
    is_roman = bool(ROMAN_PT_RX.match(f"{marker_value}) x"))
    last_pt = open_pt or closed_pt
    alpha_next = chr(ord(last_pt.number) + 1) if last_pt is not None and len(last_pt.number) == 1 else "a"
    reasons = list(reasons or [])
    flags: list[str] = []
    note: tuple[str, str] | None = None
    if is_roman and len(marker_value) > 1:
        type_ = T.SUBPOINT  # "ii)", "iv)": no such letter
    elif is_roman:
        roman_continues = open_sub is not None and roman_value(marker_value) == roman_value(open_sub.number) + 1
        roman_starts = marker_value == "i" and open_pt is not None
        alpha_continues = marker_value == alpha_next
        if (roman_continues or roman_starts) and alpha_continues:
            decided = _roman_or_letter_by_evidence(b, item, marker_value, last_pt)
            if decided is None:
                type_ = T.SUBPOINT if roman_continues else T.POINT
                reasons.append("roman_or_alphabetic_ambiguous")
                b.warn("ROMAN_ALPHA_AMBIGUOUS", f"'{marker_value})' could continue the letters or the roman list; read as {type_.value}.", item=item, severity="info")  # fmt: skip
            else:  # source evidence (next marker / indentation) decides
                type_ = T.POINT if decided == "alpha" else T.SUBPOINT
                flags.append(f"point_kind_decided_by_layout:{decided}")
        elif roman_continues or roman_starts:
            type_ = T.SUBPOINT
        elif alpha_continues:
            type_ = T.POINT
        elif marker_value == "i" and (intro := _introduced_by_text(b, item)) is not None:
            type_ = T.SUBPOINT  # a new roman list introduced by the preceding text line: valid structure
            flags.append("roman_list_introduced_by_text")
            b.intro_roman.add(b.top().id)
            note = ("ROMAN_LIST_INTRODUCED_BY_TEXT", f"'i)' starts a roman list introduced by the text {intro.id}.")
        else:
            type_ = T.SUBPOINT if marker_value == "i" else T.POINT
            reasons.append("point_sequence_unclear")
            b.warn("POINT_SEQUENCE", f"'{marker_value})' continues neither the letters nor a roman list.", item=item)
    else:
        type_ = T.POINT
    if "point_marker_in_parentheses" in reasons and type_ == T.POINT and last_pt is not None and marker_value == alpha_next \
            and _next_marker(b) == chr(ord(marker_value) + 1):  # fmt: skip
        reasons.remove("point_marker_in_parentheses")  # "k)", "(l)", "m)": the letter sequence confirms it
        flags.append("point_marker_in_parentheses")
        note = ("PARENTHESISED_POINT_MARKER", f"'({marker_value})' is printed with parentheses; the sequence {last_pt.number}) … {chr(ord(marker_value) + 1)}) confirms the point.")  # fmt: skip
    if type_ == T.POINT and closed_pt is not None and marker_value == alpha_next and marker_value != "a":
        top = b.top()
        between = [b.index[c] for c in top.children_ids[top.children_ids.index(closed_pt.id) + 1 :]]
        for e in between:  # text between two points of one list: probably sub-paragraphs of the earlier point
            if e.type == T.TEXT and "text_between_points_of_one_list" not in e.uncertainty_reasons:
                e.uncertain = True
                e.uncertainty_reasons.append("text_between_points_of_one_list")
        if between:
            b.warn("LIST_INTERRUPTED", f"Point list continues with '{marker_value})' after {len(between)} unnumbered item(s) under {top.id}.", item=item, severity="info")  # fmt: skip
    introduced = "roman_list_introduced_by_text" in flags or (open_sub is not None and open_sub.parent_id in b.intro_roman)
    if type_ == T.SUBPOINT and open_pt is None and not introduced and not any(e.type == T.NUMBERED_POINT for e in b.stack):
        reasons.append("subpoint_without_enclosing_point")
    el = _numbered(b, item, type_, marker_value, marker or f"{marker_value})", content, region, reasons=reasons)
    el.hygiene_flags += [f for f in flags if f not in el.hygiene_flags]
    if note:
        b.structure_note(note[0], note[1], el=el)


# ---- unnumbered text and footnotes ------------------------------------------------------------------------------------------
def _content(b: _EuBuilder, item: SourceItem, t: str, region: str) -> None:
    if _place_text_by_indentation(b, item, region):
        return
    _content_without_layout(b, item, t, region)


def _place_text_by_indentation(b: _EuBuilder, item: SourceItem, region: str) -> bool:
    """Place running text after a point by its indentation (Official Journal layout):
    - right of an open point's marker column (by >= INDENT_STEP): a body paragraph of that point;
    - at the marker column of the open list(s) (within INDENT_TOL): the list has ended, the text belongs to
      the enclosing unit (an introductory or closing text).
    Returns False (caller falls back to the text-only rules) when a position is unknown or in between."""
    if b.top().type not in POINT_TYPES:
        return False
    x = _item_x(b, item)
    if x is None:
        return False
    stack = list(b.stack)
    while stack and stack[-1].type in POINT_TYPES:
        px = _el_x(b, stack[-1])
        if px is None:
            return False
        if x >= px + INDENT_STEP:  # indented beyond this point's marker: its body text
            host, flag = stack[-1], "attached_by_indentation"
            break
        if abs(x - px) <= INDENT_TOL or x < px:  # at (or left of) the marker column: this list has ended
            stack.pop()
            continue
        return False  # between the columns: no layout evidence either way
    else:
        host, flag = (stack[-1] if stack else b.index[ROOT_ID]), "container_text_by_indentation"
    b.stack = stack
    el = b.add(item, T.TEXT, host, region, local=b.seq_local(host, "txt"), reasons=[])
    el.hygiene_flags.append(flag)
    return True


def _content_without_layout(b: _EuBuilder, item: SourceItem, t: str, region: str) -> None:
    reasons: list[str] = []
    top = b.top()
    if top.type in (T.POINT, T.SUBPOINT):
        last = top.original_text.rstrip()
        b.pop_to_below(LEVELS[T.NUMBERED_POINT] if any(e.type == T.NUMBERED_POINT for e in b.stack) and False else LEVELS[T.POINT])  # fmt: skip
        while b.stack and b.stack[-1].type in (T.POINT, T.SUBPOINT):
            b.stack.pop()
        if t[:1].islower():
            reasons.append("lowercase_text_after_points")
        elif not last.endswith((".", ":", "!", "?")):
            reasons.append("text_after_unterminated_point")
    elif top.type == T.NUMBERED_POINT and top.children_ids:
        reasons.append("text_after_numbered_point_attached_to_it")
    elif top.type == T.NUMBERED_POINT:
        reasons.append("text_after_numbered_point_attached_to_it")
    parent = b.top()
    b.add(item, T.TEXT, parent, region, local=b.seq_local(parent, "txt"), reasons=reasons)


def _footnote(b: _EuBuilder, item: SourceItem, t: str) -> None:
    m = re.match(r"^\(\s*(\d+)\s*\)", t)
    num = m.group(1) if m else None
    page = item.pages[0] if item.pages else None
    anchor = None
    if num is not None:
        ref_rx = re.compile(rf"\(\s+{num}\s+\)")
        for e in reversed(b.elements):
            if e.type != T.FOOTNOTE and page in e.pages and ref_rx.search(e.original_text):
                anchor = e
                break
    reasons = []
    if anchor is None:
        anchor = b.top()
        reasons.append("footnote_reference_not_found_on_page")
        b.warn("FOOTNOTE_ANCHOR_NOT_FOUND", f"No '( {num} )' reference on page {page}; footnote kept under {anchor.id}.", item=item)  # fmt: skip
    b.add(item, T.FOOTNOTE, anchor, anchor.region if anchor.region != "document" else "body",
          local=f"fn-{num or 'x'}", number=num, marker=m.group(0) if m else None, reasons=reasons)  # fmt: skip


# ---- numbered headings: confirmation by document structure -----------------------------------------------------------------
def _confirm_numbered_headings(b: _EuBuilder) -> None:
    """A short numbered line read as a heading ("2. Technische Dokumentation") is confirmed when
    (a) its number prefixes the dotted sub-items below it ("4." -> "4.1."), or
    (b) it is a sibling of a heading confirmed by (a), in the same column, and the shared numbering of the
        numbered siblings (headings and paragraphs) runs without a gap.
    Otherwise the reason stays: a numbered list item could look the same."""
    reason = "numbered_line_read_as_heading"
    cands = [e for e in b.elements if e.type == T.ANNEX_HEADING and reason in e.uncertainty_reasons]
    if not cands:
        return

    def has_sub(e: Element) -> bool:
        todo = list(e.children_ids)
        while todo:
            k = b.index[todo.pop()]
            if k.type in (T.NUMBERED_POINT, T.ANNEX_HEADING) and (k.number or "").startswith(f"{e.number}."):
                return True
            todo += k.children_ids
        return False

    confirmed = {e.id: "sub_numbering" for e in cands if has_sub(e)}
    by_parent: dict[str, list[Element]] = defaultdict(list)
    for e in cands:
        by_parent[e.parent_id].append(e)
    for pid, group in by_parent.items():
        anchors = [e for e in group if e.id in confirmed]
        if not anchors:
            continue
        numbered = [b.index[c] for c in b.index[pid].children_ids if b.index[c].type in (T.ANNEX_HEADING, T.NUMBERED_POINT)]
        keys = [_key(e) for e in numbered]
        continuous = all(k is not None for k in keys) and keys == list(range(keys[0], keys[0] + len(keys)))
        ax = [_el_x(b, a) for a in anchors]
        for e in group:
            ex = _el_x(b, e)
            same_column = ex is not None and any(a is not None and abs(ex - a) <= INDENT_TOL for a in ax)
            if e.id not in confirmed and continuous and same_column:
                confirmed[e.id] = "sibling_headings"
    for e in cands:
        if e.id in confirmed:
            e.uncertainty_reasons.remove(reason)
            e.uncertain = bool(e.uncertainty_reasons)
            e.hygiene_flags.append(f"numbered_heading_confirmed_by:{confirmed[e.id]}")


# ---- sequence checks -----------------------------------------------------------------------------------------------------------
def _key(e: Element) -> int | None:
    n = e.number or ""
    if e.type in (T.CHAPTER, T.ANNEX) or (e.type == T.SECTION and not n.isdigit()):
        return roman_value(n)
    if e.type == T.SUBPOINT:
        return roman_value(n)
    if e.type == T.POINT and len(n) == 1:
        return ord(n) - ord("a") + 1
    if e.type == T.ANNEX_PART and len(n) == 1 and n.isalpha():
        return ord(n) - ord("A") + 1
    m = re.match(r"^(\d+)", n.split(".")[-1])
    return int(m.group(1)) if m else None


def _sequence_checks(b: _EuBuilder) -> None:
    def check(group: list[Element], label: str, start_at_one: bool = True) -> None:
        prev = None
        prev_type = None
        for e in group:
            k = _key(e)
            exp = 1 if prev is None else prev + 1
            if k == 1 and prev is not None and e.id.rsplit("/", 1)[-1].startswith("run"):
                prev = k  # a restarted list (its own run id), not a break
                continue
            if k == 1 and prev is not None and prev_type is not None and e.type != prev_type:
                # another kind of numbered unit starts its own numbering (paragraphs 1-5, then headings 1-6)
                b.structure_note("NEW_NUMBERED_SEQUENCE", f"{e.marker} starts a new {e.type.value} sequence after {prev} numbered {prev_type.value}(s) under {e.parent_id}.", el=e)  # fmt: skip
                prev, prev_type = k, e.type
                continue
            prev_type = e.type
            if k is not None and (k != exp) and (prev is not None or start_at_one):
                e.uncertain = True
                e.uncertainty_reasons.append(f"{label}_sequence_break")
                b.warn("SEQUENCE_BREAK", f"{e.marker}: expected number {exp} in {label} sequence (parent {e.parent_id}).", el=e)  # fmt: skip
            prev = k if k is not None else prev

    for t in (T.RECITAL, T.ARTICLE, T.CHAPTER, T.ANNEX):
        check([e for e in b.elements if e.type == t], t.value)
    by_parent: dict[tuple[str, str], list[Element]] = defaultdict(list)
    for e in b.elements:
        if e.type in (T.ANNEX_HEADING, T.NUMBERED_POINT):
            # numbered headings and numbered paragraphs share one numbering inside an annex
            by_parent[(e.parent_id, "numbered")].append(e)
        elif e.type in (T.ARTICLE_PARAGRAPH, T.POINT, T.SUBPOINT, T.ANNEX_PART, T.SECTION):
            by_parent[(e.parent_id, e.type.value)].append(e)
    for (_, label), group in by_parent.items():
        check(group, label)
