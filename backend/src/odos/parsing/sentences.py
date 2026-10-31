"""Legal sentences as logical references to ordered text ranges (the canonical text is never copied or changed).

A sentence belongs to a unit (German Absatz, a § without Absätze; EU article paragraph, an article without
paragraphs, a recital) and consists of ranges ``[start, end)`` of Python ``str`` indices (Unicode code points)
into the ``content_text`` of the unit's elements in document order. Each range records the SHA-256 of the
``content_text`` it was computed on, so a consumer can tell when a range no longer fits (after a correction).

Two methods, never mixed within a unit:

* ``printed_number``: the PDF prints Satz numbers as superscripts. Every mark classified ``sentence_number``
  (``source_marks``) inside the unit's boxes must match a number at a sentence start in the text, in order, and the
  numbers must run 1, 2, 3, ... A sentence runs from its number to the next one, across list items and the text
  after a list. Any mismatch: the unit gets no sentences and a warning.
* ``punctuation``: units without printed numbers. A boundary is ".", "!" or "?" before whitespace and a capital
  letter / "„" / "(" , never after a legal abbreviation ("Abs.", "Nr.", "z. B.", ...), a date or an ordinal; a
  boundary candidate that cannot be decided (e.g. after a number or a single letter) leaves the whole unit
  unsegmented. Inside list items no boundary is accepted: the list belongs to the sentence that introduces it.

``number`` is only ever the printed number, never a position.
"""

from __future__ import annotations

import hashlib
import re

from odos.normalization.lang_de import ABBREVIATIONS, MONTHS_LOWER as MONTHS, SHORT_WORDS, UNITS
from odos.document_model import BoundingBox, DocumentModel, Element, ElementType as T, ParserWarning, Sentence, SentenceRange
from odos.parsing.profiles import for_model
from odos.normalization.source_marks import classify
from odos.parsing.footnotes import mark_owner, marks_on_page

# which elements are units and which are list items is the profile's (`sentence_units`, `list_types`)
NOT_TEXT = {T.FOOTNOTE, T.FOOTNOTE_HEADING, T.TABLE, T.PICTURE, T.PAGE_HEADER, T.PAGE_FOOTER}

BOUNDARY = re.compile(r"[.!?][“”\"')\]]?(?=\s+[„\"(]?[A-ZÄÖÜ§])")
NUMBER_AT_START = re.compile(r"(\d{1,2}) (?=[A-ZÄÖÜ§\[„(\"])")
SENTENCE_START_BEFORE = ".:;!?)]“”\"["  # "[" : a bracketed (optional) sentence "[2 Werden ...]"


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _own(el: Element) -> str:
    if el.type in NOT_TEXT or (el.title is not None and el.content_text == el.title):
        return ""
    return el.content_text


def units(model: DocumentModel) -> list[Element]:
    profile = for_model(model)
    whole = profile.units_if_no_subunits
    index = model.by_id()
    out = []
    for e in model.elements:
        if e.region not in ("body", "preamble", "annex", "conclusions"):
            continue
        if e.type in profile.sentence_units:
            out.append(e)
        elif e.type in whole and not any(index[c].type == whole[e.type] for c in e.children_ids):
            out.append(e)
    return out


def sequence(model: DocumentModel, unit: Element) -> list[Element]:
    """The unit's text-bearing elements in document order (the unit itself, its list items, texts after lists)."""
    index = model.by_id()
    out, stack = [], [unit.id]
    while stack:
        e = index[stack.pop()]
        if e.type in NOT_TEXT:
            continue
        out.append(e)
        stack.extend(reversed(e.children_ids))
    return out


def _ranges(seq: list[Element], starts: list[tuple[int, int]], unit_end: tuple[int, int]) -> list[list[SentenceRange]]:
    """Split the unit text at the given (element index, offset) starts; each sentence ends before the next start."""
    out = []
    bounds = [*starts, unit_end]
    for (ei, eo), (fi, fo) in zip(bounds, bounds[1:]):
        rs = []
        for i in range(ei, fi + 1):
            text = _own(seq[i])
            s = eo if i == ei else 0
            e = fo if i == fi else len(text)
            while e > s and text[e - 1].isspace():
                e -= 1
            while s < e and text[s].isspace():
                s += 1
            if s < e:
                rs.append(SentenceRange(element_id=seq[i].id, start=s, end=e, text_sha256=_sha(text)))
        out.append(rs)
    return out


def _number_candidates(text: str) -> list[tuple[int, str]]:
    out = []
    for m in NUMBER_AT_START.finditer(text):
        p = m.start()
        if p > 0 and not text[p - 1].isspace() and text[p - 1] not in "[(":
            continue
        before = text[:p].rstrip()
        if before and before[-1] not in SENTENCE_START_BEFORE and not re.search(r"\]\s*\d+$|[A-Za-zäöüß)]\s+\d+$", before):
            continue
        out.append((p, m.group(1)))
    return out


def _printed(model, unit, seq, marks_by_el) -> tuple[list[Sentence] | None, str]:
    starts, numbers, boxes = [], [], []
    for i, el in enumerate(seq):
        text = _own(el)
        cands = _number_candidates(text)
        cur = 0
        for mk, page in marks_by_el.get(el.id, []):
            hit = next(((p, n) for p, n in cands if p >= cur and n == mk.text), None)
            if hit is None:
                return None, f"Satz number {mk.text} printed on page {page} not found at a sentence start in {el.id}"
            cur = hit[0] + 1
            starts.append((i, hit[0]))
            numbers.append(hit[1])
            boxes.append((page, BoundingBox(l=mk.left, t=mk.top, r=mk.right, b=mk.bottom, coord_origin="BOTTOMLEFT")))
    return _build(unit, seq, starts, numbers, boxes, "printed_number")


def _from_text_numbers(unit, seq) -> tuple[list[Sentence] | None, str]:
    """Reviewed text: the printed numbers are the reviewer's text (no PDF mark to check them against)."""
    starts, numbers = [], []
    for i, el in enumerate(seq):
        for p, n in _number_candidates(_own(el)):
            starts.append((i, p))
            numbers.append(n)
    return _build(unit, seq, starts, numbers, [None] * len(starts), "printed_number", status="regenerated_from_reviewed_text")


def _build(unit, seq, starts, numbers, boxes, method, status="verified"):
    if not starts:
        return None, "no sentence numbers"
    if numbers != [str(k) for k in range(1, len(numbers) + 1)]:
        return None, f"Satz numbers {numbers} do not run 1, 2, 3, ..."
    first_i, first_o = starts[0]
    lead = "".join(_own(e) for e in seq[:first_i]) + _own(seq[first_i])[:first_o]
    if lead.strip():
        return None, f"text before Satz 1: {lead.strip()[:40]!r}"
    last = len(seq) - 1
    ranges = _ranges(seq, starts, (last, len(_own(seq[last]))))
    out = []
    for n, (i, o), rs, box in zip(numbers, starts, ranges, boxes):
        el = seq[i]
        marker = SentenceRange(element_id=el.id, start=o, end=o + len(n), text_sha256=_sha(_own(el)))
        out.append(Sentence(id=f"{unit.id}/satz-{n}", unit_id=unit.id, number=n, marker=marker, ranges=rs, status=status,
                            method=method, mark_page=box[0] if box else None, mark_box=box[1] if box else None))  # fmt: skip
    return out, ""


def _boundary_ok(text: str, pos: int) -> bool | None:
    """True: a sentence ends at text[pos] (the '.'); False: an abbreviation/date; None: cannot be decided."""
    if text[pos] in "!?":
        return True
    head = text[:pos].rstrip()
    if head.endswith((")", "]")):
        return True  # "... des Rates ( 12 ). Diese", "(Ämter)." : a sentence closed after its bracket
    if re.search(r"\d+/\d+(/[A-Z]{2,3})?$", head):
        return True  # a cited act's number: "(EU) 2016/679.", "Richtlinie 2006/42/EG."
    tok = re.search(r"([\wäöüÄÖÜß²³]+)\W*$", text[:pos])
    if tok is None:
        return None
    word = tok.group(1)
    after = re.match(r"[“”\"')\]]?\s+[„\"(]?([\wÄÖÜäöüß]+)", text[pos + 1 :])
    nxt = after.group(1).lower() if after else ""
    if word.isdigit():
        if len(word) == 4:
            return True  # a year: "bis zum 14. Januar 2027." (ordinals are short)
        return False if nxt in MONTHS else None  # "30. Juni" is a date; "Nummer 3. Die" cannot be decided
    if word.lower() in UNITS and re.search(r"\d\s*" + re.escape(word) + r"$", text[:pos]):
        return True  # "mindestens 3 m." ends the sentence (units take no period)
    if word.lower() in ABBREVIATIONS:
        return False
    if len(word) == 1 and re.search(r"\b\w\.\s*" + re.escape(word) + r"$", text[:pos]):
        return False  # a chain of single-letter abbreviations: "z. B.", "d. h.", "i. V."
    if word in SHORT_WORDS:
        return True  # "... den Beschäftigten zu. Über ...": a particle or pronoun ends the sentence
    if len(word) <= 2:
        return None
    return True


def _punctuation(unit, seq, list_types) -> tuple[list[Sentence] | None, str]:
    starts = [(0, 0)]
    for i, el in enumerate(seq):
        text = _own(el)
        for m in BOUNDARY.finditer(text):
            ok = _boundary_ok(text, m.start())
            if ok is None:
                return None, f"undecidable sentence end in {el.id}: {text[max(0, m.start() - 20) : m.start() + 12]!r}"
            if not ok:
                continue
            if el.type in list_types:
                return None, f"a sentence ends inside list item {el.id}"
            nxt = m.end()
            while nxt < len(text) and text[nxt].isspace():
                nxt += 1
            starts.append((i, nxt))
        if i + 1 < len(seq):  # a new sentence at an element join: after a complete sentence, into non-list text
            here, nxt_el = text.rstrip(), seq[i + 1]
            nxt_text = _own(nxt_el).lstrip()
            if here.endswith((".", "!", "?")) and nxt_el.type not in list_types and nxt_text[:1].isupper():
                if el.type in list_types or nxt_el.type == T.TEXT:
                    starts.append((i + 1, len(_own(nxt_el)) - len(nxt_text)))
    first = next((k for k, e in enumerate(seq) if _own(e).strip()), None)
    if first is None:
        return None, "no text"
    starts[0] = (first, len(_own(seq[first])) - len(_own(seq[first]).lstrip()))
    last = len(seq) - 1
    ranges = _ranges(seq, starts, (last, len(_own(seq[last]))))
    return [Sentence(id=f"{unit.id}/s{k}", unit_id=unit.id, ranges=rs, method="punctuation")
            for k, rs in enumerate((r for r in ranges if r), start=1)], ""  # fmt: skip


LOOKS_NUMBERED = re.compile(r"^\s*1 [A-ZÄÖÜ§\[„]")


def segment(model: DocumentModel, evidence=None, only_units: set[str] | None = None, reviewed: bool = False) -> dict:
    """Annotate `model.sentences` (for all units, or only `only_units`). Returns statistics."""
    marks_by_el: dict[str, list] = {}
    numbered_doc = False
    if evidence is not None and getattr(evidence, "small_marks", None) and not reviewed:
        for page in sorted({int(p) for p in evidence.small_marks}):
            for mk in marks_on_page(evidence, page):
                if classify(mk) != "sentence_number":
                    continue
                numbered_doc = True
                owner = mark_owner(model, page, mk, set())
                if owner is not None:
                    marks_by_el.setdefault(owner.id, []).append((mk, page))
    stats = {"units": 0, "printed_number": 0, "punctuation": 0, "unresolved_units": 0}
    list_types = for_model(model).list_types
    if only_units is None:
        model.sentences = []
    for unit in units(model):
        if only_units is not None and unit.id not in only_units:
            continue
        stats["units"] += 1
        seq = sequence(model, unit)
        text0 = next((_own(e) for e in seq if _own(e).strip()), "")
        if not text0:
            continue
        has_marks = any(e.id in marks_by_el for e in seq)
        if reviewed and LOOKS_NUMBERED.match(text0):
            found, why = _from_text_numbers(unit, seq)
        elif has_marks:
            found, why = _printed(model, unit, seq, marks_by_el)
        elif LOOKS_NUMBERED.match(text0) and (numbered_doc or evidence is None):
            found, why = None, "the text starts with a Satz number, but no printed superscript number confirms it"
        else:
            found, why = _punctuation(unit, seq, list_types)
            if found is not None and reviewed:
                found = [s.model_copy(update={"status": "regenerated_from_reviewed_text"}) for s in found]
        if found is None:
            stats["unresolved_units"] += 1
            if not reviewed:
                model.warnings.append(ParserWarning(code="SENTENCE_SEGMENTATION_UNRESOLVED", severity="info", element_id=unit.id,
                                                    message=f"{unit.id}: not split into sentences, {why}."))  # fmt: skip
            continue
        stats[found[0].method] += len(found)
        model.sentences.extend(found)
    return stats


def regenerate_after_corrections(model: DocumentModel, corrected_ids: set[str]) -> None:
    """Review: every sentence with a range on a corrected element is invalidated and rebuilt from the reviewed text
    (text rules only, no PDF evidence; status ``regenerated_from_reviewed_text``), or dropped if that fails."""
    affected = {s.unit_id for s in model.sentences if any(r.element_id in corrected_ids for r in s.ranges)}
    if not affected:
        return
    model.sentences = [s for s in model.sentences if s.unit_id not in affected]
    segment(model, None, only_units=affected, reviewed=True)
    order = {e.id: i for i, e in enumerate(model.elements)}
    model.sentences.sort(key=lambda s: (order.get(s.ranges[0].element_id, 0) if s.ranges else 0, s.ranges[0].start if s.ranges else 0))
