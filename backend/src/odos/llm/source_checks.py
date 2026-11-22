"""Checks of model-proposed Rule JSON records against the source text in the Legal JSON.

The checks in `rule_checks` look at a record alone; these compare the records with the text they cite:

* QUANTITIES. A threshold, measure, fraction, period or date stated in a cited sentence ("Dächer mit einer Neigung von
  weniger als 70 Grad", "zu einem Drittel", "zehn Jahre", "bis zum 14. Januar 2027") must appear in the machine-readable
  logic (a condition, requirement, formula, duration or deadline) of a record that cites that sentence as `primary`.
  A number that only appears in a `description` or `summary` cannot be checked by a machine, so it is flagged; so is a
  number a record's own description or summary states that its logic does not contain. A number written into an
  `unresolved` predicate or requirement counts as acknowledged.
* COVERAGE. Sentences and elements of the extracted text that no accepted record cites as `primary` are reported in
  `_generation.coverage`, together with those cited only by a rejected candidate. Such text may be non-normative; the
  report makes a silently dropped provision visible, it does not decide. A sentence that no record cites but whose text
  an exception of an accepted record quotes is also listed under `coveredByExceptionText`: its content is probably in the
  record (exceptions have no source of their own), but the match is a text comparison, not provenance, so the sentence
  stays in `uncitedSentences` and is not counted as cited.

Number words, fractions, units and month names are known for German and English (`LANGUAGES`); other languages get the
digit-based part of the check. Nothing here is specific to one law or document type.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator
from dataclasses import dataclass

NON_NORMATIVE_TYPES = {"heading", "recital", "recitalsIntro", "preamble", "preambleFormula", "enactingFormula",
                       "finalFormula", "citation", "conclusions"}

NUMBER_WORDS = {
    "de": {"ein": 1, "eine": 1, "einem": 1, "einer": 1, "einen": 1, "eines": 1, "zwei": 2, "drei": 3, "vier": 4, "fünf": 5, "sechs": 6,
           "sieben": 7, "acht": 8, "neun": 9, "zehn": 10, "elf": 11, "zwölf": 12, "fünfzehn": 15, "zwanzig": 20,
           "dreißig": 30, "vierzig": 40, "fünfzig": 50, "hundert": 100},
    "en": {"one": 1, "a": 1, "an": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
           "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
           "fifty": 50, "hundred": 100},
}
FRACTIONS = {
    "de": {"hälfte": 1 / 2, "drittel": 1 / 3, "viertel": 1 / 4, "fünftel": 1 / 5, "zehntel": 1 / 10},
    "en": {"half": 1 / 2, "third": 1 / 3, "thirds": 1 / 3, "quarter": 1 / 4, "quarters": 1 / 4, "fifth": 1 / 5, "tenth": 1 / 10},
}
MONTHS = {
    "de": ["januar", "februar", "märz", "april", "mai", "juni", "juli", "august", "september", "oktober", "november", "dezember"],
    "en": ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"],
}
DATE_OF_ANOTHER_ACT = re.compile(r"(?:\bvom|\bof|\bdu)\s*$", re.IGNORECASE)
UNIT_WORDS = (r"m|cm|mm|km|m2|m²|m3|m³|%|‰|°C|°|kg|t|kN|N|Pa|kPa|MPa|dB|dB\(A\)|lx|K|W|kW|V|A|s|min|h|"
              r"Meter|Metern|Zentimeter|Millimeter|Kilometer|Quadratmeter|Kubikmeter|Prozent|Grad|Kilogramm|Tonnen|"
              r"Sekunden?|Minuten?|Stunden?|Tag(?:e|en|es)?|Wochen?|Monat(?:e|en|s)?|Jahr(?:e|en|es)?|"
              r"metres?|meters?|percent|degrees?|seconds?|minutes?|hours?|days?|weeks?|months?|years?")
CITATION_WORDS = (r"§§?|Abs\.|Absatz|Absätze|Absätzen|Satz|Sätze|Sätzen|Nr\.|Nummer|Nummern|Buchstabe|Buchstaben|Artikel|Art\.|"
                  r"Anhang|Anhänge|Teil|Kapitel|Abschnitt|Unterabsatz|Ziffer|Verordnung|Richtlinie|Beschluss|"
                  r"Article|Articles|Annex|Annexes|paragraph|paragraphs|point|points|subparagraph|Regulation|Directive|"
                  r"Decision|Section|Chapter|Part|Gebäudeklassen?|Klassen?|class|classes")
_CITED_NUMBER = re.compile(rf"(?:{CITATION_WORDS})\s*(?:[\dIVXivx]+[a-z]?(?:\s*(?:,|bis|und|oder|to|and|or|-)\s*))*$")
_DIGITS = r"\d+(?:[.,]\d+)?(?!\.\d)"


@dataclass(frozen=True)
class Quantity:
    value: float
    text: str

    def matches(self, values: set[float]) -> bool:
        candidates = {self.value, self.value / 100} if "%" in self.text or "rozent" in self.text or "ercent" in self.text else {self.value}
        return any(math.isclose(c, v, rel_tol=0.01, abs_tol=1e-6) for c in candidates for v in values)


def _language(language: str | None) -> str:
    return (language or "").split("-")[0].lower()


def _to_number(token: str, language: str) -> float | None:
    if re.fullmatch(_DIGITS, token):
        if language == "de":
            token = token.replace(".", "").replace(",", ".") if re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", token) else token.replace(",", ".")
        else:
            token = token.replace(",", "")
        try:
            return float(token)
        except ValueError:
            return None
    return NUMBER_WORDS.get(language, {}).get(token.lower())


def quantities(text: str, language: str | None) -> list[Quantity]:
    """Measures with a unit, fractions, decimal factors and periods stated in `text` (not section numbers)."""
    lang = _language(language)
    words = "|".join(sorted(NUMBER_WORDS.get(lang, {}), key=len, reverse=True))
    number = rf"{_DIGITS}" + (rf"|\b(?:{words})\b" if words else "")
    found: list[Quantity] = []
    taken: list[tuple[int, int]] = []

    def add(match: re.Match, value: float) -> None:
        if any(s <= match.start() < e for s, e in taken):
            return
        if _CITED_NUMBER.search(text[max(0, match.start() - 60):match.start()]):
            return
        taken.append(match.span())
        found.append(Quantity(value, match.group(0).strip()))

    fractions = FRACTIONS.get(lang, {})
    if fractions:
        names = "|".join(sorted(fractions, key=len, reverse=True))
        for m in re.finditer(rf"(?:({number})\s+)?\b({names})\b", text, re.IGNORECASE):
            count = _to_number(m.group(1), lang) if m.group(1) else 1
            if count is not None:
                add(m, count * fractions[m.group(2).lower()])
    for m in re.finditer(rf"({number})\s*(?:{UNIT_WORDS})(?![\w²³])", text, re.IGNORECASE if lang else 0):
        value = _to_number(m.group(1), lang)
        if value is not None:
            add(m, value)
    for m in re.finditer(r"(?<![\w.,])(\d+[.,]\d+)(?![\w.,]*\d)", text):  # a bare decimal factor ("0,4 H")
        value = _to_number(m.group(1), lang)
        if value is not None:
            add(m, value)
    return found


def dates(text: str, language: str | None) -> list[tuple[str, str]]:
    """(ISO date, text) of calendar dates in `text`, except the date of another act ("Richtlinie ... vom 17. Mai 2006")."""
    lang = _language(language)
    out = []
    for m in re.finditer(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        out.append((m.group(0), m.group(0)))
    months = MONTHS.get(lang, [])
    if months:
        names = "|".join(months)
        for m in re.finditer(rf"\b(\d{{1,2}})\.?\s+({names})\s+(\d{{4}})\b", text, re.IGNORECASE):
            if DATE_OF_ANOTHER_ACT.search(text[max(0, m.start() - 6):m.start()]):
                continue
            iso = f"{m.group(3)}-{months.index(m.group(2).lower()) + 1:02d}-{int(m.group(1)):02d}"
            out.append((iso, m.group(0)))
    return out


# ── the logic of a record ─────────────────────────────────────────────────────────────────────────────────────────────

_TEXT_KEYS = ("description", "summary")


def _walk(node) -> Iterator[dict]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _logic(rule: dict) -> dict:
    """The parts of a record a machine evaluates (no source, review, descriptions or summary)."""
    return {k: rule.get(k) for k in ("applicability", "requirements", "requirementExpression", "exceptions", "definition")}


def logic_values(rule: dict, language: str | None) -> tuple[set[float], set[str]]:
    """Numbers and ISO dates in the record's machine-readable logic; numbers inside `unresolved` text count too."""
    numbers: set[float] = set()
    iso: set[str] = set()

    def number(v) -> None:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            numbers.add(float(v))
        elif isinstance(v, str) and re.fullmatch(r"-?\d+(?:\.\d+)?", v):
            numbers.add(float(v))

    for node in _walk(_logic(rule)):
        value = node.get("value")
        for v in value if isinstance(value, list) else [value]:
            number(v)
        if node.get("kind") == "operation" and node.get("operator") == "divide":
            operands = node.get("operands") or []
            if len(operands) == 2 and isinstance(operands[1], dict) and operands[1].get("kind") == "literal":
                divisor = operands[1].get("value")
                if isinstance(divisor, (int, float)) and divisor:
                    numbers.add(1 / divisor)
        if isinstance(node.get("deadline"), str):
            iso.add(node["deadline"])
        if node.get("kind") == "unresolved":
            text = f"{node.get('text', '')} {node.get('reason', '')}"
            numbers |= {q.value for q in quantities(text, language)}
            iso |= {d for d, _ in dates(text, language)}
        for key in ("startEvent", "endEvent", "action"):
            if isinstance(node.get(key), str):
                iso |= {d for d, _ in dates(node[key], language)}
    return numbers, iso


def _texts(rule: dict) -> Iterator[str]:
    for node in _walk({k: v for k, v in rule.items() if k not in ("source", "review")}):
        for key in _TEXT_KEYS:
            if isinstance(node.get(key), str):
                yield node[key]


# ── source text ───────────────────────────────────────────────────────────────────────────────────────────────────────


def _nodes(structure: list[dict]) -> Iterator[dict]:
    for node in structure:
        yield node
        yield from _nodes(node.get("children", []))


@dataclass
class SourceText:
    """The text units of the extracted part of a Legal JSON: its sentences and the elements without sentences."""
    language: str | None
    elements: dict[str, dict]  # element ID -> node (only normative elements in scope with own text)
    sentences: dict[str, str]  # sentence ID -> text (marker removed)
    sentence_elements: dict[str, set[str]]  # sentence ID -> element IDs
    sentences_of: dict[str, list[str]]  # element ID -> sentence IDs on it

    @classmethod
    def of(cls, document: dict, scope: list[str] | None = None) -> "SourceText":
        nodes = list(_nodes(document.get("structure", [])))
        if scope:
            inside: set[str] = set()
            by_id = {n["id"]: n for n in nodes}
            for element_id in scope:
                if element_id in by_id:
                    inside |= {n["id"] for n in _nodes([by_id[element_id]])}
            nodes = [n for n in nodes if n["id"] in inside]
        elements = {n["id"]: n for n in nodes if n.get("type") not in NON_NORMATIVE_TYPES
                    and isinstance(n.get("text"), str) and n["text"].strip()}
        sentences, sentence_elements, sentences_of = {}, {}, {}
        for s in document.get("sentences", []):
            ranges = [r for r in s.get("ranges", []) if isinstance(r, dict)]
            if not ranges or not all(r.get("elementId") in elements for r in ranges):
                continue
            marker = s.get("marker") if isinstance(s.get("marker"), dict) else {}
            parts = []
            for r in ranges:
                text = elements[r["elementId"]]["text"]
                start, end = r.get("start", 0), r.get("end", len(text))
                if marker.get("elementId") == r["elementId"] and marker.get("start") == start:
                    start = max(start, marker.get("end", start))
                parts.append(text[start:end])
            sentences[s["id"]] = " ".join(p.strip() for p in parts)
            sentence_elements[s["id"]] = {r["elementId"] for r in ranges}
            for r in ranges:
                sentences_of.setdefault(r["elementId"], []).append(s["id"])
        return cls(document.get("language"), elements, sentences, sentence_elements, sentences_of)

    def units_cited(self, rule: dict, roles: tuple[str, ...] = ("primary",)) -> set[str]:
        """Sentence IDs (or, for elements without sentences, element IDs) that the record cites with one of `roles`.
        An element cited without a sentence ID stands for all of its sentences."""
        out: set[str] = set()
        source = rule.get("source")
        elements = source.get("elements") if isinstance(source, dict) else None
        for e in elements if isinstance(elements, list) else []:
            if not isinstance(e, dict) or e.get("role", "primary") not in roles:
                continue
            element_id, sentence_id = e.get("elementId"), e.get("sentenceId")
            if not isinstance(element_id, str) or not isinstance(sentence_id, (str, type(None))):
                continue
            if sentence_id in self.sentences:
                out.add(sentence_id)
            elif element_id in self.sentences_of:
                out |= set(self.sentences_of[element_id])
            elif element_id in self.elements:
                out.add(element_id)
        return out

    def text_of(self, unit: str) -> str:
        return self.sentences.get(unit) or self.elements.get(unit, {}).get("text", "")


def check_quantities(rules: list[dict], source: SourceText) -> dict[str, list[str]]:
    """{rule id: flags} for quantities and dates of the cited text (or of the record's own descriptions and summary)
    that are not in the machine-readable logic."""
    language = source.language
    logic = {r["id"]: logic_values(r, language) for r in rules}
    citing: dict[str, list[str]] = {}
    for rule in rules:
        for unit in source.units_cited(rule):
            citing.setdefault(unit, []).append(rule["id"])
    flags: dict[str, list[str]] = {}
    for unit, rule_ids in citing.items():
        numbers = set().union(*(logic[rid][0] for rid in rule_ids))
        iso = set().union(*(logic[rid][1] for rid in rule_ids))
        text = source.text_of(unit)
        missing = [q.text for q in quantities(text, language) if not q.matches(numbers)]
        missing_dates = [t for d, t in dates(text, language) if d not in iso]
        if missing or missing_dates:
            stated = ", ".join(repr(m) for m in [*missing, *missing_dates])
            note = (f"the source text of {unit!r} states {stated}, which no condition, requirement, duration or deadline "
                    "of the records citing it contains; a threshold only in a description cannot be checked.")
            for rid in rule_ids:
                flags.setdefault(rid, []).append(note)
    for rule in rules:
        numbers, iso = logic[rule["id"]]
        reported = " ".join(flags.get(rule["id"], []))
        missing = []
        for text in _texts(rule):
            missing += [q.text for q in quantities(text, language) if not q.matches(numbers) and repr(q.text) not in reported]
            missing += [t for d, t in dates(text, language) if d not in iso and repr(t) not in reported]
        missing = list(dict.fromkeys(missing))
        if missing:
            flags.setdefault(rule["id"], []).append(
                f"the summary or a description states {', '.join(repr(m) for m in missing)}, which the record's "
                "conditions and requirements do not contain; express it as a predicate or requirement.")
    return flags


_WORDS = re.compile(r"\w+", re.UNICODE)
MIN_QUOTED_CHARS = 25  # a shorter sentence is too generic to prove that an exception quotes it
QUOTE_RATIO = 0.9  # how much of a sentence an exception's description must reproduce


def _normalized(text: str) -> str:
    """Words only, lower-case: no sentence number, punctuation or spacing differences."""
    return " ".join(_WORDS.findall(text.casefold()))


def _quotes(description: str, sentence: str) -> bool:
    """The description reproduces the sentence (or the sentence contains the whole description), after normalizing."""
    d, t = _normalized(description), _normalized(sentence)
    if len(t) < MIN_QUOTED_CHARS or len(d) < MIN_QUOTED_CHARS:
        return False
    if t in d:
        return True
    return d in t and len(d) >= QUOTE_RATIO * len(t)


def text_matched_sentences(rules: list[dict], source: SourceText, cited: set[str]) -> list[dict]:
    """Uncited sentences whose text is quoted by the `description` of an exception of an accepted record. Not verified
    provenance: only a normalized text comparison."""
    found: dict[str, list[dict]] = {}
    for rule in rules:
        exceptions = rule.get("exceptions")
        for index, exception in enumerate(exceptions if isinstance(exceptions, list) else []):
            description = exception.get("description") if isinstance(exception, dict) else None
            if not isinstance(description, str):
                continue
            for sentence_id, text in source.sentences.items():
                if sentence_id not in cited and _quotes(description, text):
                    found.setdefault(sentence_id, []).append({"ruleId": rule.get("id"), "exception": index})
    return [{"id": sentence_id, "matchedBy": found[sentence_id], "verified": False} for sentence_id in source.sentences if sentence_id in found]


def coverage(rules: list[dict], source: SourceText, rejected: list[dict] | None = None) -> dict:
    """Which sentences and elements of the extracted text no accepted record cites as `primary`. `coveredByExceptionText`
    lists, separately and unverified, the uncited sentences that an exception's description quotes."""
    cited = set().union(*(source.units_cited(r) for r in rules)) if rules else set()
    cited_elements = {e.get("elementId") for r in rules for e in r.get("source", {}).get("elements", [])
                      if isinstance(e, dict) and e.get("role", "primary") == "primary"}
    in_rejected: set[str] = set()
    for candidate in rejected or []:
        if isinstance(candidate, dict) and isinstance(candidate.get("source"), dict):
            in_rejected |= source.units_cited(candidate)
            elements = candidate["source"].get("elements")
            in_rejected |= {e["elementId"] for e in elements if isinstance(e, dict) and isinstance(e.get("elementId"), str)} \
                if isinstance(elements, list) else set()
    units = [*source.sentences, *(e for e in source.elements if e not in source.sentences_of)]
    uncited_units = [u for u in units if u not in cited]
    uncited_elements = [e for e in source.elements if e not in cited_elements]

    def entry(unit: str) -> dict:
        text = source.text_of(unit)
        return {"id": unit, "text": text[:160] + ("…" if len(text) > 160 else "")}

    return {
        "sentences": len(units), "sentencesCited": len(units) - len(uncited_units),
        "uncitedSentences": [entry(u) for u in uncited_units],
        "elements": len(source.elements), "elementsCited": len(source.elements) - len(uncited_elements),
        "uncitedElements": [entry(e) for e in uncited_elements],
        "citedOnlyByRejected": sorted(u for u in [*uncited_units, *uncited_elements] if u in in_rejected),
        "coveredByExceptionText": text_matched_sentences(rules, source, cited),
    }
