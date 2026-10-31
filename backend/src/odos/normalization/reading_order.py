"""Source-verified reading-order repair for overlapping Docling layout boxes.

When two body boxes overlap (``hygiene.detect_layout_overlaps``), Docling may have cut lines out of one
text region into another item. Example, Regulation (EU) 2023/1230, Art. 47: the last lines of paragraphs
(1), (2) and (3) ("Bedingungen übertragen.", "Zeitraums.", "berührt.") form one stray item placed after (3).

The repair uses the PDF's own text layer (pypdfium2) as evidence, stored next to the Docling JSON in
``pdf_text_lines.json`` (with the SHA-256 of the PDF and of the Docling JSON it belongs to). It is applied
only if all of the following hold, otherwise nothing changes and the items stay flagged:

1. every text-layer line in the region belongs to exactly one involved item, and every character of every
   involved item is matched by those lines (text compared without whitespace and soft hyphens);
2. exactly one item (the stray item) has non-contiguous lines;
3. each run of stray lines follows directly after the *last* line of one other item and is followed by the
   first line of the next item (or ends the region) -- i.e. it is that item's continuation; a stray line in
   the middle of another item is never repaired;
4. the items receiving text are not split further by the hygiene segmentation.

A repaired item is the receiving item's verbatim ``orig`` + " " + the verbatim slice of the stray item, with
both character ranges kept as ``parts``; the stray item disappears as a separate item (its text is fully
covered by those slices). The elements stay uncertain (``reading_order_uncertain:...``) for human review.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

from pydantic import BaseModel

from odos.normalization.docling_reader import SourceItem
from odos.artifact_names import READING_ORDER_EVIDENCE as EVIDENCE_NAME
from odos.document_model import SourceSpan

_SOFT = re.compile("[\xad￾­]\\s*")


class TextLine(BaseModel):
    top: float
    bottom: float
    left: float
    right: float
    text: str


class SmallMark(BaseModel):
    """A run of digits / '*' / ')' set smaller than the page's body text (superscript references, Satz numbers)."""

    text: str
    left: float
    bottom: float
    right: float
    top: float
    prev: str  # the character before the run ("" at the start of the page)
    next: str  # the character after the run
    # geometry against the nearest visible glyph on the same line (None: no glyph on that side of the line)
    prev_glyph: str = ""
    next_glyph: str = ""
    gap_before: float | None = None  # pt between the previous glyph's right edge and the run
    gap_after: float | None = None  # pt between the run and the next glyph's left edge
    raise_: float | None = None  # pt the run's bottom lies above the neighbouring glyph's bottom (superscript > 0)
    before: str = ""  # up to 8 characters before the run on its line ("1 000 m" before an exponent)


class GlyphLine(BaseModel):
    """A visual PDF line with the horizontal extent of each of its characters (``xs[i]`` belongs to ``text[i]``)."""

    top: float
    bottom: float
    text: str
    xs: list[tuple[float, float]]


class RegionLine(BaseModel):
    """One visual PDF line clipped to a Docling item's box, or to one of its table cells (`cell` = [row, col])."""

    cell: list[int] | None = None
    page: int
    top: float
    bottom: float
    left: float
    right: float
    text: str


class TextLayerEvidence(BaseModel):
    pdf_sha256: str
    docling_json_sha256: str
    extractor: str
    pages: dict[int, list[TextLine]]  # only pages with overlapping layout boxes or unproven split boundaries
    error: str | None = None  # the PDF could not be read: no lines, nothing repaired
    # the text layer inside each Docling item's box(es), one string per box; line breaks as "\n", a hyphen the
    # PDF sets at a line end as "\x02" (pypdfium2). Used to restore characters Docling normalised away.
    item_text: dict[str, list[str]] = {}
    small_marks: dict[int, list[SmallMark]] = {}
    # visual lines inside table cells and inside items listing several headings (TOC-like pages), top to bottom
    region_lines: dict[str, list[RegionLine]] = {}
    # glyph geometry of the pages where an element covers only part of a Docling item (split or repaired items)
    glyph_lines: dict[int, list[GlyphLine]] = {}


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", _SOFT.sub("", unicodedata.normalize("NFKC", s)))


def _sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# ---- evidence ------------------------------------------------------------------------------------------------
def extract_text_lines(pdf: Path, pages: list[int]) -> dict[int, list[TextLine]]:
    """Visual lines (top to bottom) of the PDF text layer: characters whose vertical centre lies within one
    line's extent, in content order. Coordinates are PDF points, origin bottom-left (as in Docling)."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf))
    out: dict[int, list[TextLine]] = {}
    try:
        for no in pages:
            tp = doc[no - 1].get_textpage()
            chars = []
            for i in range(tp.count_chars()):
                ch = tp.get_text_range(i, 1)
                left, bottom, right, top = tp.get_charbox(i)
                if ch in "\r\n" or right <= left:
                    continue
                chars.append((i, ch, left, bottom, right, top))
            lines: list[dict] = []
            for c in sorted(chars, key=lambda c: (-(c[3] + c[5]) / 2, c[0])):
                mid = (c[3] + c[5]) / 2
                line = next((ln for ln in lines if ln["b"] - 1 <= mid <= ln["t"] + 1), None)
                if line is None:
                    lines.append({"b": c[3], "t": c[5], "c": [c]})
                else:
                    line["c"].append(c)
                    line["b"], line["t"] = min(line["b"], c[3]), max(line["t"], c[5])
            out[no] = [
                TextLine(top=round(ln["t"], 2), bottom=round(ln["b"], 2), left=round(min(c[2] for c in ln["c"]), 2),
                         right=round(max(c[4] for c in ln["c"]), 2), text="".join(c[1] for c in sorted(ln["c"])))
                for ln in sorted(lines, key=lambda ln: -ln["t"])
            ]  # fmt: skip
    finally:
        doc.close()
    return out


def extract_glyph_lines(pdf: Path, pages: list[int]) -> dict[int, list[GlyphLine]]:
    """Like ``extract_text_lines``, keeping every character's horizontal extent (left, right) in PDF points."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf))
    out: dict[int, list[GlyphLine]] = {}
    try:
        for no in pages:
            tp = doc[no - 1].get_textpage()
            chars = []
            for i in range(tp.count_chars()):
                ch = tp.get_text_range(i, 1)
                left, bottom, right, top = tp.get_charbox(i)
                if ch in "\r\n" or right <= left:
                    continue
                chars.append((i, ch, left, bottom, right, top))
            lines: list[dict] = []
            for c in sorted(chars, key=lambda c: (-(c[3] + c[5]) / 2, c[0])):
                mid = (c[3] + c[5]) / 2
                line = next((ln for ln in lines if ln["b"] - 1 <= mid <= ln["t"] + 1), None)
                if line is None:
                    lines.append({"b": c[3], "t": c[5], "c": [c]})
                else:
                    line["c"].append(c)
                    line["b"], line["t"] = min(line["b"], c[3]), max(line["t"], c[5])
            out[no] = [
                GlyphLine(top=round(ln["t"], 2), bottom=round(ln["b"], 2), text="".join(c[1] for c in sorted(ln["c"])),
                          xs=[(round(c[2], 2), round(c[4], 2)) for c in sorted(ln["c"])])
                for ln in sorted(lines, key=lambda ln: -ln["t"])
            ]  # fmt: skip
    finally:
        doc.close()
    return out


def _pdf_box(it: SourceItem, p, page_h: float) -> tuple[float, float, float, float]:
    b = p.bbox
    if b.coord_origin.upper().startswith("TOP"):  # Docling may report top-left boxes
        return b.l, page_h - b.b, b.r, page_h - b.t
    return b.l, b.b, b.r, b.t


def extract_item_texts(pdf: Path, items: list[SourceItem]) -> dict[str, list[str]]:
    """The text layer inside each text item's Docling box(es). Tables and pictures are not compared."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf))
    out: dict[str, list[str]] = {}
    try:
        tps: dict[int, object] = {}
        for it in items:
            if it.table is not None or it.label == "picture" or not it.provenance or any(p.bbox is None for p in it.provenance):
                continue
            texts = []
            for p in it.provenance:
                if p.page_no not in tps:
                    tps[p.page_no] = doc[p.page_no - 1].get_textpage()
                h = doc[p.page_no - 1].get_height()
                left, bottom, right, top = _pdf_box(it, p, h)
                texts.append(tps[p.page_no].get_text_bounded(left=left - 0.5, bottom=bottom - 0.5, right=right + 0.5, top=top + 0.5))
            out[it.ref] = texts
    finally:
        doc.close()
    return out


def extract_small_marks(pdf: Path) -> dict[int, list[SmallMark]]:
    """Runs of digits, '*' and ')' set more than 1 pt smaller than the page's most common letter size."""
    from collections import Counter

    import pypdfium2 as pdfium
    import pypdfium2.raw as R

    doc = pdfium.PdfDocument(str(pdf))
    out: dict[int, list[SmallMark]] = {}
    try:
        for no in range(1, len(doc) + 1):
            tp = doc[no - 1].get_textpage()
            chars = []
            for i in range(tp.count_chars()):
                u = R.FPDFText_GetUnicode(tp.raw, i)
                chars.append((chr(u) if u > 31 else " ", R.FPDFText_GetFontSize(tp.raw, i), tp.get_charbox(i)))
            sizes = Counter(round(s, 1) for c, s, _ in chars if c.isalpha())
            if not sizes:
                continue
            body = sizes.most_common(1)[0][0]
            small = [c[0] in "0123456789*)" and c[1] < body - 1 for c in chars]

            def glyph(i: int, step: int, top: float, bottom: float, left: float, right: float):
                """Nearest visible glyph from index i in direction step, on the same visual line and on that side
                of the run, or None (the run starts or ends its line)."""
                while 0 <= i < len(chars):
                    c, _, b = chars[i]
                    if c.strip() and b[2] > b[0]:
                        mid = (b[1] + b[3]) / 2
                        same_line = bottom - 6 <= mid <= top + 6
                        on_side = b[2] <= left + 1 if step < 0 else b[0] >= right - 1
                        return (c, b) if same_line and on_side else None
                    i += step
                return None

            marks, k = [], 0
            while k < len(chars):
                if small[k] and chars[k][0] != ")":
                    j = k
                    while j < len(chars) and small[j]:
                        j += 1
                    boxes = [chars[x][2] for x in range(k, j)]
                    left, bottom = min(b[0] for b in boxes), min(b[1] for b in boxes)
                    right, top = max(b[2] for b in boxes), max(b[3] for b in boxes)
                    pg, ng = glyph(k - 1, -1, top, bottom, left, right), glyph(j, 1, top, bottom, left, right)
                    ref = pg or ng
                    marks.append(SmallMark(text="".join(chars[x][0] for x in range(k, j)),
                                           left=round(left, 2), bottom=round(bottom, 2), right=round(right, 2), top=round(top, 2),
                                           prev=chars[k - 1][0] if k else "", next=chars[j][0] if j < len(chars) else "",
                                           prev_glyph=pg[0] if pg else "", next_glyph=ng[0] if ng else "",
                                           before="".join(c[0] for c in chars[max(0, k - 8) : k]) if pg else "",
                                           gap_before=round(left - pg[1][2], 2) if pg else None,
                                           gap_after=round(ng[1][0] - right, 2) if ng else None,
                                           raise_=round(bottom - ref[1][1], 2) if ref else None))  # fmt: skip
                    k = j
                else:
                    k += 1
            if marks:
                out[no] = marks
    finally:
        doc.close()
    return out


HEADING_TOKENS = re.compile(r"§\s*\d|\bArt(?:ikel|\.)\s*\d|\b(?:Teil|TEIL|Kapitel|KAPITEL|Abschnitt|ABSCHNITT|Anlage|Anhang|ANHANG)\b")


def extract_region_lines(pdf: Path, items: list[SourceItem]) -> dict[str, list[RegionLine]]:
    """Visual lines (from ``extract_text_lines``) clipped to each table cell and to each text item that names
    several headings (a merged TOC line such as "§ 1 Anwendungsbereich § 2 Begriffe"). Lines of other items
    are not needed."""
    import pypdfium2 as pdfium

    wanted: list[tuple[SourceItem, list[tuple[list[int] | None, int, object]]]] = []
    for it in items:
        if it.is_furniture or not it.provenance or any(p.bbox is None for p in it.provenance):
            continue
        if it.table is not None and it.table.cells:
            wanted.append((it, [([c.row, c.col], c.page_no, c.bbox) for c in it.table.cells if c.bbox is not None]))
        elif it.table is None and len(HEADING_TOKENS.findall(it.orig)) >= 2:
            wanted.append((it, [(None, p.page_no, p.bbox) for p in it.provenance]))
    if not wanted:
        return {}
    lines = extract_text_lines(pdf, sorted({p for _, boxes in wanted for _, p, _ in boxes}))
    doc = pdfium.PdfDocument(str(pdf))
    out: dict[str, list[RegionLine]] = {}
    try:
        tps: dict[int, object] = {}
        for it, boxes in wanted:
            rows = []
            for cell, page, b in boxes:
                h = doc[page - 1].get_height()
                left, bottom, right, top = (b.l, h - b.b, b.r, h - b.t) if b.coord_origin.upper().startswith("TOP") else (b.l, b.b, b.r, b.t)
                tp = tps.setdefault(page, doc[page - 1].get_textpage())
                for ln in lines.get(page, []):
                    mid = (ln.top + ln.bottom) / 2
                    if not (bottom - 1 <= mid <= top + 1) or ln.right < left or ln.left > right:
                        continue
                    t = tp.get_text_bounded(left=left - 0.5, bottom=ln.bottom - 0.5, right=right + 0.5, top=ln.top + 0.5)
                    if t.strip():
                        rows.append(RegionLine(cell=cell, page=page, top=ln.top, bottom=ln.bottom, left=max(left, ln.left),
                                               right=min(right, ln.right), text=t))  # fmt: skip
            out[it.ref] = rows
    finally:
        doc.close()
    return out


def write_evidence(pdf: Path, docling_json: Path) -> Path | None:
    """Write the PDF text-layer evidence: the text inside every item's box and the small (superscript) marks
    of every page, plus the visual lines of the pages with overlapping layout boxes. An unreadable PDF is
    recorded as ``error`` (then nothing is repaired) and never fails the pipeline."""
    from importlib.metadata import version

    from odos.normalization.docling_reader import read_docling_json, read_page_sizes
    from odos.normalization.hygiene import detect_layout_overlaps, detect_running_furniture

    from odos.normalization.hygiene import segment_item

    path = Path(docling_json).parent / EVIDENCE_NAME
    _, items = read_docling_json(Path(docling_json))
    pages = {o["page"] for o in detect_layout_overlaps(items, detect_running_furniture(items, read_page_sizes(Path(docling_json))))}  # fmt: skip
    # pages where a merged item is split at a boundary the text alone cannot prove (checked against the lines)
    pages |= {p for it in items if any(s.boundary_flags for s in segment_item(it)) for p in it.pages}
    # pages where an element covers only part of a Docling item: split items and items in overlapping layout boxes
    glyph_pages = sorted(set(pages) | {p for it in items if len(segment_item(it)) > 1 for p in it.pages})
    pages = sorted(pages)
    try:
        lines, error = extract_text_lines(pdf, pages), None
        glyphs = extract_glyph_lines(pdf, glyph_pages)
        item_text, marks, region = extract_item_texts(pdf, items), extract_small_marks(pdf), extract_region_lines(pdf, items)
    except Exception as exc:  # noqa: BLE001 - evidence is optional; without it the items just stay flagged
        lines, item_text, marks, region, glyphs, error = {}, {}, {}, {}, {}, f"{type(exc).__name__}: {exc}"[:300]
    ev = TextLayerEvidence(pdf_sha256=_sha(pdf) if Path(pdf).is_file() else "", docling_json_sha256=_sha(docling_json),
                           extractor=f"pypdfium2 {version('pypdfium2')}", pages=lines, error=error,
                           item_text=item_text, small_marks=marks, region_lines=region, glyph_lines=glyphs)  # fmt: skip
    path.write_text(ev.model_dump_json(indent=1), encoding="utf-8")
    return path


def starts_visual_line(evidence: TextLayerEvidence | None, page: int | None, text: str, min_chars: int = 24) -> bool:
    """True if a visual line of the PDF page starts with the beginning of `text` (compared without
    whitespace and soft hyphens, at least min_chars characters): the text begins on its own line."""
    if evidence is None or page is None:
        return False
    lines = evidence.pages.get(page) or evidence.pages.get(str(page))  # type: ignore[call-overload]
    want = _norm(text)
    if not lines or len(want) < min_chars:
        return False
    for ln in lines:
        have = _norm(ln.text)
        n = min(len(have), len(want))
        if n >= min_chars and have[:n] == want[:n]:
            return True
    return False


def load_evidence(docling_json: Path) -> TextLayerEvidence | None:
    """The evidence next to a Docling JSON, only if it was made for exactly that JSON."""
    path = Path(docling_json).parent / EVIDENCE_NAME
    if not path.is_file():
        return None
    ev = TextLayerEvidence.model_validate(json.loads(path.read_text(encoding="utf-8")))
    return ev if ev.docling_json_sha256 == _sha(docling_json) else None


# ---- repair --------------------------------------------------------------------------------------------------
def _groups(overlaps: list[dict]) -> list[tuple[int, set[str]]]:
    """Connected components of overlapping refs, per page."""
    out: list[tuple[int, set[str]]] = []
    for o in overlaps:
        refs = set(o["refs"])
        joined = [g for g in out if g[0] == o["page"] and g[1] & refs]
        for g in joined:
            out.remove(g)
            refs |= g[1]
        out.append((o["page"], refs))
    return out


def _bbox(it: SourceItem, page: int):
    return next((p.bbox for p in it.provenance if p.page_no == page and p.bbox is not None), None)


def _assign(lines: list[TextLine], involved: list[SourceItem]) -> list[int] | str:
    """Index of the owning item for every line, or why the lines cannot be matched unambiguously."""
    rest = [_norm(it.orig) for it in involved]
    owner = []
    for ln in lines:
        t = _norm(ln.text)
        if not t:
            owner.append(-1)
            continue
        cands = [i for i, r in enumerate(rest) if r.startswith(t)]
        if len(cands) != 1:
            return f"line {ln.text[:40]!r} matches {len(cands)} items"
        rest[cands[0]] = rest[cands[0]][len(t) :]
        owner.append(cands[0])
    if any(rest):
        return "text of the involved items is not fully covered by the text layer"
    return owner


def _slice(orig: str, start_norm: int, end_norm: int) -> tuple[int, int]:
    """Character range in ``orig`` of the normalised range [start_norm, end_norm)."""
    pos, s, e = 0, None, None
    clean = _SOFT.sub(lambda m: "\x00" * len(m.group(0)), unicodedata.normalize("NFKC", orig))
    for i, ch in enumerate(clean):
        if ch == "\x00" or ch.isspace():
            continue
        if pos == start_norm and s is None:
            s = i
        pos += 1
        if pos == end_norm:
            e = i + 1
            break
    return s, e


def repair_reading_order(items: list[SourceItem], overlaps: list[dict], evidence: TextLayerEvidence | None,
                         segments_of) -> tuple[list[SourceItem], list[dict]]:  # fmt: skip
    """Apply the verified repairs; return the new item list and one report entry per overlap group."""
    if evidence is None:
        return items, [{"page": p, "refs": sorted(g), "repaired": False, "reason": "no PDF text-layer evidence"} for p, g in _groups(overlaps)]  # fmt: skip
    by_ref = {it.ref: it for it in items}
    order = [it.ref for it in items]
    replace: dict[str, SourceItem] = {}
    drop: set[str] = set()
    report = []
    for page, group in _groups(overlaps):
        entry = {"page": page, "refs": sorted(group, key=order.index), "repaired": False}
        report.append(entry)
        lines = evidence.pages.get(page) or evidence.pages.get(str(page))  # type: ignore[call-overload]
        if not lines:
            entry["reason"] = "no text-layer lines for this page"
            continue
        idx = sorted(order.index(r) for r in group)
        pred = next((order[i] for i in range(idx[0] - 1, -1, -1) if not by_ref[order[i]].is_furniture), None)
        involved = [by_ref[r] for r in ([pred] if pred and _bbox(by_ref[pred], page) else []) + [order[i] for i in idx]]
        boxes = [_bbox(it, page) for it in involved]
        lo, hi = min(min(b.t, b.b) for b in boxes), max(max(b.t, b.b) for b in boxes)
        region = [ln for ln in lines if lo - 1 <= (ln.top + ln.bottom) / 2 <= hi + 1]
        owner = _assign(region, involved)
        if isinstance(owner, str):
            entry["reason"] = owner
            continue
        seq = [(i, ln) for i, ln in zip(owner, region) if i >= 0]
        runs: list[list] = []  # [item index, [lines]]
        for i, ln in seq:
            if runs and runs[-1][0] == i:
                runs[-1][1].append(ln)
            else:
                runs.append([i, [ln]])
        scattered = {i for i in {r[0] for r in runs} if sum(r[0] == i for r in runs) > 1}
        if len(scattered) != 1:
            entry["reason"] = f"{len(scattered)} items with non-contiguous lines (exactly one stray item is repairable)"
            continue
        stray = scattered.pop()
        moves, ok, pos = [], True, 0
        seen_last = {}
        for k, (i, ln_run) in enumerate(runs):
            seen_last[i] = k
        for k, (i, ln_run) in enumerate(runs):
            if i != stray:
                continue
            if k == 0 or seen_last[runs[k - 1][0]] != k - 1 or runs[k - 1][0] == stray:
                ok = False  # not directly after the last line of another item
                break
            n = sum(len(_norm(ln.text)) for ln in ln_run)
            s, e = _slice(involved[stray].orig, pos, pos + n)
            pos += n
            target = involved[runs[k - 1][0]]
            moves.append({"text": involved[stray].orig[s:e], "from": [involved[stray].ref, s, e], "appended_to": target.ref,
                          "after_line": runs[k - 1][1][-1].text.strip(), "line_boxes": [[ln.left, ln.top, ln.right, ln.bottom] for ln in ln_run]})  # fmt: skip
        targets = {m["appended_to"] for m in moves}
        if not ok or not moves or any(len(segments_of(by_ref[t])) > 1 for t in targets):
            entry["reason"] = "a stray line is not the continuation of a complete item, or a receiving item is segmented"
            continue
        if " ".join(m["text"] for m in moves).split() != involved[stray].orig.split():
            entry["reason"] = "the moved slices do not reproduce the stray item"
            continue
        sref = involved[stray].ref
        for t in targets:
            base = by_ref[t]
            pieces = [m for m in moves if m["appended_to"] == t]
            orig = " ".join([base.orig.rstrip(), *[m["text"] for m in pieces]])  # one line of running text, as Docling's items
            text = " ".join([base.text.rstrip(), *[m["text"] for m in pieces]])
            parts = [_span(base, page, 0, len(base.orig.rstrip()))] + [_span(by_ref[sref], page, m["from"][1], m["from"][2]) for m in pieces]  # fmt: skip
            replace[t] = base.model_copy(update={
                "orig": orig, "text": text, "parts": parts,
                "provenance": [*base.provenance, *by_ref[sref].provenance],
                "order_flags": [*base.order_flags, "layout_box_overlaps_other_item", "repaired_from_pdf_text_layer"],
                "hygiene_flags": [*base.hygiene_flags, "reading_order_repaired_from_pdf_text_layer"],
            })  # fmt: skip
        drop.add(sref)
        entry.update(repaired=True, stray_item=sref, moves=moves, evidence=f"{evidence.extractor}, PDF sha256 {evidence.pdf_sha256}")
    out = [replace.get(it.ref, it) for it in items if it.ref not in drop]
    return out, report


def _span(it: SourceItem, page: int, s: int, e: int) -> SourceSpan:
    return SourceSpan(ref=it.ref, start=s, end=e, page_no=page, bbox=_bbox(it, page))
