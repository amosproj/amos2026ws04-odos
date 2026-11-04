"""What a small (superscript) mark in the PDF is: a Satz number, a footnote reference, an exponent, or unclear.

One classifier for sentences and footnotes, so no mark can count as both. It uses only the PDF's geometry
(``reading_order.SmallMark``: gaps to the neighbouring glyphs on the same line, the glyphs themselves):

* ``exponent``           "1 000 m2": a 2 or 3 right after a unit (m, cm, dm, km, mm) that follows a number;
* ``sentence_number``    glued to the start of the next word ("1Die", "2§ 18", "[3Wird"), or set after a sentence
                         end / at the start of a line before a capital ("Zeugnisses. 2 Dies");
* ``reference_attached`` glued to the previous glyph and followed by a space or the line end ("VwVfG1 finden",
                         "bescheinigten]3", "Land ….*) zu");
* ``reference_spaced``   a space on both sides (or the line end after it), not after a sentence end
                         ("der höheren 1 Bauaufsichtsbehörde", "7. … 1");
* ``ambiguous``          everything else (e.g. "]26 kann": a reference 2 and a 6, or a reference 26?).
"""

from __future__ import annotations

import re

GLUED = 3.0  # pt: at most this gap counts as glued (body text at ~12 pt has word spaces of 3-4 pt and more)
SENTENCE_END = ".:;"
STARTS_SENTENCE = re.compile(r"[A-ZÄÖÜ§\[„(\"]")
UNIT_BEFORE = re.compile(r"\d\s*(?:[ckdm]?m)$")


def classify(mark) -> str:
    text = mark.text
    ng, pg = mark.next_glyph or "", mark.prev_glyph or ""
    ga, gb = mark.gap_after, mark.gap_before
    glued_after = ng != "" and ga is not None and ga <= GLUED
    glued_before = pg != "" and gb is not None and 0 <= gb <= GLUED - 0.5
    if text in ("2", "3") and glued_before and UNIT_BEFORE.search(mark.before or ""):
        return "exponent"
    if glued_after and ng.isalnum() or glued_after and ng in "§[„(\"":
        if STARTS_SENTENCE.match(ng) or ng.isdigit():
            return "sentence_number"
        return "ambiguous"  # glued to a lowercase word: neither a Satz number nor a reference
    if "*" in text:
        return "reference_attached" if glued_before or pg in "….)" else "ambiguous"
    if glued_before:
        return "reference_attached"
    if (pg == "" or pg in SENTENCE_END or pg == ")") and ng and STARTS_SENTENCE.match(ng):
        return "sentence_number"
    if pg and pg not in SENTENCE_END and (not ng or not STARTS_SENTENCE.match(ng) or pg.isalnum() or pg in "]…"):
        return "reference_spaced"  # after a word, "]" or "…", also at the end of a line ("7. … 1")
    return "ambiguous"


def is_reference(cls: str) -> bool:
    return cls in ("reference_attached", "reference_spaced")
