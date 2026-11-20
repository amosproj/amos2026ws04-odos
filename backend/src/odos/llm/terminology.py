"""Fact-identifier terminology per document language: English names for words of the document's language.

Fact identifiers are English (see `profiles.GENERAL_INSTRUCTIONS`, rule 5). A model that reads a German text tends to
transliterate instead (`abstandsflaeche_tiefe`, `gebaeudeklasse`). This module serves two purposes:

* the prompt: `prompt_terms(language)` lists preferred translations, so the model is told what the English names are;
* the checks: `translate_fact` translates an identifier whose words are ALL known (`gebaeudeklasse` -> `building_class`)
  - a word-for-word dictionary translation, not a transliteration; `foreign_words` names the words of an identifier that
  are recognisably in the document's language, so a reviewer is pointed at identifiers that could not be translated.

Only languages listed in `LEXICONS` are checked; English documents need no lexicon. Adding a language means adding one
`Lexicon`. The terms are general vocabulary of legislation and of the regulated objects (buildings, products), not the
terms of one particular law.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

FOLD = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe", "Ü": "ue"})


def fold(word: str) -> str:
    """Lower case with umlauts written out (the ASCII spelling a model uses when it transliterates)."""
    return word.translate(FOLD).lower()


@dataclass(frozen=True)
class Lexicon:
    language: str
    terms: dict[str, str]  # word as written in the document's language -> English snake_case
    function_words: frozenset[str] = field(default_factory=frozenset)  # recognisably foreign, never translated
    suffixes: tuple[str, ...] = ()  # word endings that are recognisably foreign (checked on words of 6+ letters)
    inflections: tuple[str, ...] = ()  # endings stripped to find a term ("abstandsflaechen" -> "abstandsflaeche")

    def folded_terms(self) -> dict[str, str]:
        return {fold(k): v for k, v in self.terms.items()}


GERMAN = Lexicon(
    language="de",
    terms={
        # general legal vocabulary
        "Anforderung": "requirement", "Antrag": "request", "Anzahl": "count", "Behörde": "authority", "Dauer": "duration",
        "Einhaltung": "compliance", "erforderlich": "required", "Frist": "deadline", "Genehmigung": "permit",
        "Prüfung": "inspection", "unzulässig": "prohibited", "vorhanden": "present", "zulässig": "permitted",
        "Jahr": "year", "Jahre": "years", "Monat": "month", "Tag": "day", "Woche": "week",
        "und": "and", "oder": "or", "mit": "with", "ohne": "without", "nicht": "not",
        # actors
        "Bauherr": "client", "Betreiber": "operator", "Bevollmächtigter": "authorised_representative", "Einführer": "importer",
        "Eigentümer": "owner", "Händler": "distributor", "Hersteller": "manufacturer", "Marktüberwachungsbehörde": "market_surveillance_authority",
        "Nutzer": "user", "Verwender": "user",
        # buildings and plots
        "Abstand": "distance", "Abstände": "distances", "Abstandsfläche": "setback_area", "Außenwand": "exterior_wall",
        "Außenwände": "exterior_walls", "Bauteil": "building_component", "Baugebiet": "building_zone", "Breite": "width",
        "Dach": "roof", "Dachaufbau": "roof_structure", "Dachhöhe": "roof_height", "Dachneigung": "roof_pitch",
        "Fläche": "area", "Gebäude": "building", "Gebäudeabstand": "building_distance", "Gebäudeklasse": "building_class",
        "Gelände": "terrain", "Geländeoberfläche": "ground_surface", "Geschoss": "storey", "Gewerbegebiet": "commercial_zone",
        "Grenze": "boundary", "Grundfläche": "footprint_area", "Grundstück": "plot", "Grundstücksgrenze": "plot_boundary",
        "Höhe": "height", "Industriegebiet": "industrial_zone", "Länge": "length", "Maß": "measure",
        "Nachbargrenze": "neighbouring_boundary", "Neigung": "pitch", "Nutzungseinheit": "usage_unit", "Tiefe": "depth",
        "Verkehrsfläche": "traffic_area", "Vorbau": "projection", "Vorbauten": "projections", "Wand": "wall",
        "Wandhöhe": "wall_height", "Wohngebäude": "residential_building",
        # products and machinery
        "Betriebsanleitung": "instructions", "Gefahr": "hazard", "Gesundheit": "health", "Kennzeichnung": "marking",
        "Konformitätserklärung": "declaration_of_conformity", "Maschine": "machine", "Produkt": "product",
        "Quellcode": "source_code", "Risiko": "risk", "Sicherheit": "safety", "Steuerung": "control_system",
        "technisch": "technical", "technische": "technical", "Unterlagen": "documentation", "Verpackung": "packaging",
    },
    function_words=frozenset({"nach", "bei", "von", "fuer", "der", "das", "des", "dem", "den", "ein", "eine", "einer",
                              "auf", "zu", "zur", "zum", "im", "vom", "ueber", "unter", "gegen", "sowie", "gemaess",
                              "ist", "sind", "wird", "werden", "muss", "darf", "kein", "keine"}),
    suffixes=("ung", "ungen", "keit", "heit", "lich", "schaft", "isch", "flaeche", "hoehe", "gebaeude"),
    inflections=("en", "n", "e", "es", "s"),
)

LEXICONS: dict[str, Lexicon] = {GERMAN.language: GERMAN}


def lexicon_for(language: str | None) -> Lexicon | None:
    return LEXICONS.get((language or "").split("-")[0].lower())


def _lookup(word: str, terms: dict[str, str], inflections: tuple[str, ...]) -> str | None:
    if word in terms:
        return terms[word]
    for ending in inflections:
        if word.endswith(ending) and word[: -len(ending)] in terms:
            return terms[word[: -len(ending)]]
    return None


def translate_fact(name: str, language: str | None) -> str | None:
    """The English identifier if every word of every segment is a known term of the document's language, else None
    (also None if nothing changes). Accepts the transliterated (`gebaeudeklasse`) and the original spelling
    (`gebäudeklasse`). A partly known identifier is never half-translated: that is left to `foreign_words` and review."""
    lexicon = lexicon_for(language)
    if lexicon is None or not name:
        return None
    terms = lexicon.folded_terms()
    translated_any = False
    segments = []
    for segment in fold(name).split("."):
        words = []
        for word in segment.split("_"):
            english = _lookup(word, terms, lexicon.inflections)
            if english is None:
                return None
            translated_any = translated_any or english != word
            words.append(english)
        segments.append("_".join(words))
    result = ".".join(segments)
    return result if translated_any and re.fullmatch(r"[a-z][a-z0-9_.]*", result) else None


def foreign_words(name: str, language: str | None) -> list[str]:
    """The words of an ASCII identifier that are recognisably in the document's (non-English) language."""
    lexicon = lexicon_for(language)
    if lexicon is None:
        return []
    terms = lexicon.folded_terms()
    long_terms = [t for t in terms if len(t) >= 6]
    found = []
    for word in re.split(r"[._]", fold(name)):
        if not word:
            continue
        known = _lookup(word, terms, lexicon.inflections)
        if (known is not None and known != word) or word in lexicon.function_words \
                or (len(word) >= 6 and word.endswith(lexicon.suffixes)) \
                or any(t in word for t in long_terms if t != word):
            found.append(word)
    return found


def prompt_terms(language: str | None, limit: int = 80) -> str:
    """A short list of preferred translations for the prompt, e.g. `Abstandsfläche -> setback_area`."""
    lexicon = lexicon_for(language)
    if lexicon is None:
        return ""
    pairs = [(k, v) for k, v in lexicon.terms.items() if k[0].isupper() and "_" not in k][:limit]
    return ", ".join(f"{k} -> {v}" for k, v in pairs)
