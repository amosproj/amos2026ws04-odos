"""Restore characters that Docling normalised away, using the PDF's own text layer as evidence.

Docling's page assembly (`sanitize_text`) drops every hyphen at a line end between two words and replaces
typographic quotes and dashes by ASCII. The PDF text inside an item's box (``reading_order`` evidence,
``item_text``) shows what is printed. A difference is repaired only if the two texts are identical apart from
exactly those normalisations (whitespace ignored); any other difference leaves the item untouched, and the
source-fidelity check reports it.

Line-end hyphens. The PDF prints a hyphen; Docling removed it. Whether it is part of the text (a compound
"CE-Zeichen", a suspended hyphen "Gewerbe- und") or only a word division ("Brandschutznach-|weisen") is decided
by fixed rules, then by the document itself:

* before "und" / "oder" / "bzw." / "sowie"                       -> "Gewerbe- und"     (suspended hyphen)
* before a capital letter, after a non-capital word               -> "CE-Zeichen"       (German word division never
                                                                                         continues with a capital)
* before a non-letter                                              -> "Sport-,"          (no word continues there)
* otherwise the same document decides: the hyphenated form printed mid-line elsewhere and never joined -> hyphen;
  joined elsewhere and never hyphenated -> Docling's join stands (a word division);
* no or conflicting evidence: the printed hyphen is kept and the repair is ``unresolved`` (for human review).

Every decision, including "Docling was right", is recorded as a ``TextRepair`` with its evidence.
"""

from __future__ import annotations

import re
from collections import Counter

from odos.normalization.docling_reader import SourceItem
from odos.normalization.lang_de import HYPHEN_CONJUNCTION
from odos.document_model import DocumentModel, TextRepair

LINE_END_HYPHEN = "\x02￾"  # pypdfium2: a hyphen the PDF sets at a line end
SOFT_HYPHEN = "\xad"
TYPOGRAPHY = {'"': "„“”‟″", "'": "‘’‚‛′", "-": "–—‑‒−", "/": "⁄", "·": "•"}  # Docling's ASCII -> printed characters
LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}  # expanded by Docling, kept so
WORD_END = re.compile(r"[A-Za-zÄÖÜäöüß]+$")
WORD_START = re.compile(r"^[A-Za-zÄÖÜäöüß]+")


def _pdf_text(boxes: list[str]) -> tuple[str, list[int]]:
    """The item's text-layer string (boxes joined by a line break) and the start offset of each box."""
    starts, out = [], []
    pos = 0
    for b in boxes:
        b = "".join(LIGATURES.get(c, c) for c in b)
        starts.append(pos)
        out.append(b)
        pos += len(b) + 1
    return "\n".join(out), starts


def align(docling: str, pdf: str) -> list[tuple] | None:
    """Events that turn `docling` into `pdf`, or None if they differ in any other way. Whitespace is ignored.

    ("typo", i, j, char)    docling[i] is Docling's ASCII form of the printed `char` (pdf index j)
    ("hyphen", i, j, kept)  the PDF prints a line-end hyphen (pdf index j) before docling[i]; kept = Docling kept it
    """
    i = j = 0
    events: list[tuple] = []
    nd, np_ = len(docling), len(pdf)
    while True:
        while i < nd and docling[i].isspace():
            i += 1
        while j < np_ and pdf[j].isspace():
            j += 1
        if i < nd and j < np_ and docling[i] == pdf[j]:
            i += 1
            j += 1
            continue
        if j < np_ and pdf[j] in LINE_END_HYPHEN and i < nd and docling[i] == SOFT_HYPHEN:
            i += 1  # the PDF's soft hyphen at a line end, kept by Docling as U+00AD: the same printed word division
            j += 1
            continue
        if i < nd and docling[i] == SOFT_HYPHEN:
            i += 1
            continue
        if j < np_ and pdf[j] == SOFT_HYPHEN:
            j += 1
            continue
        if j < np_ and (pdf[j] in LINE_END_HYPHEN or (pdf[j] == "-" and "\n" in pdf[j + 1 : j + 3].replace("\r", "\n"))):
            kept = i < nd and docling[i] == "-"
            events.append(("hyphen", i, j, kept))
            i += 1 if kept else 0
            j += 1
            continue
        if i >= nd and j >= np_:
            return events
        if i < nd and j < np_ and docling[i] in TYPOGRAPHY and pdf[j] in TYPOGRAPHY[docling[i]]:
            events.append(("typo", i, j, pdf[j]))
            i += 1
            j += 1
            continue
        return None


class Lexicon:
    """How often a hyphenated or a joined form is printed mid-line in this document's text layer."""

    def __init__(self, texts: list[str]):
        self.text = "\n".join(texts)
        self._cache: dict[str, int] = {}

    def count(self, s: str) -> int:
        if s not in self._cache:
            self._cache[s] = len(re.findall(re.escape(s), self.text))
        return self._cache[s]


def _decide_hyphen(left: str, right: str, lex: Lexicon) -> tuple[str, str, str, str]:
    """(inserted text, status, rule, evidence) for a line-end hyphen Docling dropped."""
    lw = WORD_END.search(left)
    lw = lw.group(0) if lw else ""
    if right[:1] and not right[0].isalpha():
        return "-", "verified", "hyphen_before_non_letter", f"followed by {right[:1]!r}: no word continues there"
    if m := HYPHEN_CONJUNCTION.match(right):
        return "- ", "verified", "suspended_hyphen_before_conjunction", f"followed by {m.group(1)!r}"
    rw = WORD_START.match(right)
    rw = rw.group(0) if rw else ""
    if right[:1].isupper() and lw and not (lw.isupper() and rw.isupper()):  # all-caps text (headings) excepted
        return "-", "verified", "hyphen_before_capital", "word division never continues a word with a capital letter"
    if not lw or not rw:
        return "-", "unresolved", "no_word_context", "printed hyphen kept"
    stem = rw[:3]
    hy, jo = lex.count(f"{lw}-{stem}"), lex.count(f"{lw}{stem}")
    ev = f"'{lw}-{stem}' printed mid-line {hy}x, '{lw}{stem}' {jo}x in this document"
    if hy and not jo:
        return "-", "verified", "hyphenated_form_elsewhere_in_document", ev
    if jo and not hy:
        return "", "verified", "joined_form_elsewhere_in_document", ev + " (a word division: Docling's join stands)"
    return "-", "unresolved", "conflicting_document_evidence" if hy and jo else "no_document_evidence", ev + "; printed hyphen kept"


def restore(docling: str, boxes: list[str], ref: str, pages: list[int], lex: Lexicon, extractor: str):
    """(canonical text, repairs, new_pos) or None when the PDF text differs in any other way than Docling's
    normalisations. new_pos maps a position in Docling's text to the canonical text."""
    pdf, starts = _pdf_text(boxes)
    events = align(docling, pdf)
    if events is None:
        return None
    out, repairs, pos = [], [], 0
    deltas: list[tuple[int, int]] = []  # (docling position, length change)

    def page_at(j: int) -> int | None:
        k = max((n for n, s in enumerate(starts) if s <= j), default=0)
        return pages[k] if k < len(pages) else None

    for ev in events:
        if ev[0] == "hyphen" and ev[3]:  # Docling kept the printed hyphen: nothing to do
            continue
        i = ev[1]
        out.append(docling[pos:i])
        at = sum(len(x) for x in out)
        if ev[0] == "typo":
            out.append(ev[3])
            repairs.append(TextRepair(ref=ref, kind="typography", status="verified", rule="typographic_character_from_pdf",
                                      start=at, end=at + 1, docling=docling[i], restored=ev[3], page=page_at(ev[2]),
                                      evidence=f"{extractor}: the PDF prints {ev[3]!r}"))  # fmt: skip
            pos = i + 1
        else:
            insert, status, rule, why = _decide_hyphen(docling[:i], docling[i:], lex)
            out.append(insert)
            repairs.append(TextRepair(ref=ref, kind="line_end_hyphen", status=status, rule=rule, start=at, end=at + len(insert),
                                      docling="", restored=insert, page=page_at(ev[2]),
                                      evidence=f"{extractor}: hyphen at a line end; {why}"))  # fmt: skip
            deltas.append((i, len(insert)))
            pos = i
    out.append(docling[pos:])

    def new_pos(p: int) -> int:
        return p + sum(d for at_, d in deltas if at_ < p)

    return "".join(out), repairs, new_pos


def revert(text: str, repairs: list[TextRepair], offset: int = 0) -> str:
    """Docling's text from the canonical text: undo the repairs (positions relative to `offset`)."""
    for r in sorted(repairs, key=lambda r: r.start, reverse=True):
        s, e = r.start - offset, r.end - offset
        text = text[:s] + r.docling + text[e:]
    return text


def restore_items(items: list[SourceItem], evidence) -> list[SourceItem]:
    """Apply the verified restorations to the Docling items (before segmentation). Without evidence: unchanged."""
    if evidence is None or not getattr(evidence, "item_text", None):
        return items
    lex = Lexicon([t for boxes in evidence.item_text.values() for t in boxes])
    out = []
    for it in items:
        boxes = evidence.item_text.get(it.ref)
        if not boxes or it.is_furniture or it.parts or it.table is not None:
            out.append(it)
            continue
        res = restore(it.orig, boxes, it.ref, [p.page_no for p in it.provenance], lex, evidence.extractor)
        if res is None or not res[1]:
            out.append(it)
            continue
        orig, repairs, new_pos = res
        if not it.orig.endswith(it.text):  # Docling's `text` is `orig` without its list marker; otherwise do not touch
            out.append(it)
            continue
        new_prefix = new_pos(len(it.orig) - len(it.text))
        out.append(it.model_copy(update={
            "orig": orig, "text": orig[new_prefix:], "docling_orig": it.orig, "text_repairs": repairs,
            "hygiene_flags": [*it.hygiene_flags, "text_restored_from_pdf_text_layer"] if any(r.restored != r.docling for r in repairs) else it.hygiene_flags,
        }))  # fmt: skip
    return out


# ---- source fidelity: the canonical model against the PDF ---------------------------------------------------------
def source_fidelity(model: DocumentModel, evidence) -> dict:
    """Compare each element's text with the PDF text layer inside its source boxes.

    Equality with the internal model (``legal_json.verify``) does not show that the text is the PDF's; this does,
    as far as the PDF has a text layer."""
    if evidence is None or not getattr(evidence, "item_text", None):
        return {"pdf_text_layer": False, "note": "no PDF text-layer evidence: fidelity to the PDF is not verified"}
    by_ref: dict[str, list] = {}
    for e in [*model.elements, *model.furniture]:
        for r in e.source_refs:
            by_ref.setdefault(r, []).append(e)
    counts: Counter = Counter()
    unexplained, not_verifiable = [], Counter()
    for ref, boxes in evidence.item_text.items():
        els = by_ref.get(ref, [])
        if not els:
            not_verifiable["item_not_in_model"] += 1
            continue
        if any(e.type.value in ("page_header", "page_footer") for e in els):
            not_verifiable["page_furniture"] += 1
            continue
        if any(len(e.source_refs) > 1 and e.source_spans for e in els):
            not_verifiable["reading_order_repaired_item"] += 1
            continue
        if len(els) > 1 or els[0].source_spans:  # segments of one item (hygiene split): tile the item in order
            segs = sorted(els, key=lambda e: next((s.start for s in e.source_spans if s.ref == ref), 0))
            text = "".join(e.original_text for e in segs)
        elif len(els[0].source_refs) > 1:  # heading whose title came from the next item: one piece per item
            pieces = els[0].original_text.split("\n")
            if len(pieces) != len(els[0].source_refs):
                not_verifiable["merged_item_not_separable"] += 1
                continue
            text = pieces[els[0].source_refs.index(ref)]
        else:
            text = els[0].original_text
        events = align(text, _pdf_text(boxes)[0])
        if events is None:
            unexplained.append({"ref": ref, "elements": [e.id for e in els], "text": text[:80], "pdf": "".join(boxes)[:80]})
            continue
        joins = [ev for ev in events if ev[0] == "hyphen" and not ev[3]]
        decided = sum(1 for e in els for r in e.text_repairs if r.ref == ref and r.rule == "joined_form_elsewhere_in_document")
        if any(ev[0] == "typo" for ev in events) or len(joins) > decided:
            unexplained.append({"ref": ref, "elements": [e.id for e in els], "text": text[:80], "pdf": "".join(boxes)[:80]})
        elif joins:
            counts["identical_except_recorded_word_divisions"] += 1
        else:
            counts["identical"] += 1
    repairs = [r for e in [*model.elements, *model.furniture] for r in e.text_repairs]
    return {
        "pdf_text_layer": True,
        "extractor": evidence.extractor,
        "pdf_sha256": evidence.pdf_sha256,
        "items_compared": sum(counts.values()) + len(unexplained),
        "identical": counts["identical"],
        "identical_except_recorded_word_divisions": counts["identical_except_recorded_word_divisions"],
        "unexplained_differences": unexplained,
        "not_verifiable": dict(not_verifiable),
        "repairs": {
            "verified_text_changes": sum(1 for r in repairs if r.status == "verified" and r.restored != r.docling),
            "verified_docling_kept": sum(1 for r in repairs if r.status == "verified" and r.restored == r.docling),
            "unresolved": [{"ref": r.ref, "rule": r.rule, "page": r.page, "evidence": r.evidence} for r in repairs if r.status == "unresolved"],
            "by_rule": dict(Counter(r.rule for r in repairs)),
        },
        "note": "Tables, pictures and page furniture are not compared. Bold, italics and layout are not part of the check.",
    }
