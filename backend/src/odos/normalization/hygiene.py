"""Shared extraction-hygiene layer (profile-independent).

Runs between the Docling reader and any structure parser and only *derives* data:

* splits Docling items that contain several numbered legal paragraphs (and their lettered points)
  into segments, each an exact slice of the item's `orig` with its character range;
* adds a normalised `search_text` (soft hyphens, spacing, letter-spacing, "( 3 )" references);
* flags running headers/footers, including ones Docling labelled as body text;
* flags body items whose boxes overlap on the page: Docling then moved lines of one text region into
  another item, so the reading order there is unreliable (e.g. the last lines of three paragraphs
  collected in one stray item). The items are kept as they are and marked for review.

The Docling items themselves are never modified or dropped.
"""

from __future__ import annotations

import re
from collections import defaultdict

from pydantic import BaseModel, Field

from odos.normalization.docling_reader import SourceItem
from odos.document_model import Provenance
from odos.normalization.source_text import revert

SPLITTABLE_LABELS = {"text", "list_item"}
SENTENCE_END = ".;:!?"
# "(2)" after a sentence end, followed by text: a paragraph that Docling merged into the previous one
EMBEDDED_PARAGRAPH = re.compile(r"(?<=[.;:!?])(\s+)\((\d+)([a-z]?)\)\s+(?=\S)")
LEADING_PARAGRAPH = re.compile(r"^\((\d+)([a-z]?)\)\s")
EMBEDDED_POINT = re.compile(r"(?<=\S)(\s+)([a-z])\)\s+(?=\S)")
HEADER_BAND = 0.08  # top/bottom share of the page height scanned for running headers/footers
OVERLAP_MIN_PT = 2.0  # body boxes overlapping by more than this in both directions share lines


class Segment(BaseModel):
    start: int
    end: int
    marker: str | None = None
    kind: str = "whole"  # whole | paragraph | point | intro
    boundary_flags: list[str] = Field(default_factory=list)


class HygieneResult(BaseModel):
    items: list[SourceItem]
    report: dict


# ---- search text ----------------------------------------------------------------------------------------
def search_normalize(text: str) -> tuple[str, list[str]]:
    """Derived text for search and comparison. Never used as legal text."""
    flags: list[str] = []
    s = text
    if "\xad" in s:
        s = re.sub("\xad\\s*", "", s)  # soft hyphen (+ the line-break space Docling keeps after it)
        flags.append("soft_hyphen_removed")
    s2 = re.sub(r"\(\s+(\d+)\s+\)", r"(\1)", s)  # "( 3 )" -> "(3)" (EU footnote references)
    if s2 != s:
        flags.append("spaced_reference_compacted")
        s = s2

    def join_run(m: re.Match) -> str:
        return m.group(0).replace(" ", "")

    s2 = re.sub(r"(?<!\S)(?:\w ){4,}\w(?!\S)", join_run, s)  # "N o r m a l e s" -> "Normales"
    if s2 != s:
        flags.append("letter_spacing_collapsed")  # word boundaries inside the run are lost
        s = s2
    s2 = re.sub(r"\s+", " ", s.replace(" ", " ")).strip()
    if s2 != s and "whitespace_normalised" not in flags:
        flags.append("whitespace_normalised")
    return s2, flags


# ---- segmentation -----------------------------------------------------------------------------------------
def _paragraph_cuts(orig: str) -> list[tuple[int, str, list[str]]]:
    """(start offset, marker, boundary flags) of embedded paragraph markers that continue the numbering."""
    lead = LEADING_PARAGRAPH.match(orig)
    expected = int(lead.group(1)) + 1 if lead else None
    found = [(m.start(2) - 1, int(m.group(2)), f"({m.group(2)}{m.group(3)})", m) for m in EMBEDDED_PARAGRAPH.finditer(orig)]  # fmt: skip
    cuts: list[tuple[int, str, list[str]]] = []
    if expected is None:
        # no leading marker: only a run of >= 2 consecutive embedded markers counts, and it stays uncertain
        nums = [n for _, n, _, _ in found]
        if len(nums) >= 2 and nums == list(range(nums[0], nums[0] + len(nums))):
            cuts = [(pos, mk, ["item_has_no_leading_paragraph_marker"]) for pos, _, mk, _ in found]
        return cuts
    for pos, n, mk, m in found:
        if n != expected:
            continue  # e.g. a quoted "(5)" that does not continue the numbering: not a boundary
        flags = []
        nxt = orig[m.end() : m.end() + 1]
        if nxt and not (nxt.isupper() or nxt.isdigit()):
            flags.append("text_after_marker_not_capitalised")
        cuts.append((pos, mk, flags))
        expected += 1
    return cuts


def _point_cuts(orig: str, start: int, end: int) -> list[tuple[int, str, list[str]]]:
    """Embedded lettered points a), b), c) ... inside one paragraph segment."""
    seg = orig[start:end]
    cands = [(m.start(2), m.group(2), m) for m in EMBEDDED_POINT.finditer(seg)]
    run: list[tuple[int, str, list[str]]] = []
    for pos, letter, m in cands:
        expected = chr(ord("a") + len(run))
        if letter != expected:
            if run:
                break
            continue
        before = seg[: m.start(1)].rstrip()[-1:]
        if letter != "a" and before not in ";,:":
            break  # "Buchstabe a) und b)" is a reference, not a list
        flags = [] if before in ";,:" else ["point_marker_without_preceding_punctuation"]
        run.append((start + pos, f"{letter})", flags))
    return run if len(run) >= 2 else []


def segment_item(item: SourceItem) -> list[Segment]:
    orig = item.orig
    whole = [Segment(start=0, end=len(orig))]
    if item.label not in SPLITTABLE_LABELS or item.is_furniture or item.table is not None:
        return whole
    cuts = _paragraph_cuts(orig)
    if not cuts:
        return whole
    lead = LEADING_PARAGRAPH.match(orig)
    bounds = [(0, f"({lead.group(1)}{lead.group(2)})" if lead else None, [])] + cuts
    segs: list[Segment] = []
    for i, (s, mk, flags) in enumerate(bounds):
        e = bounds[i + 1][0] if i + 1 < len(bounds) else len(orig)
        e = len(orig[:e].rstrip())  # the separating whitespace belongs to no segment
        points = _point_cuts(orig, s, e)
        if not points:
            segs.append(Segment(start=s, end=e, marker=mk, kind="paragraph", boundary_flags=flags))
            continue
        segs.append(Segment(start=s, end=len(orig[: points[0][0]].rstrip()), marker=mk, kind="paragraph", boundary_flags=flags))  # fmt: skip
        for j, (ps, pmk, pflags) in enumerate(points):
            pe = points[j + 1][0] if j + 1 < len(points) else e
            segs.append(Segment(start=ps, end=len(orig[:pe].rstrip()), marker=pmk, kind="point", boundary_flags=pflags))
    return segs


def _segment_provenance(item: SourceItem, s: int, e: int) -> list[Provenance]:
    out = []
    for p in item.provenance:
        cs = p.charspan or (0, len(item.orig))
        lo, hi = max(s, cs[0]), min(e, cs[1])
        if lo < hi or (s == e == lo):
            out.append(Provenance(page_no=p.page_no, bbox=p.bbox, charspan=(lo, hi)))
    return out or [Provenance(page_no=p.page_no, bbox=p.bbox, charspan=(s, e)) for p in item.provenance[:1]]


def _exact_highlights(it: SourceItem, segs, derived: list[SourceItem], by_ref: dict, glyphs, maps: dict) -> None:
    """Set `highlight_boxes` on segments of a split item and on a reading-order-repaired item (see highlight.py)."""
    from odos.normalization.highlight import boxes_for, glyph_map

    def mapping(ref: str, text: str, prov):
        if ref not in maps:
            maps[ref] = glyph_map(text, [(p.page_no, p.bbox) for p in prov], glyphs)
        return maps[ref]

    if it.parts:  # slices of several Docling items (their verbatim Docling text)
        boxes = []
        for p in it.parts:
            src = by_ref.get(p.ref)
            m = mapping(p.ref, src.orig, src.provenance) if src is not None else None
            got = boxes_for(src.orig, p.start, p.end, m, glyphs) if m else None
            if not got:
                return
            boxes += got
        derived[0].highlight_boxes = boxes
        return
    if len(segs) < 2:
        return
    m = mapping(it.ref, it.orig, it.provenance)
    if m is None:
        return
    for d in derived:
        got = boxes_for(it.orig, d.span[0], d.span[1], m, glyphs) if d.span else None
        d.highlight_boxes = got or []


def _derived_items(item: SourceItem, segs: list[Segment]) -> list[SourceItem]:
    if len(segs) == 1:
        st, fl = search_normalize(item.orig)
        return [item.model_copy(update={"search_text": st if st != item.orig else None, "hygiene_flags": [*item.hygiene_flags, *fl]})]  # fmt: skip
    out = []
    for i, sg in enumerate(segs):
        orig = item.orig[sg.start : sg.end]
        first = i == 0
        text = item.text if first and item.marker is None else orig
        if first and item.marker and orig.startswith(item.marker):
            text = orig[len(item.marker) :].lstrip()
        st, fl = search_normalize(orig)
        flags = ["split_from_merged_docling_item", f"segment_kind_{sg.kind}"] + fl
        if not first:
            flags.append("marker_derived_from_text")
        repairs = [r for r in item.text_repairs if sg.start <= r.start < sg.end]  # item-level offsets, like `span`
        docling = revert(orig, repairs, offset=sg.start) if item.docling_orig is not None else None
        if any(r.restored != r.docling for r in repairs):
            flags.append("text_restored_from_pdf_text_layer")
        out.append(SourceItem(
            ref=item.ref, label=item.label, layer=item.layer, orig=orig, text=text,
            marker=item.marker if first else sg.marker, enumerated=item.enumerated if first else True,
            group_ref=item.group_ref, provenance=_segment_provenance(item, sg.start, sg.end),
            span=(sg.start, sg.end), segment_index=i, segment_count=len(segs),
            boundary_flags=sg.boundary_flags, search_text=st if st != orig else None, hygiene_flags=flags,
            docling_orig=docling if docling != orig else None, text_repairs=repairs,
        ))  # fmt: skip
    return out


# ---- running headers / footers --------------------------------------------------------------------------------
def _signature(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", text)).strip().lower()


def detect_running_furniture(items: list[SourceItem], page_sizes: dict[int, tuple[float, float]]) -> dict[str, str]:
    """ref -> "running_header" | "running_footer" for short lines repeated in the top/bottom band of many pages."""
    n_pages = max(len(page_sizes), 1)
    pages_by_sig: dict[tuple[str, str], set[int]] = defaultdict(set)
    where: dict[str, tuple[str, str]] = {}
    for it in items:
        text = it.orig.strip()
        if not text or len(text) > 200 or it.table is not None or len(it.provenance) != 1 or it.label == "footnote":
            continue
        p = it.provenance[0]
        if p.bbox is None or p.page_no not in page_sizes:
            continue
        h = page_sizes[p.page_no][1]
        top, bottom = (p.bbox.t, p.bbox.b) if p.bbox.coord_origin.upper().startswith("BOTTOM") else (h - p.bbox.t, h - p.bbox.b)  # fmt: skip
        band = "running_header" if top >= h * (1 - HEADER_BAND) else "running_footer" if bottom <= h * HEADER_BAND else None
        if band is None:
            continue
        key = (band, _signature(text))
        pages_by_sig[key].add(p.page_no)
        where[it.ref] = key
    threshold = max(3, int(0.2 * n_pages))
    return {ref: key[0] for ref, key in where.items() if len(pages_by_sig[key]) >= threshold}


# ---- overlapping layout boxes ----------------------------------------------------------------------------------------
def detect_layout_overlaps(items: list[SourceItem], furniture: dict[str, str]) -> list[dict]:
    """Pairs of body items (not furniture, footnotes or tables) on the same page whose boxes overlap by more
    than OVERLAP_MIN_PT in both directions. Lines then belong to two layout regions at once, and Docling's
    reading order between the two items is not reliable."""
    boxes: dict[int, list[tuple[SourceItem, object]]] = defaultdict(list)
    for it in items:
        if it.is_furniture or it.table is not None or it.label == "footnote" or it.ref in furniture:
            continue
        for p in it.provenance:
            if p.bbox is not None:
                boxes[p.page_no].append((it, p.bbox))
    out = []
    for page in sorted(boxes):
        lst = boxes[page]
        for i, (a, x) in enumerate(lst):
            for b, y in lst[i + 1 :]:
                if a.ref == b.ref:
                    continue
                w = min(x.r, y.r) - max(x.l, y.l)
                h = min(max(x.t, x.b), max(y.t, y.b)) - max(min(x.t, x.b), min(y.t, y.b))  # either coordinate origin
                if w > OVERLAP_MIN_PT and h > OVERLAP_MIN_PT:
                    out.append({"page": page, "refs": [a.ref, b.ref], "overlap_pt": [round(w, 1), round(h, 1)]})
    return out


# ---- entry point ------------------------------------------------------------------------------------------------
def apply_hygiene(items: list[SourceItem], page_sizes: dict[int, tuple[float, float]], evidence=None) -> HygieneResult:
    """``evidence``: the PDF text layer (``reading_order.load_evidence``); without it nothing is repaired."""
    from odos.normalization.reading_order import repair_reading_order, starts_visual_line
    from odos.normalization.source_text import restore_items

    source = items
    furniture = detect_running_furniture(items, page_sizes)
    overlaps = detect_layout_overlaps(items, furniture)
    overlapping = {r for o in overlaps for r in o["refs"]}
    items, repairs = repair_reading_order(items, overlaps, evidence, segment_item)
    items = restore_items(items, evidence)  # characters Docling normalised away, from the PDF text layer
    restored = {it.ref: it for it in items if it.docling_orig is not None}
    # accounting is against the canonical text: Docling's, plus the recorded repairs (which must undo exactly)
    canonical = [restored[i.ref] if i.ref in restored and revert(restored[i.ref].orig, restored[i.ref].text_repairs) == i.orig else i
                 for i in source]  # fmt: skip
    out: list[SourceItem] = []
    split_items = []
    glyphs = getattr(evidence, "glyph_lines", None) or {}
    by_ref = {i.ref: i for i in source}
    maps: dict[str, dict | None] = {}
    for it in items:
        segs = [Segment(start=0, end=len(it.orig))] if it.parts else segment_item(it)  # repaired: never re-segmented
        derived = _derived_items(it, segs)
        if glyphs:  # elements covering only part of an item get exact rectangles, where the glyphs prove them
            _exact_highlights(it, segs, derived, by_ref, glyphs, maps)
        for d in derived:  # an inferred split boundary is proven when the segment starts its own line in the PDF
            if d.boundary_flags and starts_visual_line(evidence, d.pages[0] if d.pages else None, d.orig):
                d.boundary_flags = []
                d.hygiene_flags = [*d.hygiene_flags, "segment_boundary_verified_by_pdf_text_layer"]
        if it.ref in overlapping and "repaired_from_pdf_text_layer" not in it.order_flags:
            for d in derived:
                d.order_flags = [*d.order_flags, "layout_box_overlaps_other_item"]
                d.hygiene_flags = [*d.hygiene_flags, "layout_box_overlap"]
        if it.ref in furniture:
            leaked = not it.is_furniture
            for d in derived:
                d.hygiene_flags = [*d.hygiene_flags, furniture[it.ref]] + (["furniture_labelled_as_body_by_docling"] if leaked else [])  # fmt: skip
        if len(segs) > 1:
            split_items.append({
                "ref": it.ref, "pages": it.pages, "chars": len(it.orig), "segments": len(segs),
                "markers": [s.marker for s in segs],
                "uncertain_boundaries": [{"marker": s.marker, "flags": s.boundary_flags} for s in segs if s.boundary_flags],
            })  # fmt: skip
        out.extend(derived)
    report = {
        "docling_items": len(source),
        "derived_items": len(out),
        "split_items": split_items,
        "segments_from_split_items": sum(s["segments"] for s in split_items),
        "uncertain_boundaries": sum(len(s["uncertain_boundaries"]) for s in split_items),
        "running_furniture": {
            "flagged_items": len(furniture),
            "labelled_as_body_by_docling": sorted(
                (r for r in furniture if not next(i for i in items if i.ref == r).is_furniture),
                key=lambda r: int(r.rsplit("/", 1)[1]),
            ),
        },
        "layout_overlaps": overlaps,
        "reading_order_repairs": repairs,
        "search_text_flags": _count_flags(out),
        "accounting": check_accounting(canonical, out),
        "source_text_repairs": {"items": len(restored), "repairs": sum(len(i.text_repairs) for i in restored.values()),
                                "unresolved": sum(r.status == "unresolved" for i in restored.values() for r in i.text_repairs)},  # fmt: skip
    }
    return HygieneResult(items=out, report=report)


def _count_flags(items: list[SourceItem]) -> dict[str, int]:
    c: dict[str, int] = defaultdict(int)
    for it in items:
        for f in it.hygiene_flags:
            if f in ("soft_hyphen_removed", "spaced_reference_compacted", "letter_spacing_collapsed", "whitespace_normalised"):
                c[f] += 1
    return dict(sorted(c.items()))


def check_accounting(original: list[SourceItem], derived: list[SourceItem]) -> dict:
    """Every Docling item is represented; split items are tiled exactly (only whitespace between segments)."""
    by_ref: dict[str, list[tuple[int | None, int | None, str]]] = defaultdict(list)  # (start, end, text) per Docling item
    for d in derived:
        if d.parts:  # reading-order repair: orig is verbatim slices of several items joined by " "
            for p in d.parts:
                src = next(i.orig for i in original if i.ref == p.ref)
                by_ref[p.ref].append((p.start, p.end, src[p.start : p.end]))
        elif d.span is not None:
            by_ref[d.ref].append((d.span[0], d.span[1], d.orig))
        else:
            by_ref[d.ref].append((None, None, d.orig))
    problems = []
    for d in derived:
        if d.parts and " ".join(next(i.orig for i in original if i.ref == p.ref)[p.start : p.end].rstrip() for p in d.parts) != d.orig:  # fmt: skip
            problems.append({"ref": d.ref, "problem": "repaired_text_is_not_its_parts"})
    for it in original:
        parts = by_ref.get(it.ref, [])
        if not parts:
            problems.append({"ref": it.ref, "problem": "missing"})
            continue
        if len(parts) == 1 and parts[0][0] is None:
            if parts[0][2] != it.orig:
                problems.append({"ref": it.ref, "problem": "text_changed"})
            continue
        pos = 0
        for s, e, text in sorted(parts, key=lambda x: x[0] or 0):
            if s is None:
                problems.append({"ref": it.ref, "problem": "covered_twice"})
                continue
            if it.orig[pos:s].strip():
                problems.append({"ref": it.ref, "problem": "uncovered_text", "at": pos})
            if s < pos:
                problems.append({"ref": it.ref, "problem": "overlap", "at": s})
            if text != it.orig[s:e]:
                problems.append({"ref": it.ref, "problem": "segment_text_differs", "at": s})
            pos = e
        if it.orig[pos:].strip():
            problems.append({"ref": it.ref, "problem": "uncovered_text", "at": pos})
    return {"ok": not problems, "problems": problems}
