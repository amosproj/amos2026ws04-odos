"""Rule-based document classifier.

Evidence-driven: every rule that fires adds a weighted `Evidence` item (with page, snippet and source
reference) to the candidate types it supports. The file name is never used. Headline evidence (document
title block = first lines of the first page) outweighs mentions in the running text, so a standard that
cites an EU regulation is still a standard.
"""

from __future__ import annotations

import re

from odos.classification.model import (
    Band, ClassificationResult, DocumentType as D, Evidence, InputInfo, SupportStatus,
)
from odos.classification.router import MODE_FOR_TYPE
from odos.classification.text_source import Line, Lines

TITLE_LINES = 30  # lines of the first page that count as the title block
MIN_POINTS = 6  # below this nothing is recognised
HIGH, MEDIUM = (14, 8), (8, 4)  # (min points, min margin)
EU = [D.EU_REGULATION, D.EU_DIRECTIVE]
DE = [D.GERMAN_LAW, D.GERMAN_MODEL_REGULATION]

# ---- patterns ------------------------------------------------------------------------------------------------
# Titles of OJ acts are upper case; running text ("der Richtlinie 2006/42/EG") is not, so these are case-sensitive.
EU_REG_TITLE = re.compile(r"^(?:DURCHFÜHRUNGS|DELEGIERTE )?VERORDNUNG\s*\((?:EU|EG|EWG|EU, Euratom)\)\s*(?:Nr\.?\s*)?\d+/\d+"
                          r"|^(?:COMMISSION )?(?:IMPLEMENTING |DELEGATED )?REGULATION\s*\((?:EU|EC|EEC)\)\s*(?:No\.?\s*)?\d+/\d+")  # fmt: skip
EU_DIR_TITLE = re.compile(r"^(?:DURCHFÜHRUNGS)?RICHTLINIE\s*(?:\((?:EU|EG|EWG)\)\s*)?(?:Nr\.?\s*)?\d+/\d+(?:/(?:EU|EG|EWG))?"
                          r"|^(?:COMMISSION )?(?:IMPLEMENTING )?DIRECTIVE\s*(?:\((?:EU|EC|EEC)\)\s*)?(?:No\.?\s*)?\d+/\d+")  # fmt: skip
ENACT_REG = re.compile(r"^(?:HABEN|HAT) FOLGENDE (?:\w+ )?VERORDNUNG ERLASSEN|^HAVE ADOPTED THIS REGULATION|^HAS ADOPTED THIS REGULATION")  # fmt: skip
ENACT_DIR = re.compile(r"^(?:HABEN|HAT) FOLGENDE (?:\w+ )?RICHTLINIE ERLASSEN|^HAVE ADOPTED THIS DIRECTIVE|^HAS ADOPTED THIS DIRECTIVE")  # fmt: skip
FINAL_REG = re.compile(r"^Diese Verordnung ist in allen ihren Teilen verbindlich|^This Regulation shall be binding in its entirety")  # fmt: skip
FINAL_DIR = re.compile(r"^Diese Richtlinie ist an die Mitgliedstaaten gerichtet|^This Directive is addressed to the Member States")  # fmt: skip
OJ = re.compile(r"Amtsblatt der Europäischen Union|Official Journal of the European Union")
OJ_PAGE = re.compile(r"\b[LC] \d{1,3}/\d{1,3}\b")
RECITAL_INTRO = re.compile(r"^in Erwägung (?:nachstehender|folgender) Gründe|^Whereas:?$|^WHEREAS:?$")
ARTICLE = re.compile(r"^(?:Artikel|Article)\s+\d+[a-z]?$")
CHAPTER = re.compile(r"^(?:KAPITEL|CHAPTER)\s+[IVXL]+$")
PARA_HEADING = re.compile(r"^§\s*\d+[a-z]?(?:\s+\S.*)?$")
RECITAL_LINE = re.compile(r"^\((\d+)\)\s")
LAW_TITLE = re.compile(r"\b\w*[gG]esetz(?:buch)?\b")
MODEL_TITLE = re.compile(r"^MUSTER[\w-]*(?:ORDNUNG|GESETZ|VERORDNUNG|SATZUNG|RICHTLINIE)\b", re.I)
MODEL_BODY = re.compile(r"Bauministerkonferenz|Ministerkonferenz|ARGEBAU|Arbeitsgemeinschaft der für das Bau")
FASSUNG = re.compile(r"^FASSUNG\s+\w+\s+\d{4}", re.I)
STD_ID = re.compile(r"\b(?:DIN\s+EN\s+ISO|DIN\s+EN\s+IEC|DIN\s+ISO|DIN\s+EN|DIN\s+IEC|ISO/IEC|ISO/TS|CEN/TS|ISO|IEC|DIN|EN|ÖNORM|BS)"
                    r"\s+[A-Z]{0,3}\s?\d{2,6}(?:-\d+)*(?::\d{4})?\b")  # fmt: skip
CLAUSE_SCOPE = re.compile(r"^1\s+(?:Scope|Anwendungsbereich)\b", re.I)
CLAUSE_NORMREF = re.compile(r"^2\s+(?:Normative references|Normative Verweisungen|Normative Verweise)\b", re.I)
CLAUSE_TERMS = re.compile(r"^3\s+(?:Terms and definitions|Begriffe|Begriffe und Definitionen)\b", re.I)
FOREWORD = re.compile(r"^(?:Foreword|Vorwort)$", re.I)
COPYRIGHT = re.compile(r"©\s*(?:ISO|IEC|DIN|CEN|CENELEC)")
ICS = re.compile(r"^ICS\s+\d{2}\.\d{3}")
CLAUSE_NUM = re.compile(r"^\d+(?:\.\d+){1,3}\s+[A-ZÄÖÜ]")


class _Collector:
    def __init__(self) -> None:
        self.evidence: list[Evidence] = []

    def add(self, rule: str, desc: str, supports: list[D], weight: int, line: Line | None = None, count: int | None = None) -> None:  # fmt: skip
        self.evidence.append(Evidence(
            rule_id=rule, description=desc, supports=supports, weight=weight,
            page=line.page if line else None, snippet=line.text[:160] if line else None,
            source_ref=line.ref if line else None, count=count,
        ))  # fmt: skip

    def points(self) -> dict[D, int]:
        p = {t: 0 for t in D if t != D.UNKNOWN}
        for e in self.evidence:
            for t in e.supports:
                p[t] += e.weight
        return p


def _first(lines: list[Line], rx: re.Pattern, search: bool = False) -> Line | None:
    for ln in lines:
        if (rx.search(ln.text) if search else rx.match(ln.text)):
            return ln
    return None


def _matching(lines: list[Line], rx: re.Pattern, search: bool = False) -> list[Line]:
    return [ln for ln in lines if (rx.search(ln.text) if search else rx.match(ln.text))]


def collect_evidence(data: Lines) -> tuple[_Collector, list[str]]:
    c = _Collector()
    warnings: list[str] = []
    lines = data.lines
    first_page = min((ln.page for ln in lines), default=1)
    title = [ln for ln in lines if ln.page == first_page][:TITLE_LINES]

    # ---- EU -------------------------------------------------------------------------------------------------
    if ln := _first(title, EU_REG_TITLE):
        c.add("eu_regulation_title", "Title block names a regulation of the form 'VERORDNUNG (EU) n/n'", [D.EU_REGULATION], 5, ln)
    if ln := _first(title, EU_DIR_TITLE):
        c.add("eu_directive_title", "Title block names a directive of the form 'RICHTLINIE (EU) n/n' / 'RICHTLINIE n/n/EU'", [D.EU_DIRECTIVE], 5, ln)  # fmt: skip
    if ln := _first(lines, ENACT_REG):
        c.add("eu_enacting_formula_regulation", "Enacting formula 'HABEN FOLGENDE VERORDNUNG ERLASSEN'", [D.EU_REGULATION], 4, ln)
    if ln := _first(lines, ENACT_DIR):
        c.add("eu_enacting_formula_directive", "Enacting formula 'HABEN FOLGENDE RICHTLINIE ERLASSEN'", [D.EU_DIRECTIVE], 4, ln)
    if ln := _first(lines, FINAL_REG):
        c.add("eu_final_formula_regulation", "Final formula: binding in its entirety and directly applicable", [D.EU_REGULATION], 3, ln)
    if ln := _first(lines, FINAL_DIR):
        c.add("eu_final_formula_directive", "Final formula: addressed to the Member States", [D.EU_DIRECTIVE], 3, ln)
    if ln := _first(lines, OJ, search=True):
        c.add("eu_official_journal", "Official Journal of the European Union indicator", EU, 3, ln)
        pages = {x.page for x in _matching(lines, OJ_PAGE, search=True)}
        if len(pages) >= 3:
            c.add("eu_oj_page_numbers", "Official Journal page references (e.g. 'L 165/12') on several pages", EU, 1, count=len(pages))
    if ln := _first(lines, RECITAL_INTRO):
        c.add("eu_recitals_intro", "Recitals introduced by 'in Erwägung nachstehender Gründe'", EU, 3, ln)
    arts = _matching(lines, ARTICLE)
    if len(arts) >= 5:
        w = 2 + (1 if len(arts) >= 20 else 0)  # Artikelgesetze also have 'Artikel n': supports both EU types only weakly
        c.add("eu_article_headings", f"{len(arts)} stand-alone 'Artikel n' headings", EU, w, arts[0], len(arts))
    chs = _matching(lines, CHAPTER)
    if len(chs) >= 2:
        c.add("eu_chapter_headings", f"{len(chs)} 'KAPITEL <roman>' headings", EU, 1, chs[0], len(chs))
    # recitals: "(1) (2) ..." numbered consecutively from 1 before the first article / chapter
    cut = next((i for i, ln in enumerate(lines) if ARTICLE.match(ln.text) or CHAPTER.match(ln.text)), len(lines))
    nums = [int(m.group(1)) for ln in lines[:cut] if (m := RECITAL_LINE.match(ln.text))]
    run = 0
    while run < len(nums) and nums[run] == run + 1:
        run += 1
    if run >= 5 and cut < len(lines):
        c.add("eu_recital_sequence", f"Numbered paragraphs (1)..({run}) before the first article/chapter (recital-like)", EU, 3, lines[0], run)  # fmt: skip

    # ---- German law and model regulation ----------------------------------------------------------------------
    secs = [ln for ln in lines if PARA_HEADING.match(ln.text) and len(ln.text) <= 120 and not ln.text.endswith(".")]
    if len(secs) >= 5:
        w = 4 + (2 if len(secs) >= 20 else 0)
        c.add("de_paragraph_headings", f"{len(secs)} '§ n' headings", DE, w, secs[0], len(secs))
    for rule, rx, w, text in (
        ("de_bgbl", re.compile(r"Bundesgesetzblatt|\bBGBl\b"), 2, "Reference to the Bundesgesetzblatt (BGBl)"),
        ("de_vollzitat", re.compile(r"^Vollzitat:?"), 3, "'Vollzitat' (official full citation)"),
        ("de_ausfertigungsdatum", re.compile(r"^Ausfertigungsdatum:?"), 3, "'Ausfertigungsdatum' (date of enactment)"),
        ("de_gesetze_im_internet", re.compile(r"gesetze-im-internet\.de"), 2, "Federal law database 'gesetze-im-internet.de'"),
    ):
        if ln := _first(lines, rx, search=True):
            c.add(rule, text, [D.GERMAN_LAW], w, ln)
    if ln := _first(title, LAW_TITLE, search=True):
        c.add("de_law_title", "Title block contains a '...gesetz' name", [D.GERMAN_LAW], 2, ln)
    if ln := _first(lines, re.compile(r"^Inhaltsübersicht$")):
        c.add("de_table_of_contents", "'Inhaltsübersicht' (German statute contents list)", [D.GERMAN_LAW], 1, ln)
    if ln := _first(title, MODEL_TITLE):
        c.add("de_model_title", "Title block names a 'Muster...' regulation/law", [D.GERMAN_MODEL_REGULATION], 5, ln)
    if ln := _first(title, MODEL_BODY, search=True):
        c.add("de_model_issuer", "Title block names a ministers' conference (issuer of model texts)", [D.GERMAN_MODEL_REGULATION], 3, ln)
    if ln := _first(title, FASSUNG):
        c.add("de_model_fassung", "Version statement 'FASSUNG <month> <year>' instead of an Ausfertigungsdatum", [D.GERMAN_MODEL_REGULATION], 2, ln)  # fmt: skip

    # ---- technical standards -------------------------------------------------------------------------------------
    if ln := _first(title, STD_ID, search=True):
        c.add("std_identifier_title", "Standard identifier (ISO/IEC/DIN/EN ...) in the title block", [D.TECHNICAL_STANDARD], 5, ln)
    else:
        ids = _matching(lines, STD_ID, search=True)
        if len(ids) >= 3:
            c.add("std_identifier_body", f"{len(ids)} mentions of standard identifiers in the text (weak: citing is not being)", [D.TECHNICAL_STANDARD], 1, ids[0], len(ids))  # fmt: skip
    for rule, rx, w, text in (
        ("std_scope_clause", CLAUSE_SCOPE, 3, "Numbered clause '1 Scope'"),
        ("std_normative_references", CLAUSE_NORMREF, 3, "Numbered clause '2 Normative references'"),
        ("std_terms_clause", CLAUSE_TERMS, 2, "Numbered clause '3 Terms and definitions'"),
        ("std_foreword", FOREWORD, 2, "'Foreword' / 'Vorwort' heading"),
        ("std_ics", ICS, 3, "ICS classification code"),
    ):
        if ln := _first(lines, rx):
            c.add(rule, text, [D.TECHNICAL_STANDARD], w, ln)
    if ln := _first(lines, COPYRIGHT, search=True):
        c.add("std_copyright", "Copyright line of a standards body (ISO/IEC/DIN/CEN)", [D.TECHNICAL_STANDARD], 3, ln)
    cl = _matching(lines, CLAUSE_NUM)
    if len(cl) >= 15:
        c.add("std_clause_numbering", f"{len(cl)} dotted clause numbers (1.1, 3.2.1 ...)", [D.TECHNICAL_STANDARD], 1, cl[0], len(cl))

    # ---- warnings independent of the winner -----------------------------------------------------------------------
    chars = sum(len(ln.text) for ln in lines)
    if data.pages_scanned and chars / data.pages_scanned < 200:
        warnings.append("Very little text per page: the PDF may be scanned (no text layer). Classification is unreliable; OCR is not enabled.")  # fmt: skip
    if data.pages_total > data.pages_scanned:
        warnings.append(f"Only the first {data.pages_scanned} of {data.pages_total} pages were scanned.")
    return c, warnings


def classify_lines(data: Lines, pdf_sha256: str | None = None) -> ClassificationResult:
    c, warnings = collect_evidence(data)
    pts = c.points()
    ranked = sorted(pts.items(), key=lambda kv: (-kv[1], kv[0].value))
    (top_t, top_p), (_, second_p) = ranked[0], ranked[1]
    # German law vs model regulation share the § evidence: the model type needs its own markers
    model_markers = sum(e.weight for e in c.evidence if e.supports == [D.GERMAN_MODEL_REGULATION])
    if top_t == D.GERMAN_MODEL_REGULATION and model_markers < 5:
        top_t = D.GERMAN_LAW
        top_p, second_p = pts[D.GERMAN_LAW], pts[D.GERMAN_MODEL_REGULATION]
    margin = top_p - second_p

    if top_p < MIN_POINTS:
        dtype, band = D.UNKNOWN, Band.LOW
    elif top_p >= HIGH[0] and margin >= HIGH[1]:
        dtype, band = top_t, Band.HIGH
    elif top_p >= MEDIUM[0] and margin >= MEDIUM[1]:
        dtype, band = top_t, Band.MEDIUM
    else:
        dtype, band = top_t, Band.LOW

    # Structure is required: markers alone (BGBl, Vollzitat, a title) never give more than a low band.
    have = {e.rule_id for e in c.evidence}
    if dtype in DE and "de_paragraph_headings" not in have and band != Band.LOW:
        band = Band.LOW
    if dtype in EU and not ({"eu_article_headings", "eu_enacting_formula_regulation", "eu_enacting_formula_directive"} & have) and band != Band.LOW:  # fmt: skip
        band = Band.LOW

    # ---- consistency warnings --------------------------------------------------------------------------------------------
    rules = {e.rule_id for e in c.evidence}
    if dtype == D.UNKNOWN and top_p > 0:
        warnings.append(f"Some evidence for '{top_t.value}' ({top_p} points) but below the minimum of {MIN_POINTS}; treated as unknown.")  # fmt: skip
    if band == Band.LOW and dtype != D.UNKNOWN:
        warnings.append(f"Classification is uncertain: best candidate '{dtype.value}' has {top_p} points, only {margin} ahead of the runner-up.")  # fmt: skip
    if "eu_official_journal" in rules and not ({"eu_article_headings", "eu_enacting_formula_regulation", "eu_enacting_formula_directive"} & rules):  # fmt: skip
        warnings.append("Official Journal indicators found but no article structure or enacting formula: not treated as an EU act (could be a communication, notice or other OJ item).")  # fmt: skip
    if "de_paragraph_headings" not in rules and ("de_law_title" in rules or "de_bgbl" in rules):
        warnings.append("The title or text suggests a German statute, but no '§ n' structure was found.")
    if {"de_paragraph_headings"} & rules and ({"eu_official_journal", "eu_regulation_title", "eu_directive_title"} & rules):
        warnings.append("Both German '§' structure and EU indicators found; the stronger evidence was used.")
    if dtype in (D.EU_REGULATION, D.EU_DIRECTIVE) and abs(pts[D.EU_REGULATION] - pts[D.EU_DIRECTIVE]) < 6 and band != Band.HIGH:
        warnings.append("Regulation and directive evidence are close; check the title and enacting formula manually.")
    if "std_identifier_body" in rules and dtype not in (D.TECHNICAL_STANDARD,):
        warnings.append("The text mentions standard identifiers; citing a standard does not make this document a standard.")
    if dtype == D.GERMAN_MODEL_REGULATION:
        warnings.append("Model regulation: processed with the German-law parser (tested on the Musterbauordnung); it has no enactment date of its own.")  # fmt: skip
    if dtype == D.EU_DIRECTIVE:
        warnings.append("EU directives are recognised but not routed to the EU regulation parser: structure compatibility has not been verified.")  # fmt: skip
    if dtype == D.TECHNICAL_STANDARD:
        warnings.append("Technical standards are recognised but have no structured pipeline yet (Custom JSON is not implemented); extraction only.")  # fmt: skip
    if dtype == D.EU_REGULATION:
        warnings.append("The EU parser has been tested on Regulation (EU) 2023/1230 only.")

    candidate = MODE_FOR_TYPE[dtype]
    if dtype == D.UNKNOWN:
        suggested, status = "extract_only", SupportStatus.UNSUPPORTED
    elif candidate == "extract_only":
        suggested, status = "extract_only", SupportStatus.RECOGNISED_NOT_SUPPORTED
    elif band == Band.LOW:
        suggested, status = "extract_only", SupportStatus.UNCERTAIN
    else:
        suggested, status = candidate, SupportStatus.SUPPORTED
    chars = sum(len(ln.text) for ln in data.lines)
    summary = {
        SupportStatus.SUPPORTED: f"Detected {dtype.value} ({band.value} confidence); suggested processing mode: {suggested}.",
        SupportStatus.UNCERTAIN: f"Possibly {dtype.value}, but the evidence is weak; suggesting extraction only. You can override.",
        SupportStatus.RECOGNISED_NOT_SUPPORTED: f"Detected {dtype.value} ({band.value} confidence); no structured pipeline supports this type yet, so extraction only is suggested.",  # fmt: skip
        SupportStatus.UNSUPPORTED: "The document type could not be determined; extraction only is suggested.",
    }[status]
    ev = sorted(c.evidence, key=lambda e: (-e.weight, e.rule_id))
    return ClassificationResult(
        document_type=dtype, suggested_processing_mode=suggested,
        candidate_mode=candidate if candidate != suggested else None,
        confidence_band=band, support_status=status, supported=status == SupportStatus.SUPPORTED,
        summary=summary, evidence=ev, points={k.value: v for k, v in sorted(pts.items(), key=lambda kv: kv[0].value)},
        warnings=warnings,
        input=InputInfo(source=data.source, pages_total=data.pages_total, pages_scanned=data.pages_scanned, lines=len(data.lines), characters=chars),  # fmt: skip
        pdf_sha256=pdf_sha256,
    )  # fmt: skip
