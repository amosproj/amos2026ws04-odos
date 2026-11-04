"""Numbering style of a printed marker. The marker itself is always exported verbatim."""

from __future__ import annotations

import re

from odos.normalization.numbering import is_roman as _is_roman

_DECIMAL = re.compile(r"^\d+(\.\d+)+\.?$")
_WORD_PREFIX = re.compile(r"^(?P<word>[A-Za-zÄÖÜäöüß]+)\s+(?P<rest>\S.*)$")
_STRIP = re.compile(r"[\s()\[\].]")
# node types whose single letters are Roman numerals ("i)", "KAPITEL I"); elsewhere letters are alphabetic
_ROMAN_TYPES = {"subpoint", "numeral", "chapter", "annex", "section", "title"}


def marker_style(marker: str | None, node_type: str) -> str | None:
    if not marker or not marker.strip():
        return None
    m = marker.strip()
    if m.startswith("§"):
        return "section_sign"
    if re.fullmatch(r"\*+\)?", m):
        return "symbol"
    token = m
    if wm := _WORD_PREFIX.match(m):  # "KAPITEL IX", "ANHANG XII", "TEIL A", "Artikel 54", "Erster Teil"
        rest = wm.group("rest")
        if re.fullmatch(r"[A-ZÄÖÜ][a-zäöüß]+", rest):  # a capitalised word, not a Roman numeral like "XII"
            return "ordinal_word"
        token = rest
    if _DECIMAL.match(token.strip("()[] ")):
        return "decimal_hierarchy"
    core = _STRIP.sub("", token)
    if not core:
        return None
    if core[0].isdigit():
        return "arabic"
    if core.islower():
        if len(core) > 1 and len(set(core)) == 1 and node_type not in _ROMAN_TYPES:
            return "alpha_lower_double"
        if node_type in _ROMAN_TYPES and _is_roman(core):
            return "roman_lower"
        if len(core) > 1 and _is_roman(core):
            return "roman_lower"
        return "alpha_lower"
    if core.isupper():
        if node_type in _ROMAN_TYPES and _is_roman(core):
            return "roman_upper"
        if len(core) > 1 and _is_roman(core):
            return "roman_upper"
        return "alpha_upper"
    return None
