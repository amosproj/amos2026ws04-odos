"""Numbering systems used by legal markers (language- and profile-independent)."""

from __future__ import annotations

import re

_ROMAN = re.compile(r"^M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")


def roman_value(s: str) -> int:
    """'IX' -> 9, 'xii' -> 12 (I, V, X, L, C)."""
    vals = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}
    s = s.lower()
    total = 0
    for a, b in zip(s, s[1:] + " "):
        total += -vals[a] if b != " " and vals.get(b, 0) > vals[a] else vals[a]
    return total


def is_roman(s: str) -> bool:
    """A well-formed Roman numeral, upper or lower case."""
    return bool(s) and bool(_ROMAN.match(s.upper()))
