"""Recognition rules of the German-law profile (§, Teil/Kapitel/Abschnitt, Absatz, Nummer, Buchstabe), so the
recognizer stays reusable across German laws. Language data (ordinal words, months) lives in `lang_de`."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from odos.normalization.lang_de import ORDINAL_STEMS
from odos.document_model import ElementType

NUM = r"(\d+[a-z]?)"

ORDINAL_KINDS = {"Teil": ElementType.TEIL, "Kapitel": ElementType.KAPITEL, "Abschnitt": ElementType.ABSCHNITT,
                 "Unterabschnitt": ElementType.UNTERABSCHNITT}  # fmt: skip


@dataclass(frozen=True)
class LegalStructureRules:
    toc_titles: tuple[str, ...] = ("inhaltsübersicht", "inhaltsverzeichnis")
    footnote_titles: tuple[str, ...] = ("fußnote",)
    # structural headings: type -> regex with groups (number, title)
    headings: dict[ElementType, re.Pattern] = field(
        default_factory=lambda: {
            ElementType.TEIL: re.compile(rf"^Teil\s+{NUM}\b\s*(.*)$", re.S),
            ElementType.KAPITEL: re.compile(rf"^Kapitel\s+{NUM}\b\s*(.*)$", re.S),
            ElementType.UNTERABSCHNITT: re.compile(rf"^Unterabschnitt\s+{NUM}\b\s*(.*)$", re.S),
            ElementType.ABSCHNITT: re.compile(rf"^Abschnitt\s+{NUM}\b\s*(.*)$", re.S),
            ElementType.PARAGRAPH: re.compile(rf"^§\s*{NUM}\b\s*(.*)$", re.S),
            ElementType.ANLAGE: re.compile(r"^Anlage\s+(\d+[a-z]?|[IVX]+)\b\s*(.*)$", re.S),
        }
    )
    # hierarchy depth: a node closes every open node of equal or deeper level
    levels: dict[ElementType, int] = field(
        default_factory=lambda: {
            ElementType.TEIL: 1,
            ElementType.ANLAGE: 1,
            ElementType.KAPITEL: 2,
            ElementType.ABSCHNITT: 3,
            ElementType.UNTERABSCHNITT: 4,
            ElementType.PARAGRAPH: 5,
            ElementType.ABSATZ: 6,
            ElementType.NUMMER: 7,
            ElementType.BUCHSTABE: 8,
            ElementType.DOPPELBUCHSTABE: 9,
        }
    )
    absatz: re.Pattern = re.compile(rf"^\({NUM}\)\s*(.*)$", re.S)
    nummer_marker: re.Pattern = re.compile(rf"^{NUM}\.$")
    nummer_text: re.Pattern = re.compile(rf"^\[?{NUM}\.\s+(\S.*)$", re.S)
    buchstabe_marker: re.Pattern = re.compile(r"^([a-z])\)$")
    doppelbuchstabe_marker: re.Pattern = re.compile(r"^([a-z]{2})\)$")
    # a real § heading is "§ 12 Title" with a capitalised title word
    paragraph_heading_strict: re.Pattern = re.compile(r"^§\s*\d+[a-z]?\s+\S")
    paragraph_heading_any: re.Pattern = re.compile(r"^§\s*\d+[a-z]?(\s+\S.*)?$", re.S)
    ordinal_heading: re.Pattern = re.compile(
        r"^(?P<ord>" + "|".join(sorted(ORDINAL_STEMS, key=len, reverse=True))
        + r")(?:er|es|e|en)\s+(?P<kind>Teil|Kapitel|Unterabschnitt|Abschnitt)\b\s*(?P<title>.*)$", re.S)  # fmt: skip
    buchstabe_text: re.Pattern = re.compile(r"^([a-z])\)\s+(\S.*)$", re.S)
    # a heading line that lost its "§" in the source: "23 Zertifizierung"
    numeric_heading: re.Pattern = re.compile(r"^(\d+[a-z]?)\s+([A-ZÄÖÜ]\S.*)$", re.S)


GERMAN_LAW_RULES = LegalStructureRules()


def number_key(number: str) -> tuple[int, str]:
    m = re.match(r"(\d+)([a-z]?)$", number)
    return (int(m.group(1)), m.group(2)) if m else (-1, number)
