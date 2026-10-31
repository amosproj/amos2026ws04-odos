"""German language data, shared by every profile that reads German-language text.

Language is not the legal system: a German-language EU regulation uses this module as much as a German statute.
A future English-language profile gets its own `lang_en` with the same names.
"""

from __future__ import annotations

import re

MONTH_NAMES = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
               "November", "Dezember")  # fmt: skip
MONTHS = {m: i for i, m in enumerate(MONTH_NAMES, 1)}  # exact spelling, as printed in dates ("vom 14. Juni 2023")
MONTHS_UPPER = {m.upper(): i for m, i in MONTHS.items()}  # "FASSUNG NOVEMBER 2002"
MONTHS_LOWER = frozenset(m.lower() for m in MONTH_NAMES)

# "Erster Teil", "Zweiter Abschnitt", "Erstes Kapitel", ... -> number
ORDINAL_STEMS = {
    "Erst": 1, "Zweit": 2, "Dritt": 3, "Viert": 4, "Fünft": 5, "Sechst": 6, "Siebent": 7, "Siebt": 7,
    "Acht": 8, "Neunt": 9, "Zehnt": 10, "Elft": 11, "Zwölft": 12, "Dreizehnt": 13, "Vierzehnt": 14,
    "Fünfzehnt": 15, "Sechzehnt": 16, "Siebzehnt": 17, "Achtzehnt": 18, "Neunzehnt": 19, "Zwanzigst": 20,
}  # fmt: skip

# a period after these does not end a sentence ("Abs.", "Nr.", "z. B." ...)
ABBREVIATIONS = {
    "abs", "nr", "nrn", "art", "artt", "s", "bzw", "ggf", "vgl", "buchst", "unterabs", "abl", "rn", "ff", "f", "kap",
    "anh", "anl", "gem", "ca", "sog", "inkl", "zzgl", "ziff", "lit", "bspw", "usw", "etc", "evtl", "max", "min",
    "mind", "bzgl", "einschl", "entspr", "insb", "insbes", "allg", "dgl", "hs", "halbs", "bgbl", "abschn", "dr",
    "prof", "hrsg", "std", "mio", "mrd", "zul", "anm", "fn", "abb", "tab", "lfd", "bek", "v", "vom", "i", "e",
    "u", "o", "a", "z", "d", "h", "m", "nachf", "geänd", "aufgeh", "neugef", "verk", "ber", "st", "pkt",
}  # fmt: skip
# units of measurement take no period: "mindestens 3 m." ends the sentence
UNITS = {"m", "cm", "mm", "km", "dm", "kg", "g", "t", "h", "min", "l", "kw", "kv", "v", "db", "m²", "m³", "ha"}
# short words that can end a sentence ("... den Beschäftigten zu.")
SHORT_WORDS = {"zu", "ab", "an", "um", "da", "so", "es", "er", "ob", "in", "im", "am", "wo", "ja", "je", "ihm", "ihn", "uns"}  # fmt: skip

# a hyphen before these is a suspended hyphen ("Gewerbe- und Industriegebiete"), never a word division
HYPHEN_CONJUNCTION = re.compile(r"(und|oder|bzw\.|sowie)(?![\wäöüß])")
