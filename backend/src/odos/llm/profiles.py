"""Extraction instructions in three independent layers, combined by `instructions_for(legal_json)`:

1. GENERAL_INSTRUCTIONS: valid for every normative document (operators, exceptions, units, formulas, fact identifiers,
   provenance). Nothing in it names a particular law.
2. A language glossary (`LANGUAGE_GLOSSARIES`, chosen by the document's `language`): how modality and bounds are worded
   in that language. German and English; other languages fall back to the general instructions only.
3. A document-type profile (`PROFILES`, chosen by Legal JSON `documentType`, then `legalSystem`): structure, citation
   style and who is addressed in that kind of document.

Adding a document type (e.g. DIN/EN/ISO technical standards, Legal JSON `documentType: technical_standard`) means adding
one `ExtractionProfile` to `PROFILES`; until then such documents get the general instructions and the generic profile.
"""

from __future__ import annotations

from dataclasses import dataclass

from odos.llm.terminology import prompt_terms

PROMPT_VERSION = "4"  # recorded in rules.json `_generation`; raise it whenever the instructions change

GENERAL_INSTRUCTIONS = """1. ONE RECORD PER REQUIREMENT, NO DUPLICATES. Split a provision with several independent requirements into several records. Never express the same requirement twice: not in two records, and not once as a record and again as an exception of another record.

2. EXCEPTIONS BELONG TO THE RULE THEY CHANGE. A sentence that relaxes, replaces, restricts or disapplies another requirement of the same provision (an alternative value, a special case, an exemption, "this does not apply if ...") is an entry in `exceptions` of the rule it changes: with its own `condition`, its own `requirements` (the values that apply instead) and the matching `effect`. Do not also emit it as a separate record. A separate record is only right for a requirement that stands on its own.

3. OPERATORS FOLLOW THE WORDING, NEVER AN ASSUMPTION.
   - A determined value ("is", "amounts to") is `==`. A formula that determines a value is `operator: "=="`.
   - A determined value with a floor or ceiling ("0.4 H, at least 3 m") is ONE formula: `== max(0.4 * h, 3 m)` (or `min(...)` for a ceiling). Never split it into several `>=` bounds.
   - Only an explicit minimum is `>=` / `>`, only an explicit maximum is `<=` / `<`; "more than" is `>`, "less than" is `<`, "at least"/"not less than" is `>=`, "at most"/"not more than" is `<=`.
   - An alternative that relaxes a rule ("... suffices", "... is sufficient") states the value that applies instead and keeps the operator of the rule it changes (rule 2): a determined value `==` stays `==`.
   - Every threshold, measure, fraction and number of the text goes into the machine-readable logic, never only into a `description` or `summary`. A condition with a threshold ("roofs with a pitch of less than 70°") is a comparison predicate (`roof_pitch < 70 deg`) in `applicability.conditions` or in an exception's `condition`. Cases split by a threshold ("below 70°: one third is added; otherwise: all of it") are a rule and an exception, or two records, each with its threshold predicate; never one `any` of the alternatives without their conditions.

4. FORMULAS AND UNITS.
   - Write a calculation as the structured expression the text means, e.g. "one third of the roof height is added to the wall height" is `wall_height + roof_height / 3`.
   - Units are bare UCUM-style codes without spaces: `m`, `cm`, `mm`, `m2`, `m3`, `kg`, `t`, `N`, `kN`, `kN/m2`, `Pa`, `kPa`, `W`, `kW`, `V`, `A`, `dB`, `lx`, `K`, `Cel`, `s`, `min`, `h`, `d`, `month`, `year`, `%`. Angles are `deg`.
   - `1` is only for counts and dimensionless ratios. A factor such as `0.4` has no unit.
   - All operands of `add`, `subtract`, `min` and `max` have the same unit, and so does the formula's result `unit`.
   - A quantity the document defines (a symbol such as "H", a measured value) is a fact with a descriptive name, used with that same name in every record.

5. FACT IDENTIFIERS. Every `fact` and every arithmetic `name` is an English, ASCII, lower-case snake_case identifier, optionally with a dotted entity prefix: `setback_depth`, `building.height`, `machine.control_system.withstands_external_influences`. No umlauts or other non-ASCII letters, no camelCase, no spaces, no symbols as names (use `measure_h`, not `H`). TRANSLATE the meaning into English: a word of the document's language written in ASCII letters is not English. Use the same identifier for the same concept in every record of the answer. Explain the fact in the document's language in `description` where helpful.

6. VALUE TYPES. A fact has one value type and one unit in every record. Numbers are numbers: classes, levels or categories numbered 1, 2, 3 are `integer` values (`valueType: "integer"` / `"integer_array"`), never strings such as "1". Yes/no properties are `boolean`.

7. TIME. A period or deadline (a retention period, "within one month", "for at least ten years after ...", "by 1 January 2030") is a `temporal` requirement: `relation`, `duration` {value, unit} and `startEvent` (what the period is counted from), or `endEvent` / `deadline` (ISO date). Never a numeric fact with a time unit, which loses the start event. Use a numeric requirement only for a duration that is a measured property (e.g. a fire resistance of 30 min).

8. PROVENANCE. `source.elements` lists the most specific element(s) that carry the wording, with IDs copied exactly from the input; add other elements (definitions, the provision that makes an annex binding) with their `role`. An exception, alternative, exemption or override has no source of its own: the sentences it comes from are cited ONLY in the `source.elements` of the record it belongs to. So list EVERY sentence that contributes to the record, the one of the main requirement and the sentence of each exception or alternative, one entry per sentence with its `sentenceId` and `role: "primary"`, even if they belong to the same element. A sentence that is not cited there is reported as not covered, although its content is in the record. Never invent or alter an ID, a page number or a sentence ID; use `sentenceId` only if that sentence is listed in `sentences` for that element. Set `source.documentId` to the document's `id`. Give `citation` in the citation style of the document. Do not skip a sentence or a numbered item: every operative sentence belongs to at least one record.

9. ACTORS. Name each actor with the same words in every record (same singular or plural, same qualifiers). A permission names the permitted party as `beneficiary`, never as `duty_holder`.

10. SCHEMA FORM. Use only the properties the schema defines at each place: predicates (`comparison`, `all`, `any`, `not`) have no `description`; explain them in the requirement's or exception's `description` instead.
   - `requirements` and `requirementExpression` are mutually exclusive: a record has exactly one of them (a `definition` record has neither), never both, and never the same requirement in both. Use `requirements`, a list in which every item must hold, for ordinary requirements. Use `requirementExpression` only when the requirements must be combined with `any` or `not` logic that a list cannot express, for example "either X or Y" where the text itself offers both and either suffices.
   - Cases that depend on a condition are never an `any` of their requirements. Write the main case as `requirements` (its condition, if any, in `applicability.conditions`) and each further case as an entry of `exceptions` with its own `condition` and `requirements` (rules 2 and 3). A threshold decides between the cases through the conditions, not through `any`.

11. REFERENCES. Put each cross-reference to ANOTHER provision or document in `references` with its exact citation. Give `elementId` only if you can copy it from the input, otherwise `resolution: "unresolved"`. Do not reference the record's own source element.

12. NON-BINDING TEXT. Preambles, recitals, tables of contents, headings, footnotes and editorial notes are context, never rules of their own.

13. UNCERTAINTY. If a requirement cannot be expressed faithfully with the schema, use an `unresolved` requirement or predicate, set `review.machineCheckable` to false and explain in `review.ambiguities`. `review.status` is always "draft".

14. LANGUAGE. Human-readable content (`summary`, `entity`, `description`, `citation`, `text`) is in the language of the document; keys, enum values and fact identifiers are as in the schema and rule 5."""

LANGUAGE_GLOSSARIES = {
    "de": """GERMAN WORDING.
- Obligation: "muss", "müssen", "hat ... zu", "ist ... zu", "sind ... zu", "ist verpflichtet". Prohibition: "darf nicht", "dürfen nicht", "ist unzulässig", "ist verboten". Permission: "darf", "dürfen", "ist zulässig", "kann" (for an authority: discretion, the authority is the actor; usually not machine-checkable).
- Determined value: "beträgt", "ist" (==). Minimum: "mindestens", "nicht weniger als", "wenigstens" (>=). Maximum: "höchstens", "nicht mehr als", "bis zu" (<=). "mehr als" is >, "weniger als" / "unter" is <.
- "X, mindestens Y" after a determined value is == max(X, Y); "X, höchstens Y" is == min(X, Y).
- Relaxation: "genügt", "reicht aus" (an alternative value, rule 2 and 3). "gilt entsprechend" is a reference with `relationship: "depends_on"`; "unbeschadet" is `subject_to`.
- Exceptions: "es sei denn", "ausgenommen", "dies gilt nicht", "abweichend von", "Satz 1 gilt nicht für".
- Time (rule 7): "innerhalb von", "binnen" (within, startEvent); "mindestens ... lang", "für einen Zeitraum von mindestens" (for_at_least, startEvent); "nach Ablauf von" (after); "spätestens", "bis zum <Datum>" (no_later_than, deadline); "vor" (before).
- Fact identifiers are translated, not transliterated: `building_class`, not `gebaeudeklasse`; `setback_area_depth`, not `abstandsflaeche_tiefe`. Preferred English terms: """ + prompt_terms("de") + ".",
    "en": """ENGLISH WORDING.
- Obligation: "shall", "must", "is required to". Prohibition: "shall not", "must not", "is prohibited". Permission: "may", "is permitted"; "may" for an authority is discretion.
- Determined value: "is", "shall be" (==). Minimum: "at least", "not less than", "minimum" (>=). Maximum: "at most", "not more than", "not exceeding", "up to" (<=). "more than"/"exceeding" is >, "less than"/"below" is <.
- Relaxation: "is sufficient", "suffices". Exceptions: "unless", "except", "by way of derogation from", "shall not apply to". "without prejudice to" is `subject_to`; "mutatis mutandis" is `depends_on`.
- Time (rule 7): "within" (within, startEvent); "for a period of at least", "for at least ... after" (for_at_least, startEvent); "after the expiry of" (after); "no later than", "by <date>" (no_later_than, deadline); "before" (before); "until" (until).""",
}


@dataclass(frozen=True)
class ExtractionProfile:
    name: str
    document_types: tuple[str, ...]  # Legal JSON 2.0 `documentType` values this profile is for
    legal_systems: tuple[str, ...]  # fallback: Legal JSON `legalSystem` values
    instructions: str


GERMAN_LEGISLATION = ExtractionProfile(
    name="german_legislation",
    document_types=("de_legislation",),
    legal_systems=("de",),
    instructions="""DOCUMENT TYPE: German legislation (federal or state statute, ordinance, model code).
- Structure: Teil/Abschnitt (grouping), § (Paragraph: the provision), Absatz, Satz, Nummer, Buchstabe. The sentences of an Absatz are in `sentences` (Satz 1, 2, ...).
- Citation style: "§ 6 Abs. 5 Satz 1", "§ 6 Abs. 6 Nr. 2 Buchstabe a", "§ 6 Abs. 5 Sätze 1 bis 3". A reference to another law keeps its name or abbreviation ("§ 34 Abs. 1 Satz 1 BauGB").
- "Satz 1", "die Sätze 1 bis 3", "Absatz 2", "Nummer 3" without a § refer to the same § (or the same Absatz): they are exceptions or references inside the provision, resolvable from the input.
- Definitions ("im Sinne dieses Gesetzes ist", "... ist ...", "Gebäudeklasse 1 sind ...") are `definition` records. A quantity defined in one Absatz and used in another (e.g. a symbol introduced with "Das sich ergebende Maß ist H") is one fact used in every record.
- Duty holders are usually not named: leave `actors` empty unless the text names one (Bauherr, Behörde, Gemeinde, Verantwortlicher, ...).""",
)

EU_LEGISLATION = ExtractionProfile(
    name="eu_legislation",
    document_types=("eu_regulation", "eu_decision", "eu_legislation"),
    legal_systems=("eu",),
    instructions="""DOCUMENT TYPE: EU legal act (regulation or decision; directly applicable).
- Structure: recitals (Erwägungsgründe: interpretive context, never rules), Kapitel/Abschnitt, Artikel, Absatz (numbered paragraph), Unterabsatz (unnumbered subparagraph), Buchstabe, Nummer/Ziffer, Anhang (annex) with its own parts and sections.
- Citation style follows the language of the document: German "Artikel 10 Absatz 3 Unterabsatz 2", "Artikel 3 Nummer 18", "Anhang III Abschnitt 1.2.1 Buchstabe a"; English "Article 10(3), second subparagraph", "Annex III, section 1.2.1(a)".
- Definitions articles ("Für die Zwecke dieser Verordnung bezeichnet der Ausdruck ...", "For the purposes of this Regulation, ... means ...") give one `definition` record per defined term.
- Name the addressed actors in `applicability.actors`: economic operators (manufacturer, importer, distributor, authorised representative), notified bodies, market surveillance authorities, Member States, the Commission. A duty holder is `duty_holder`.
- An annex requirement is binding through the article that refers to it: cite the annex element as `primary` and the article as `context` when both are in the input.
- Delegated and implementing acts, harmonised standards and other legal acts are `references`; leave them `unresolved` unless their element is in the input.""",
)

EU_DIRECTIVE = ExtractionProfile(
    name="eu_directive",
    document_types=("eu_directive",),
    legal_systems=(),
    instructions=EU_LEGISLATION.instructions.replace(
        "DOCUMENT TYPE: EU legal act (regulation or decision; directly applicable).",
        "DOCUMENT TYPE: EU directive (binding on Member States as to the result; transposed into national law).",
    ) + """
- A directive's obligations are addressed to the Member States ("Die Mitgliedstaaten stellen sicher, dass ...", "Member States shall ensure that ..."): the Member State is the `duty_holder`; the persons the national rules must bind are `targets` or further actors. Such rules are usually not machine-checkable against a product or building model.
- A transposition or application deadline is a `temporal` requirement (`no_later_than` with a `deadline` date).""",
)

GENERIC = ExtractionProfile(
    name="generic",
    document_types=(),
    legal_systems=(),
    instructions="DOCUMENT TYPE: normative document without a specific profile. Follow its own structure and citation style.",
)

PROFILES: tuple[ExtractionProfile, ...] = (GERMAN_LEGISLATION, EU_LEGISLATION, EU_DIRECTIVE)


def profile_for(legal_json: dict) -> ExtractionProfile:
    """The profile for the document's `documentType`, else its `legalSystem`, else the generic one."""
    document_type = legal_json.get("documentType")
    for profile in PROFILES:
        if document_type in profile.document_types:
            return profile
    legal_system = legal_json.get("legalSystem")
    for profile in PROFILES:
        if legal_system in profile.legal_systems:
            return profile
    return GENERIC


def instructions_for(legal_json: dict) -> tuple[str, ExtractionProfile]:
    """The combined instructions (general, language, document type) and the profile used."""
    profile = profile_for(legal_json)
    language = (legal_json.get("language") or "").split("-")[0].lower()
    parts = [GENERAL_INSTRUCTIONS]
    if language in LANGUAGE_GLOSSARIES:
        parts.append(LANGUAGE_GLOSSARIES[language])
    parts.append(profile.instructions)
    return "\n\n".join(parts), profile
