"""Text that runs on over a page break: one decision rule for every legal profile.

A page break is a layout event, not a legal boundary. When the text of a unit (Absatz, Nummer, Buchstabe, EU
paragraph or point, an unnumbered text block, ...) is cut by the page end, Docling delivers its tail as a separate
item on the next page. A recognizer that finds such an item without a legal marker asks `assess` whether it is
the continuation of the element that was open at the end of the previous page, and `StructureBuilder.extend`
then appends it to that element: one element with its complete own text and every page that carries it.

No single signal decides. A continuation needs all of the following, and a veto from any one keeps the item
a separate (flagged) element:

* structure: the open element is a text-bearing unit or text block that has no child yet, and nothing structural
  stands between it and the item (the caller checks the builder's stack);
* page boundary: the item starts on a later page than the open element ends on;
* no legal marker: the item is plain text (no "(2)", "3.", "b)", heading, Satz number ...; the profile's
  `is_marker` decides) and not a table, picture or footnote;
* intact source: the item's own segmentation and reading order are not in doubt (`boundary_flags`, `order_flags`);
* geometry (where the PDF page sizes are known): the open element ends in the lower part of its page and the
  item starts in the upper part of the next one;
* text: the open element is not closed (no sentence end, colon or semicolon; abbreviations like "Abs." do not
  close it) AND the item either starts in lowercase, or the open element ends in a clearly unfinished phrase
  (comma, hyphen, dangling article/preposition/conjunction) or is a sentence-sized text that stops without any
  sentence end, and the geometry confirms the page boundary.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass, field

from odos.document_model import Element
from odos.normalization.docling_reader import SourceItem

FLAG = "page_break_continuation_merged_confirmed"  # on the element that received the continuation
HYPHEN_FLAG = "page_break_line_end_hyphen_kept"
NOTE_FLAG = "page_foot_note_labelled_as_body_by_docling"  # a note left separate between a text and its continuation

# an item with one of these Docling labels is never body text that continues a sentence
NOT_RUNNING_TEXT = {"section_header", "title", "table", "picture", "footnote", "caption", "formula", "code", "page_header", "page_footer"}  # fmt: skip

# geometry: the open element's box ends within this share of the page height from the bottom edge, the next
# item's box starts within this share from the top edge (MBO, BDSG: the foot ends at <= 15 %, the head starts at >= 92 %)
BOTTOM_SHARE = 0.30
TOP_SHARE = 0.20

MIN_WORDS_UNTERMINATED = 5  # a text this long that stops without any sentence end was cut off, not finished
CLOSING = ".!?:;"
QUOTES = "\"'“”„‚‘’»«)]"
# a final "." that does not end the sentence
ABBREVIATIONS = frozenset({
    "abs", "art", "nr", "nrn", "bzw", "ggf", "vgl", "ca", "usw", "etc", "evtl", "inkl", "sog", "bspw", "ff", "str",
    "dr", "prof", "bes", "insb", "ggfs", "max", "min", "mind", "lfd", "gem", "zzgl", "abschn", "anh", "anl", "buchst",
    "s", "u", "a", "b", "h", "m", "o", "ä", "v", "z", "t", "i", "d", "e", "g", "k", "l", "w",
})  # fmt: skip
# words that cannot end a sentence: articles, prepositions, conjunctions, auxiliaries ("... und", "... von")
DANGLING = frozenset({
    "und", "oder", "sowie", "bzw", "sondern", "aber", "denn", "als", "wie", "wenn", "dass", "ob", "weil", "soweit",
    "sofern", "falls", "während", "bevor", "nachdem", "damit", "indem", "von", "vom", "zu", "zum", "zur", "bei",
    "beim", "mit", "nach", "aus", "auf", "an", "am", "in", "im", "für", "über", "unter", "vor", "durch", "gegen",
    "ohne", "um", "bis", "seit", "neben", "zwischen", "gemäß", "nach", "entsprechend", "der", "die", "das", "des",
    "dem", "den", "ein", "eine", "einer", "eines", "einem", "einen", "diese", "dieser", "dieses", "diesem",
    "diesen", "jede", "jeder", "jedes", "jedem", "jeden", "nicht", "auch", "nur", "sich", "ist", "sind", "wird",
    "werden", "kann", "können", "muss", "müssen", "darf", "dürfen", "soll", "sollen", "hat", "haben", "sein",
    "je", "so", "zwar", "et", "and", "or", "of", "the", "to", "in",
})  # fmt: skip
# a page-bottom note that Docling labelled as body text ("2 nach Landesrecht", "* ...", "¹ ..."): not running text
FOOTNOTE_LIKE = re.compile(r"^(?:\d{1,2}|\*{1,3}|[¹²³⁴⁵⁶⁷⁸⁹⁰]+)\)?\s+[a-zäöüß]")
NOTE_MARK = re.compile(r"^(\d{1,2}|\*{1,3})\)?\s+\S")  # a note's own leading mark (a number, or asterisks)
MAX_NOTE_CHARS = 160  # a lone note this short
NOTE_TYPES = ("text", "unmarked_list_item")  # element types a note Docling labelled as body text becomes
LAST_WORD = re.compile(r"([^\W\d_]+)[\s,;]*$", re.U)


@dataclass
class Verdict:
    merge: bool
    evidence: list[str] = field(default_factory=list)  # why it is a continuation
    vetoes: list[str] = field(default_factory=list)  # why it is not (or may not be treated as one)


def _tail(text: str) -> str:
    """The text without trailing whitespace and closing quotes/brackets."""
    return text.rstrip().rstrip(QUOTES).rstrip()


def _first_letter(text: str) -> str:
    for ch in text.lstrip(" \t\n\"'“„‚‘»«([-–"):
        return ch
    return ""


def starts_lowercase(text: str) -> bool:
    ch = _first_letter(text)
    return ch.isalpha() and ch.islower()


def _is_closed(text: str) -> bool:
    """The text ends its sentence (or introduces a list): ". ! ? : ;", not counting abbreviations."""
    t = _tail(text)
    if not t:
        return True
    last = t[-1]
    if last not in CLOSING:
        return False
    if last == ".":
        m = re.search(r"([^\W\d_]+)\.$", t, re.U)
        if m and (m.group(1).lower() in ABBREVIATIONS or len(m.group(1)) == 1):
            return False
    return True


def _open_phrase(text: str) -> str | None:
    """Why the text ends in an unfinished phrase: 'comma', 'hyphen' or 'dangling_word'."""
    t = _tail(text)
    if t.endswith(","):
        return "comma"
    if t.endswith(("-", "‐", "–", "\xad")):
        return "hyphen"
    m = LAST_WORD.search(t)
    if m and m.group(1).lower() in DANGLING and not t.endswith(tuple(CLOSING)):
        return "dangling_word"
    return None


def _edge(prov, page_sizes: dict[int, tuple[float, float]]) -> tuple[float, float] | None:
    """(top, bottom) of a box as the distance in points from the page's bottom edge, or None if unknown."""
    if prov is None or prov.bbox is None or prov.page_no not in page_sizes:
        return None
    b, h = prov.bbox, page_sizes[prov.page_no][1]
    top, bottom = (b.t, b.b) if b.coord_origin.upper().startswith("BOTTOM") else (h - b.t, h - b.b)
    return max(top, bottom), min(top, bottom)


def _geometry(prev: Element, item: SourceItem, page_sizes: dict[int, tuple[float, float]] | None) -> bool | None:
    """True: the box of `prev` ends low on its page and the box of `item` starts high on its page; False: it does
    not; None: the boxes or page sizes are unknown (no evidence either way)."""
    if not page_sizes or not prev.provenance or not item.provenance:
        return None
    last = max(prev.provenance, key=lambda p: p.page_no)
    first = min(item.provenance, key=lambda p: p.page_no)
    below, above = _edge(last, page_sizes), _edge(first, page_sizes)
    if below is None or above is None:
        return None
    return below[1] <= BOTTOM_SHARE * page_sizes[last.page_no][1] and above[0] >= (1 - TOP_SHARE) * page_sizes[first.page_no][1]  # fmt: skip


def trailing_notes(recent: Iterable[Element], page_sizes: dict[int, tuple[float, float]] | None) -> tuple[list[Element], Element | None]:
    """Split off the page-foot notes that Docling labelled as body text from the end of the body.

    `recent` is the body in reverse document order. The notes are the maximal trailing run of unnumbered text
    elements that each start with their own mark (a number, or asterisks), sit within the foot zone of one page, are
    numbered consecutively in document order (or are all asterisk notes), and below a host that ends on that same
    page. Anything less certain is not a note: the run is empty and the host is simply the last element. Returns the
    notes in document order and the host (the element right before them, None if the body ends)."""
    run: list[Element] = []
    first: Element | None = None  # the last body element, whatever it is
    host: Element | None = None
    for el in recent:
        first = first or el
        if (el.type.value in NOTE_TYPES and len(el.pages) == 1 and NOTE_MARK.match(el.original_text.strip())
                and _in_foot_zone(el, page_sizes) and (not run or el.pages == run[-1].pages)):  # fmt: skip
            run.append(el)
            continue
        host = el
        break
    run.reverse()
    marks = [NOTE_MARK.match(e.original_text.strip()).group(1) for e in run]
    consecutive = all(m.isdigit() for m in marks) and all(int(y) == int(x) + 1 for x, y in zip(marks, marks[1:]))
    stars = all(m.startswith("*") for m in marks)
    # one numbered line at a page foot is as likely a Satz-numbered text block ("2 Satz 1 gilt ...") as a note: only a
    # short note that opens the page's notes (mark 1 or asterisks) counts alone, longer runs must be consecutive
    alone = len(run) != 1 or (marks[0] in ("1",) or marks[0].startswith("*")) and len(run[0].original_text) <= MAX_NOTE_CHARS
    if run and alone and (consecutive or stars) and host is not None and host.pages and host.pages[-1] == run[0].pages[0]:
        return run, host
    return [], first


def _in_foot_zone(el: Element, page_sizes: dict[int, tuple[float, float]] | None) -> bool:
    if not page_sizes or not el.provenance:
        return False
    prov = el.provenance[-1]
    edge = _edge(prov, page_sizes)
    return edge is not None and edge[1] <= BOTTOM_SHARE * page_sizes[prov.page_no][1]


def assess(prev: Element, item: SourceItem, page_sizes: dict[int, tuple[float, float]] | None,
           is_marker: Callable[[str], bool], notes: Collection[str] = ()) -> Verdict:
    """Whether `item` continues the text of `prev`. The caller has already established that `prev` is the open
    text-bearing element (see the module docstring); this function weighs the evidence in the item and its source."""
    v = Verdict(merge=False)
    text = item.orig.strip()
    if not prev.pages or not item.pages or item.pages[0] <= prev.pages[-1]:
        v.vetoes.append("not_on_a_later_page")
    if any(c not in notes for c in prev.children_ids):  # page-foot notes between the text and the page break are not children of its own text  # fmt: skip
        v.vetoes.append("open_element_has_children")
    if FOOTNOTE_LIKE.match(text):
        v.vetoes.append("item_looks_like_a_footnote")
    if not text or item.label in NOT_RUNNING_TEXT or item.table is not None or item.is_furniture:
        v.vetoes.append("not_running_text")
    if is_marker(text):
        v.vetoes.append("starts_with_legal_marker")
    if item.boundary_flags or item.order_flags:
        v.vetoes.append("source_segmentation_or_order_uncertain")
    if FOOTNOTE_LIKE.match(prev.original_text.strip()):
        v.vetoes.append("open_element_looks_like_a_footnote")
    if re.fullmatch(r"\W*\d+\W*", prev.original_text):
        v.vetoes.append("open_element_is_a_bare_number")  # a page number no running-furniture rule has caught
    if _is_closed(prev.original_text):
        v.vetoes.append("open_element_ends_its_sentence")
    geometry = _geometry(prev, item, page_sizes)
    if geometry is False:
        v.vetoes.append("not_at_page_boundary_by_geometry")
    if v.vetoes:
        return v
    lower, phrase = starts_lowercase(text), _open_phrase(prev.original_text)
    unterminated = len(prev.content_text.split()) >= MIN_WORDS_UNTERMINATED  # a sentence-sized text with no end at all
    if geometry:
        v.evidence.append("geometry_page_end_to_page_start")
    if lower:
        v.evidence.append("starts_lowercase")
    if phrase:
        v.evidence.append(f"open_end:{phrase}")
    elif unterminated:
        v.evidence.append("no_sentence_end")
    v.merge = lower or (bool(geometry) and (phrase is not None or unterminated))
    if not v.merge:
        v.vetoes.append("no_text_evidence")
    return v


def ends_with_hyphen(el: Element) -> bool:
    return _tail(el.content_text).endswith(("-", "‐", "\xad"))
