"""Footnotes proven by PDF evidence, on the parsed model, without changing element ids (lifecycle stage 6 for
profiles whose footnote marks are superscripts or asterisks; see `engine.resolve_footnotes`).

* ``recognise_marked_notes``: a note beginning with "*" or "*)" in the front matter or the table of contents
  is a footnote when it is the lowest text on its page and the same mark stands exactly once elsewhere on
  that page, glued to the end of a word ("STAND 1.1.2000*"): that element is its anchor.
* ``anchor_page_footnotes``: a page footnote ("1 siehe Landesrecht") gets ``anchor_id`` = the element whose box
  holds its superscript reference mark. Only when the superscript references on the page (small digits or
  "*)", not glued to a following word like a Satz number "1Die") are exactly the page's footnote marks, each
  once and in order, and each mark lies in exactly one element. Otherwise nothing changes.
* ``marks_on_page`` / ``mark_owner``: the small marks of a page and the element whose box holds a mark (also
  used by sentence segmentation for printed Satz numbers).
"""

from __future__ import annotations

import re

from odos.document_model import BoundingBox, DocumentModel, Element, ElementType as T, FootnoteRef, ParserWarning
from odos.normalization.source_marks import classify

NOTE = re.compile(r"^\s*(\*+\)?)\s+\S")
FOOTNOTE_MARK = re.compile(r"^\s*(\d+|\*+\)?)")
CONTAINERS = (T.DOCUMENT, T.TOC)


def _key(mark: str) -> str:
    return mark.rstrip(")")

def _box(el: Element, page: int):
    return next((p.bbox for p in el.provenance if p.page_no == page and p.bbox is not None and p.bbox.coord_origin.upper() == "BOTTOMLEFT"), None)  # fmt: skip

def mark_owner(model: DocumentModel, page: int, mark, exclude: set[str]) -> Element | None:
    x, y = (mark.left + mark.right) / 2, (mark.bottom + mark.top) / 2
    hits = [e for e in model.elements if e.id not in exclude and e.type not in (T.FOOTNOTE, T.FOOTNOTE_HEADING, *CONTAINERS)
            and (b := _box(e, page)) is not None and b.l - 1 <= x <= b.r + 1 and b.b - 1 <= y <= b.t + 1]  # fmt: skip
    return hits[0] if len(hits) == 1 else None

def marks_on_page(evidence, page: int) -> list:
    return list((evidence.small_marks or {}).get(page) or (evidence.small_marks or {}).get(str(page)) or [])  # type: ignore[call-overload]

def recognise_marked_notes(model: DocumentModel, evidence) -> list[str]:
    if evidence is None or not getattr(evidence, "small_marks", None):
        return []
    found = []
    for el in model.elements:
        if el.region not in ("front", "toc") or el.type not in (T.TOC_ENTRY, T.FRONT_MATTER, T.TEXT) or el.children_ids:
            continue
        m = NOTE.match(el.original_text)
        if not m or len(el.pages) != 1:
            continue
        page, box = el.pages[0], _box(el, el.pages[0])
        if box is None:
            continue
        others = [b for e in model.elements if e.id != el.id and (b := _box(e, page)) is not None]
        if any(b.b < box.b for b in others):  # not the lowest text on its page: not in the footnote zone
            continue
        # the reference: the same mark glued to the end of a word, exactly once on the page outside the note
        ref = re.compile(rf"[^\s*]{re.escape(m.group(1))}(?![\w*)])")
        hits = [(e, len(ref.findall(e.original_text))) for e in model.elements
                if e.id != el.id and page in e.pages and e.type not in CONTAINERS and ref.search(e.original_text)]  # fmt: skip
        if len(hits) != 1 or hits[0][1] != 1:
            continue
        owner = hits[0][0]
        el.type = T.FOOTNOTE
        el.marker = m.group(1)
        el.anchor_id = owner.id
        el.anchor_ids = [owner.id]
        el.footnote_refs = [FootnoteRef(element_id=owner.id, mark=m.group(1), page=page, bbox=None, mark_class="text_mark",
                                        evidence=f"the only {m.group(1)!r} glued to a word on page {page}: {owner.original_text[-30:]!r}")]  # fmt: skip
        el.hygiene_flags.append("footnote_recognised_from_pdf_reference_mark")
        found.append(el.id)
    return found

def _set_anchors(note: Element, refs: list[FootnoteRef], flag: str) -> None:
    note.footnote_refs = refs
    note.anchor_ids = list(dict.fromkeys(r.element_id for r in refs))
    note.anchor_id = note.anchor_ids[0] if len(note.anchor_ids) == 1 else None  # meaning unchanged: the single anchor
    note.uncertainty_reasons = [r for r in note.uncertainty_reasons if r != "page_footnote_anchor_unknown"]
    note.uncertain = bool(note.uncertainty_reasons)
    note.hygiene_flags.append(flag)

def _box_of(mk) -> BoundingBox:
    return BoundingBox(l=mk.left, t=mk.top, r=mk.right, b=mk.bottom, coord_origin="BOTTOMLEFT")

def anchor_page_footnotes(model: DocumentModel, evidence) -> dict[str, list[str]]:
    """Anchor page footnotes to every element that prints their reference mark. Per page, all of this must hold,
    otherwise the footnote stays unresolved (and a warning names the competing candidates):

    * each reference is a mark classified as a reference (never a Satz number or an exponent);
    * the footnote's mark has at least one reference and no unclear mark could also be one of its references;
    * spaced references (a space on both sides) count only when they are the footnote's sole candidate;
    * the first references of the page's footnotes come in the footnotes' order;
    * every reference mark lies in exactly one element.
    A footnote without any reference on its page takes the single unclaimed reference with its mark on the
    previous page, if there is exactly one."""
    if evidence is None or not getattr(evidence, "small_marks", None):
        return {}
    index = model.by_id()
    by_page: dict[int, list[Element]] = {}
    for el in model.elements:
        if el.type == T.FOOTNOTE and el.anchor_id is None and not el.anchor_ids and index[el.parent_id].type != T.FOOTNOTE_HEADING and len(el.pages) == 1:  # fmt: skip
            by_page.setdefault(el.pages[0], []).append(el)
    notes_all = {n.id for ns in by_page.values() for n in ns}
    claimed: dict[int, set[int]] = {}  # page -> indexes of marks used as references
    unresolved: dict[str, str] = {}
    anchored: dict[str, list[str]] = {}

    furniture = [(p.page_no, p.bbox) for e in model.furniture for p in e.provenance if p.bbox is not None]

    def page_marks(page: int, zone_top: float | None):
        out = []
        for i, mk in enumerate(marks_on_page(evidence, page)):
            if zone_top is not None and (mk.bottom + mk.top) / 2 <= zone_top + 1:
                continue  # the footnote texts' own leading numbers
            x, y = (mk.left + mk.right) / 2, (mk.bottom + mk.top) / 2
            if any(pg == page and b.l - 1 <= x <= b.r + 1 and b.b - 1 <= y <= b.t + 1 for pg, b in furniture):
                continue  # page headers/footers ("- Seite 1 von 45 -") are not text with references
            out.append((i, mk, classify(mk)))
        return out

    pending: list[tuple[int, Element, str]] = []
    for page, notes in sorted(by_page.items()):
        boxes = [_box(n, page) for n in notes]
        marks_of = [FOOTNOTE_MARK.match(n.original_text) for n in notes]
        if None in boxes or None in marks_of:
            continue
        zone_top = max(b.t for b in boxes)
        marks = page_marks(page, zone_top)
        found: dict[str, list[FootnoteRef]] = {}
        first_pos: list[tuple[int, str]] = []
        for note, m in zip(notes, marks_of):
            key = _key(m.group(1))
            attached = [(i, mk) for i, mk, c in marks if c == "reference_attached" and _key(mk.text) == key]
            spaced = [(i, mk) for i, mk, c in marks if c == "reference_spaced" and _key(mk.text) == key]
            # unclear: ambiguous marks containing the footnote's mark, and longer runs that start with it ("26" for 2)
            unclear = [mk.text for i, mk, c in marks
                       if (c == "ambiguous" and key in mk.text) or (c != "sentence_number" and c != "exponent" and _key(mk.text) != key and _key(mk.text).startswith(key))]  # fmt: skip
            refs = attached if attached else spaced if len(spaced) == 1 else []
            why = None
            if unclear:
                why = f"unclear mark(s) {unclear} could also be references"
            elif attached and spaced:
                why = f"{len(attached)} attached and {len(spaced)} spaced candidate(s)"
            elif len(spaced) > 1:
                why = f"{len(spaced)} spaced candidates"
            elif not refs:
                pending.append((page, note, key))
                continue
            if why is None:
                owners = [mark_owner(model, page, mk, notes_all) for _, mk in refs]
                if None in owners:
                    why = "a reference mark lies in no single element"
                else:
                    cls = {i: c for i, _, c in marks}
                    found[note.id] = [FootnoteRef(element_id=o.id, mark=mk.text, page=page, bbox=_box_of(mk), mark_class=cls[i],
                                                  evidence=f"{evidence.extractor}: superscript '{mk.text}' after {mk.prev_glyph!r} (gap {mk.gap_before} pt), before {mk.next_glyph!r} (gap {mk.gap_after} pt)")  # fmt: skip
                                      for (i, mk), o in zip(refs, owners)]
                    first_pos.append((min(i for i, _ in refs), note.id))
                    claimed.setdefault(page, set()).update(i for i, _ in refs)
            if why:
                unresolved[note.id] = why
        order = [nid for _, nid in sorted(first_pos)]
        if order != [n.id for n in notes if n.id in found]:  # references must come in the footnotes' order
            for nid in found:
                unresolved[nid] = "the references are not in the order of the footnotes"
            found = {}
        for note in notes:
            if note.id in found:
                _set_anchors(note, found[note.id], "footnote_anchor_from_pdf_reference_mark")
                anchored[note.id] = note.anchor_ids
    for page, note, key in pending:  # the reference may stand on the previous page
        prev = [(i, mk) for i, mk, c in page_marks(page - 1, None) if c == "reference_attached" and _key(mk.text) == key
                and i not in claimed.get(page - 1, set())]  # fmt: skip
        prev_notes = {m.group(1) for n in by_page.get(page - 1, []) if (m := FOOTNOTE_MARK.match(n.original_text))}
        owner = mark_owner(model, page - 1, prev[0][1], notes_all) if len(prev) == 1 and key not in {_key(x) for x in prev_notes} else None
        if owner is None:
            unresolved[note.id] = "no reference mark found on its page" + (" or a single one on the previous page" if page > 1 else "")
            continue
        i, mk = prev[0]
        claimed.setdefault(page - 1, set()).add(i)
        _set_anchors(note, [FootnoteRef(element_id=owner.id, mark=mk.text, page=page - 1, bbox=_box_of(mk), mark_class=classify(mk),
                                        evidence=f"{evidence.extractor}: the only unclaimed reference '{mk.text}' is on the previous page")],
                     "footnote_anchor_from_pdf_reference_mark_previous_page")  # fmt: skip
        anchored[note.id] = note.anchor_ids
    # reference-like marks that no footnote claimed (outside every footnote's own box): reported, never forced
    fn_boxes = [(p.page_no, p.bbox) for e in model.elements if e.type == T.FOOTNOTE for p in e.provenance if p.bbox]
    for page in sorted({int(p) for p in (evidence.small_marks or {})}):
        for i, mk, c in page_marks(page, None):
            x, y = (mk.left + mk.right) / 2, (mk.bottom + mk.top) / 2
            if not c.startswith("reference") or i in claimed.get(page, set()):
                continue
            if any(pg == page and b.l - 1 <= x <= b.r + 1 and b.b - 1 <= y <= b.t + 1 for pg, b in fn_boxes):
                continue
            owner = mark_owner(model, page, mk, notes_all)
            model.warnings.append(ParserWarning(code="FOOTNOTE_REFERENCE_WITHOUT_FOOTNOTE", severity="info",
                                                element_id=owner.id if owner else None,
                                                message=f"Page {page}: superscript {mk.text!r} after {mk.prev_glyph!r} looks like a footnote reference, but no footnote could be matched to it."))  # fmt: skip
    for nid, why in unresolved.items():
        if nid not in anchored:
            model.warnings.append(ParserWarning(code="FOOTNOTE_REFERENCE_UNRESOLVED", severity="info", element_id=nid,
                                                source_ref=index[nid].source_refs[0] if index[nid].source_refs else None,
                                                message=f"Footnote {index[nid].original_text[:30]!r}: not anchored, {why}."))  # fmt: skip
    return anchored
