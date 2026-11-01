"""AKN4EU 5.0.1.0 specification rules for the package of an EU act published in the Official Journal.

ODOS's own implementation of requirements read from the official specification (AKN4EU 5.0.1.0 Part 1
"Guidelines and Modelling" and Part 2 "Document types"); every rule cites its section and page. It is NOT
the official AKN4EU validator: those artefacts were not available, and only the rules in ``RULES`` are
checked (``NOT_CHECKED`` lists what is not). Passing them is therefore not official AKN4EU conformance.

The layers are reported separately: ``xml`` (well-formedness, pinned OASIS AKN 3.1 XSD), ``package``
(entry file, officialGazette, attachments, file names), ``metadata`` (per file) and ``model`` (nothing
dropped, text and order, annexes, the reviewed model). Each rule has one result:

- ``pass`` / ``fail``;
- ``missing_input``: the rule needs a value that the source does not print and nobody supplied (the
  act's ELI, the Official Journal URI, the legislative procedure). The requirement is NOT met; nothing
  is invented to meet it;
- ``warning``: a SHOULD rule is not met; it never makes the package fail (``warnings`` in the summary);
- ``deviation``: deliberately not met, because meeting it would be a false statement (ODOS is not an EU
  body and cannot be named as one);
- ``not_applicable``.
"""

from __future__ import annotations

import re
from collections import Counter

from lxml import etree

from odos.akn.akn4eu import AKN4EU_DOCUMENTATION, AKN4EU_NS, AUTH, ODOS_ORG_HREF, OJ_RESOURCE, RESOURCE_TYPE, XID
from odos.akn.mapping import AKN_NS
from odos.akn.validate import validate_xml
from odos.document_model import DocumentModel, ElementType as T

A = f"{{{AKN_NS}}}"
V = f"{{{AKN4EU_NS}}}"
TARGET_VERSION = "5.0.1.0"  # the specification these rules come from (Part 1 §9.2.2.10, p.111)
SPECIFICATION = {
    "part_1": "AKN4EU 5.0.1.0 – PART 1 Guidelines and Modelling (pages dated 10/06/2026)",
    "part_2": "AKN4EU 5.0.1.0 – PART 2 Document types (Part 2.8 pages dated 11/10/2024)",
}
PASS, FAIL, MISSING, DEVIATION, NA, WARN = "pass", "fail", "missing_input", "deviation", "not_applicable", "warning"
RANK = {NA: 0, PASS: 1, WARN: 2, DEVIATION: 3, MISSING: 4, FAIL: 5}
MAX_FINDINGS = 50  # per rule in the report; the total is always given

RESOURCE_CODES = {"DEC", "DIR", "REG", "DEC_DEL", "DIR_DEL", "REG_DEL", "DEC_IMPL", "DIR_IMPL", "REG_IMPL", "REC"}  # Part 2.1 p.18
COLLECTIONS = {"OJ-L", "OJ-C", "OJ-P", "OJ-X", "OJ-S", "OJ-A"}  # Part 2.8 §1.3.1 p.197, §2.3.1 p.206
FORBIDDEN = set('<>:"/\\|?*')  # Part 1 §1.2.3.1, p.24
ELI_ACT = re.compile(r"^http://data\.europa\.eu/eli/(?P<type>[a-z_]+)/(?P<year>\d{4})/(?P<no>\d+)/oj$")
ELI_ANNEX = re.compile(r"^http://data\.europa\.eu/eli/[a-z_]+/\d{4}/\d+/anx(_\w+)?/oj$")
TLC = {"TLCOrganization", "TLCReference", "TLCLocation", "TLCRole", "TLCConcept", "TLCProcess", "TLCPerson", "TLCEvent", "TLCObject", "TLCTerm"}  # fmt: skip
TLC_EXCEPTIONS = {"identifier", "language", "procedureReference"}  # @showAs has its own rule (Part 1 §9.4, p.113)
ACT_EIDS = {"preface": "prf_1", "longTitle": "tit_1", "preamble": "pbl_1", "body": "enc_1", "conclusions": "fnp_1"}

# rule -> (layer, level, source, requirement)
RULES = {
    "XML_WELL_FORMED": ("xml", "MUST", "Part 1 §1.2, pp.21-22 (AKN4EU files are XML files)", "every file of the package is well-formed XML"),
    "AKN_ROOT": ("xml", "MUST", "Part 1 §1.2.3.1, p.24 (footnote 11)", "root akomaNtoso in the Akoma Ntoso namespace with exactly one document element"),
    "AKN_3_1_XSD": ("xml", "MUST", "Part 1 change log, pp.2-3 (AKN4EU 5.x implements Akoma Ntoso 3.1)", "every file is valid against the OASIS Akoma Ntoso 3.1 schema (unmodified, SHA-256 pinned)"),
    "PKG_MAIN_FILE": ("package", "MUST", "Part 1 §1.2, pp.21-22", "exactly one 'main-' entry file, whose document element is documentCollection or officialGazette"),
    "PKG_MAIN_COVERPAGE": ("package", "MUST", "Part 1 §1.2, p.22 (footnote 7)", "the main document has a coverPage (it may be empty)"),
    "PKG_FLAT": ("package", "MUST", "Part 1 §1.2, p.22", "all files are in the root directory of the package"),
    "PKG_REFERENCES": ("package", "MUST", "Part 1 §1.2, pp.21-22; Part 2.8 §1.3.2, p.197; Part 2.1 §3.9.1, p.44", "every documentRef resolves to a file of the package, and every file except main is referenced"),
    "FILENAME_CHARACTERS": ("package", "MUST", "Part 1 §1.2.3.1, p.24", "no forbidden character (< > : \" / \\ | ? *) in a file name"),
    "FILENAME_PREFIX": ("package", "MUST", "Part 1 §1.2.3.1, p.24; Part 2.8 §1.5.1, p.201", "every file except main starts with the @name of its document element; an OJ act starts with 'act-'"),
    "FILENAME_LANGUAGE": ("package", "MUST", "Part 1 §1.2.3.1, p.26; §9.9.1, p.120", "the last component of every file name is the 2-letter language code of the file (FRBRlanguage/@language), the same for the whole package"),
    "FILENAME_IDENTIFIER": ("package", "MUST", "Part 1 §1.2.3.1, pp.25-26; §9.9.2, p.121; Part 2.8 §1.5.1, p.201", "in an OJ document the second component of the file name is the official URI's identifier, and it is present as FRBRnumber"),
    "OJ_GAZETTE": ("package", "MUST", "Part 2.8 §1.3.1, p.197; §2.3.1, p.206", "the package of an act published in the OJ has an officialGazette main file whose @name is a 'document-collection' code (OJ-L, OJ-C, ...)"),
    "OJ_GAZETTE_STRUCTURE": ("package", "MUST", "Part 2.8 §1.3.2, p.197; §1.4.1, p.200; §2.3.2, p.207", "officialGazette: meta, coverPage and collectionBody with exactly one component/documentRef to the act (@href mandatory, @showAs empty)"),
    "OJ_GAZETTE_META": ("package", "MUST", "Part 1 §9.2.2.3, p.109; Part 2.8 §1.3.3, p.198", "officialGazette metadata: FRBRauthor is EURUN (TLCOrganization of corporate-body/EURUN) and a TLCReference docType for its document-collection entry"),
    "OJ_COVERPAGE_REFERENCE": ("package", "MUST", "Part 2.8 §1.3.4.2, p.200; §2.3.3.2, p.210", "the coverPage holds the publication reference inside block[@name='reference']/docNumber"),
    "OJ_COVERPAGE_INFO": ("package", "SHOULD", "Part 2.8 §2.3.3.2, pp.209-210 (pre-ABA); §1.3.4.1, pp.199-200", "coverPage/container[@name='publicationInfo'] with the blocks issn, ageOJ, publicationDate, publicationLang, publicationTitle and reference"),
    "OJ_CLASSIFICATION": ("package", "SHOULD", "Part 2.8 §2.3.3.3, pp.210-211", "the main file of a pre-ABA publication has coverPage/container[@name='ojClassification']"),
    "ATTACHMENTS": ("package", "MUST", "Part 2.1 §3.3, p.19; §3.9.1, p.44", "for each annex the act has an attachment containing only a documentRef (@href to the ANNEX file, @showAs empty); each ANNEX file is referenced exactly once"),
    "DOC_TYPE_ACT": ("metadata", "MUST", "Part 2.1 §3.1-3.2, pp.17-18; §3.4, p.21", "an act published in the OJ is an <act> whose @name is a 'resource-type' code, with TLCReference docType (xml:id = @name, href resource-type/@name)"),
    "ACT_STRUCTURE": ("metadata", "MUST", "Part 2.1 §3.3, p.19", "act: meta, preface, preamble, body, conclusions (and attachments if there are annexes), in this order"),
    "DOC_ANNEX": ("metadata", "MUST", "Part 2.1 §4, §4.1-4.2, pp.46-47", "annex: doc[@name='ANNEX'] with meta and mainBody/annex, and TLCReference docType ANNEX (href resource-type/ANNEX)"),
    "META_SOURCE": ("metadata", "MUST", "Part 1 §9.1, p.101", "@source of the metadata sections refers to a TLCOrganization whose @href is an entry of the 'corporate-body' table"),
    "FRBR_MANDATORY": ("metadata", "MUST", "Part 1 §9.9.1, p.120", "FRBRthis, FRBRuri, FRBRdate and FRBRauthor in FRBRWork, FRBRExpression and FRBRManifestation"),
    "FRBR_COUNTRY": ("metadata", "MUST", "Part 1 §9.2, p.102; §9.9.1, p.120", "FRBRWork/FRBRcountry is 'EU'"),
    "FRBR_SUBTYPE": ("metadata", "MUST", "Part 1 §9.2, p.102; Part 2.1 §3.4, p.20", "act/bill: FRBRsubtype with @value = @name of the act and @refersTo a TLCProcess of the procedure"),
    "FRBR_NUMBER": ("metadata", "MUST", "Part 1 §9.2, p.103; §9.9.1, p.120", "FRBRWork/FRBRnumber or (exclusive) akn4eu:docCUID"),
    "FRBR_NUMBER_OJ": ("metadata", "MUST", "Part 1 §9.2.2.4, pp.109-110", "OJ document: FRBRnumber is the extract of FRBRWork/FRBRthis ('eli/...' of an ELI, 'oj/...' of a resource URI)"),
    "FRBR_PRESCRIPTIVE": ("metadata", "MUST", "Part 1 §9.2.2.5, p.110; §9.9.1, p.120; Part 2.1 §3.4, p.20; §4.2, p.47", "act and annex: FRBRprescriptive 'true' (Council Recommendation: 'false'); officialGazette: not used"),
    "FRBR_LANGUAGE": ("metadata", "MUST", "Part 1 §9.2.2.7, pp.110-111; §9.9.1, p.120", "FRBRlanguage/@language is a 2-letter code; a TLCReference name='language' (href language/XXX, @showAs the 2-letter code); in OJ documents FRBRlanguage/@refersTo points to it"),
    "AKN4EU_VERSION": ("metadata", "MUST", "Part 1 §9.2.2.10, p.111 (also p.107); §9.9.1, p.120", f"preservation/akn4eu:akn4euVersion/@value is '{TARGET_VERSION}', the version these rules belong to"),
    "AKN4EU_DOCUMENTATION": ("metadata", "MUST", "Part 1 §9.2.2.10, p.111 (also p.107); §9.9.1, p.120", "preservation/akn4eu:akn4euDocumentation/@href is the official AKN4EU documentation page"),
    "OJ_URI": ("metadata", "MUST", "Part 1 §9.2.2.1, p.108; §9.2.2.6, p.110; §9.2.2.9, p.111; Part 2.8 §1.3.3, p.198; §1.5.2, p.201", "OJ document: FRBRthis/FRBRuri are the official URI (act: its ELI .../oj; annex: its own ELI, FRBRuri the act's; officialGazette: the OJ resource URI, not an ELI); Expression adds the 3-letter language, Manifestation '/akn4eu'"),
    "OJ_DATES": ("metadata", "MUST", "Part 1 §9.2.2.2, pp.108-109", "OJ document: FRBRWork/FRBRdate[@name='publication'], equal to publication/@date"),
    "OJ_AUTHOR": ("metadata", "MUST", "Part 1 §9.2.2.3, p.109", "OJ document: FRBRWork/FRBRauthor refers to the adopting institution(s) (officialGazette: EURUN); FRBRauthor in FRBRExpression and FRBRManifestation is empty"),
    "OJ_PUBLICATION": ("metadata", "MUST", "Part 1 §9.3, p.112; Part 2.1 §3.4, p.21; §4.2, p.47", "act and annex published in the OJ: meta/publication with @date, @number, @showAs and @name; forbidden in other files"),
    "TLC_AUTHORITY": ("metadata", "MUST", "Part 1 §9.4, p.113", "references to an authority table: @xml:id is the authority code, @showAs empty (except identifier, language, procedureReference); in OJ documents @eId = @xml:id"),
    "ELI_EIDS": ("metadata", "MUST", "Part 2.8 §1.5.3, pp.201-202", "OJ act: preface prf_1, longTitle tit_1, preamble pbl_1, citation cit_N, recital rct_N, body enc_1, conclusions fnp_1"),
    "ANNEX_EIDS": ("metadata", "MUST", "Part 2.8 §1.6, p.202", "annex: mainBody has no @eId; every eId outside meta starts with the annex identifier (anx)"),
    "MODEL_COMPLETE": ("model", "MUST", "ODOS: nothing silently dropped (Part 2.1 §3.3, p.19: every part of the act is mandatory)", "every element of the DocumentModel except the document root and page furniture is in the XML; nothing unmapped"),
    "MODEL_TEXT_ORDER": ("model", "MUST", "ODOS: text preservation", "every element's text rebuilt from the XML equals the model text, in model order"),
    "MODEL_ANNEXES": ("model", "MUST", "Part 2.1 §3.9.1, p.44; §4, p.46", "every annex of the model is one ANNEX file, referenced from the act in model order, with its printed number"),
    "MODEL_ACT_TYPE": ("model", "MUST", "Part 2.1 §3.2, pp.17-18", "act/@name is the 'resource-type' code of the printed document type (REG for a Regulation)"),
    "MODEL_PUBLICATION": ("model", "MUST", "Part 1 §9.3, p.112", "publication/@date and @number are the printed Official Journal date and reference"),
    "MODEL_REVIEW": ("model", "MUST", "ODOS: review corrections reach every export", "the export is built from the effective reviewed DocumentModel when a review exists, and every corrected element is in the XML"),
}

NOT_CHECKED = [
    "the official AKN4EU validation artefacts (schema/Schematron): not available",
    "membership of the codes in the EU authority tables (only the form of the URIs is checked, the tables are not looked up)",
    "TLCReference name='procedureReference' (SHOULD, Part 2.1 §3.4, p.21) and the procedure itself: not determined from the source",
    "ELI subdivision eIds below the article and annex level (Part 1 Annex 3 ELI template)",
    "the content mark-up rules of Part 1 §§3-8 (lists, tables, citations, references, amendments) beyond the AKN 3.1 schema and the sample rules",
    "resource files (RSC_...) and the PDF rendition",
    "the AKN4EU_LEG package name (Part 1 §1.2.3, p.24): the ZIP keeps the ODOS artifact name akn4eu_package.zip",
]

SPECIFICATION_NOTES = [
    "Part 2.8 p.195 (footnote 26, pages dated 11/10/2024) states that only Commission autonomous acts are covered for OJ acts; "
    "Part 1 p.10 (pages dated 10/06/2026) covers Regulations. A Regulation of the Parliament and the Council (e.g. (EU) 2023/1230) is "
    "checked against the Part 1 rules and the OJ act rules of Part 2.8; whether the Publications Office applies them to such acts is not confirmed.",
    "Part 2.8 §1.5.3 p.202 requires body eId 'enc_1'; the 5.0.0.1 samples use 'ent_1'. The specification is followed.",
    "Part 2.1 §3.9.1 p.44 requires an empty @showAs on annex documentRefs; the 2025/864 sample uses 'ANNEX'. The specification is followed.",
    "The sample package declares akn4euVersion 5.0.0.1; Part 1 pp.107/111 give 5.0.1.0. ODOS declares 5.0.1.0.",
    "The pre-ABA example of Part 2.8 pp.208-209 (FRBRdate DATE_PUB/DATE_SIG, FRBRauthor ~COM, FRBRnumber without 'oj/', FRBRprescriptive in "
    "officialGazette) differs from Part 1 §9.2.2 pp.108-110 (FRBRdate 'publication', EURUN, 'oj/' extract, no FRBRprescriptive). Part 1 is followed.",
    "Part 1 §9.4 p.113 requires an empty @showAs for authority entries; the samples give labels. The specification is followed.",
    "No file name example exists for the main- file of a pre-ABA publication; ODOS uses 'OJ_' + the identifier of FRBRnumber, as in the ABA example (p.37).",
]


class _Results:
    def __init__(self) -> None:
        self.out = {r: {"status": NA, "findings": []} for r in RULES}

    def note(self, rule: str, status: str, file: str | None = None, message: str | None = None) -> None:
        if status == FAIL and RULES[rule][1] == "SHOULD":
            status = WARN  # a SHOULD requirement that is not met is a warning, not a mandatory error
        cur = self.out[rule]
        if RANK[status] > RANK[cur["status"]]:
            cur["status"] = status
        if message is not None and status != PASS:
            cur["findings"].append({"status": status, "file": file, "message": message})


def _local(n) -> str:
    return etree.QName(n).localname


def _doc(root):
    kids = [c for c in root if isinstance(c.tag, str)]
    return kids[0] if root.tag == A + "akomaNtoso" and len(kids) == 1 else None


def _levels(d) -> dict:
    ident = d.find(f"{A}meta/{A}identification")
    return {lvl: (ident.find(A + lvl) if ident is not None else None) for lvl in ("FRBRWork", "FRBRExpression", "FRBRManifestation")}


def _value(level, tag: str, attr: str = "value") -> str | None:
    n = level.find(A + tag) if level is not None else None
    return None if n is None else (n.get(attr) or "")


def _refs(d) -> dict:
    out = {}
    for n in d.iterfind(f"{A}meta/{A}references/*"):
        for k in (n.get(XID), n.get("eId")):
            if k:
                out.setdefault(k, n)
    return out


def _resolve(refs: dict, value: str | None):
    return refs.get(value[1:]) if value and value[:1] in "#~" else None


def validate_akn4eu(files: dict[str, bytes], model: DocumentModel | None = None, result=None, text: dict | None = None,
                    model_source: dict | None = None) -> dict:  # fmt: skip
    """All rules over one package (file name -> XML). With the model, the generator result and the text check
    of the export, the model layer is checked too."""
    r = _Results()
    docs = _xml(files, r)
    oj = _package(files, docs, r)
    for name, d in docs.items():
        _metadata(name, d, docs, oj, r)
    if model is not None and result is not None:
        _model(model, result, text or {}, model_source, docs, r)
    return _summary(r)


# ---- xml ---------------------------------------------------------------------------------------------------------------
def _xml(files: dict[str, bytes], r: _Results) -> dict:
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    docs = {}
    for name, xml in files.items():
        try:
            root = etree.fromstring(xml, parser)
        except etree.XMLSyntaxError as exc:
            r.note("XML_WELL_FORMED", FAIL, name, f"not well-formed: {exc}")
            continue
        r.note("XML_WELL_FORMED", PASS, name)
        d = _doc(root)
        if d is None:
            r.note("AKN_ROOT", FAIL, name, "not an akomaNtoso root with one document element")
            continue
        r.note("AKN_ROOT", PASS, name)
        v = validate_xml(xml)
        r.note("AKN_3_1_XSD", PASS if v.valid else FAIL, name, None if v.valid else "; ".join(e.message for e in v.errors[:3]))
        docs[name] = d
    return docs


# ---- package -----------------------------------------------------------------------------------------------------------
def _package(files: dict[str, bytes], docs: dict, r: _Results) -> bool:
    names = list(files)
    mains = [n for n in names if n.startswith("main-")]
    main = docs.get(mains[0]) if len(mains) == 1 else None
    if len(mains) != 1:
        r.note("PKG_MAIN_FILE", FAIL, None, f"{len(mains)} main- files (exactly one required)")
    elif main is None:
        r.note("PKG_MAIN_FILE", FAIL, mains[0], "the main- file is not a readable Akoma Ntoso document")
    elif _local(main) not in ("documentCollection", "officialGazette"):
        r.note("PKG_MAIN_FILE", FAIL, mains[0], f"document element {_local(main)}, not documentCollection or officialGazette")
    else:
        r.note("PKG_MAIN_FILE", PASS, mains[0])
        r.note("PKG_MAIN_COVERPAGE", PASS if main.find(A + "coverPage") is not None else FAIL, mains[0], "no coverPage")
    oj = (main is not None and _local(main) == "officialGazette") or any(d.find(f"{A}meta/{A}publication") is not None for d in docs.values())  # fmt: skip

    langs = {}
    for name in names:
        r.note("PKG_FLAT", FAIL if "/" in name or "\\" in name else PASS, name, "file is not in the root directory")
        stem = name.rsplit(".", 1)[0]
        bad = sorted({c for c in stem if c in FORBIDDEN})
        r.note("FILENAME_CHARACTERS", FAIL if bad else PASS, name, f"forbidden character(s) {''.join(bad)}")
        d = docs.get(name)
        if d is None:
            continue
        parts = stem.split("-")
        lang = _value(_levels(d)["FRBRExpression"], "FRBRlanguage", "language")
        langs[name] = lang
        ok = len(parts) >= 3 and parts[-1] == lang and re.fullmatch(r"[a-z]{2}", parts[-1] or "")
        r.note("FILENAME_LANGUAGE", PASS if ok else FAIL, name, f"last component {parts[-1]!r}, FRBRlanguage {lang!r}")
        if not name.startswith("main-"):
            want = "act" if _local(d) == "act" and oj else (d.get("name") or _local(d))
            r.note("FILENAME_PREFIX", PASS if parts[0] == want else FAIL, name, f"first component {parts[0]!r}, expected {want!r}")
        if oj and len(parts) >= 3:
            w = _levels(d)["FRBRWork"]
            this = _value(w, "FRBRthis")
            numbers = [n.get("value") or "" for n in (w.findall(A + "FRBRnumber") if w is not None else [])]
            ident = "-".join(parts[1:-1])
            if not this:
                r.note("FILENAME_IDENTIFIER", MISSING, name, f"identifier {ident!r}: the official URI (FRBRthis) is not known, so the file cannot be named after it")  # fmt: skip
            elif ident.lower() not in {n.replace("/", "_").lower() for n in numbers} and ident.lower() not in {"oj_" + n.replace("/", "_").lower() for n in numbers}:  # fmt: skip
                r.note("FILENAME_IDENTIFIER", FAIL, name, f"identifier {ident!r} is not one of the FRBRnumber values {numbers}")
            else:
                r.note("FILENAME_IDENTIFIER", PASS, name)
    if len(set(langs.values())) > 1:
        r.note("FILENAME_LANGUAGE", FAIL, None, f"files of different languages in one package: {sorted(set(langs.values()), key=str)}")

    # references: main -> act -> annexes; nothing dangling, nothing orphaned
    referenced: list[str] = []
    for name, d in docs.items():
        for ref in d.iter(A + "documentRef"):
            href = ref.get("href") or ""
            referenced.append(href)
            r.note("PKG_REFERENCES", PASS if href in files else FAIL, name, f"documentRef {href!r} is not a file of the package")
    for name in names:
        if not name.startswith("main-"):
            r.note("PKG_REFERENCES", PASS if name in referenced else FAIL, name, "not referenced by any documentRef of the package")

    for rule in ("OJ_GAZETTE", "OJ_GAZETTE_STRUCTURE", "OJ_GAZETTE_META", "OJ_COVERPAGE_REFERENCE", "OJ_COVERPAGE_INFO", "OJ_CLASSIFICATION"):
        if not oj:
            r.note(rule, NA)
    if oj:
        _gazette(mains[0] if len(mains) == 1 else None, main, docs, r)
    _attachments(docs, r)
    return oj


def _gazette(name: str | None, g, docs: dict, r: _Results) -> None:
    if g is None or _local(g) != "officialGazette":
        r.note("OJ_GAZETTE", FAIL, name, "the act is published in the Official Journal, but the main file is not an officialGazette")
        return
    r.note("OJ_GAZETTE", PASS if g.get("name") in COLLECTIONS else FAIL, name, f"officialGazette/@name {g.get('name')!r} is not a document-collection code")  # fmt: skip
    kids = [_local(c) for c in g if isinstance(c.tag, str)]
    comps = g.findall(f"{A}collectionBody/{A}component")
    refs = [x for c in comps for x in c.findall(A + "documentRef")]
    problems = [f"missing {k}" for k in ("meta", "coverPage", "collectionBody") if k not in kids]
    if len(comps) != 1 or len(refs) != 1:
        problems.append(f"{len(comps)} component(s) with {len(refs)} documentRef(s) (exactly one required)")
    else:
        href = refs[0].get("href")
        if not href:
            problems.append("documentRef without @href")
        elif href not in docs or _local(docs[href]) != "act":
            problems.append(f"documentRef {href!r} does not point to an act of the package")
        if refs[0].get("showAs") != "":
            problems.append(f"documentRef/@showAs {refs[0].get('showAs')!r} (must be empty)")
    r.note("OJ_GAZETTE_STRUCTURE", FAIL if problems else PASS, name, "; ".join(problems))
    w, refmap = _levels(g)["FRBRWork"], _refs(g)
    authors = [a.get("href") for a in (w.findall(A + "FRBRauthor") if w is not None else [])]
    eurun = [_resolve(refmap, a) for a in authors]
    problems = []
    if len(eurun) != 1 or eurun[0] is None or _local(eurun[0]) != "TLCOrganization" or eurun[0].get("href") != AUTH + "corporate-body/EURUN":
        problems.append(f"FRBRWork/FRBRauthor {authors} is not EURUN")
    doc_types = [n for n in refmap.values() if _local(n) == "TLCReference" and n.get("name") == "docType"]
    if not any(n.get("href") == AUTH + f"document-collection/{g.get('name')}" for n in doc_types):
        problems.append(f"no TLCReference docType for document-collection/{g.get('name')}")
    r.note("OJ_GAZETTE_META", FAIL if problems else PASS, name, "; ".join(problems))
    cover = g.find(A + "coverPage")
    numbers = cover.xpath(".//a:block[@name='reference']/a:docNumber", namespaces={"a": AKN_NS}) if cover is not None else []
    r.note("OJ_COVERPAGE_REFERENCE", PASS if numbers and "".join(numbers[0].itertext()).strip() else FAIL, name, "no block[@name='reference']/docNumber with the reference")  # fmt: skip
    info = cover.find(f"{A}container[@name='publicationInfo']") if cover is not None else None
    pre_aba = bool(numbers) and numbers[0].find(f"{A}inline[@name='collectionNumber']") is not None
    want = ["issn", "ageOJ", "publicationDate", "publicationLang", "publicationTitle", "reference"] if pre_aba else \
           ["flag", "publicationTitle", "publicationLang", "publicationCollection", "publicationDate", "issn"]  # fmt: skip
    have = {b.get("name") for b in info.iter(A + "block")} if info is not None else set()
    missing = [b for b in want if b not in have]
    r.note("OJ_COVERPAGE_INFO", MISSING if missing else PASS, name,
           f"publicationInfo without {missing}: not printed in the source PDF" if info is not None else "no publicationInfo container")  # fmt: skip
    if pre_aba:
        has = cover.find(f"{A}container[@name='ojClassification']") is not None
        r.note("OJ_CLASSIFICATION", PASS if has else FAIL, name, "no container[@name='ojClassification'] (ODOS keeps the printed OJ headings in the act's coverPage)")  # fmt: skip
    else:
        r.note("OJ_CLASSIFICATION", NA)


def _attachments(docs: dict, r: _Results) -> None:
    annexes = [n for n, d in docs.items() if _local(d) == "doc" and d.get("name") == "ANNEX"]
    seen: list[str] = []
    for name, d in docs.items():
        for at in d.iterfind(f"{A}attachments/{A}attachment"):
            kids = [c for c in at if isinstance(c.tag, str)]
            refs = [c for c in kids if _local(c) == "documentRef"]
            if at.get("refersTo"):  # an attached act ("attachment"), not an annex: Part 2.1 §3.9.3
                continue
            if len(refs) != 1 or len(kids) != 1:
                r.note("ATTACHMENTS", FAIL, name, f"attachment {at.get(XID)} must contain only one documentRef ({[_local(c) for c in kids]})")
                continue
            href, show = refs[0].get("href") or "", refs[0].get("showAs")
            seen.append(href)
            if href not in annexes:
                r.note("ATTACHMENTS", FAIL, name, f"documentRef {href!r} is not an ANNEX file of the package")
            elif show != "":
                r.note("ATTACHMENTS", FAIL, name, f"documentRef {href!r}: @showAs {show!r} (must be empty)")
            else:
                r.note("ATTACHMENTS", PASS, name)
    for a in annexes:
        if seen.count(a) != 1:
            r.note("ATTACHMENTS", FAIL, a, f"referenced {seen.count(a)} times by an attachment (exactly once required)")


# ---- metadata, per file ----------------------------------------------------------------------------------------------------
def _metadata(name: str, d, docs: dict, oj: bool, r: _Results) -> None:
    local = _local(d)
    is_act, is_gazette = local == "act", local == "officialGazette"
    is_annex = local == "doc" and d.get("name") == "ANNEX"
    lv, refs = _levels(d), _refs(d)
    w, ex, mf = lv["FRBRWork"], lv["FRBRExpression"], lv["FRBRManifestation"]
    doc_types = [n for n in refs.values() if _local(n) == "TLCReference" and n.get("name") == "docType"]

    if is_act:
        nm = d.get("name")
        ok = nm in RESOURCE_CODES and any(n.get(XID) == nm and n.get("href") == AUTH + f"resource-type/{nm}" for n in doc_types)
        r.note("DOC_TYPE_ACT", PASS if ok else FAIL, name, f"act/@name {nm!r} not a resource-type code with its TLCReference docType")
        kids = [_local(c) for c in d if isinstance(c.tag, str)]
        order = ["meta", "coverPage", "preface", "preamble", "body", "conclusions", "attachments"]
        need = ["meta", "preface", "preamble", "body"] + (["conclusions"] if nm != "REC" else [])
        if d.find(A + "attachments") is None and any(_local(x) == "doc" and x.get("name") == "ANNEX" for x in docs.values()):
            r.note("ACT_STRUCTURE", FAIL, name, "the package has annexes, but the act has no attachments")
        missing = [k for k in need if k not in kids]
        if missing or [k for k in kids if k not in order] or kids != sorted(kids, key=lambda k: order.index(k) if k in order else 99):
            r.note("ACT_STRUCTURE", FAIL, name, f"children {kids} (missing {missing})")
        elif "coverPage" in kids:
            r.note("ACT_STRUCTURE", DEVIATION, name, "coverPage before the preface holds the OJ headings printed above the title (ODOS addition, not in Part 2.1 §3.3)")  # fmt: skip
        else:
            r.note("ACT_STRUCTURE", PASS, name)
    if is_annex:
        ok = d.find(A + "meta") is not None and d.find(f"{A}mainBody/{A}annex") is not None
        ok = ok and any(n.get(XID) == "ANNEX" and n.get("href") == AUTH + "resource-type/ANNEX" for n in doc_types)
        r.note("DOC_ANNEX", PASS if ok else FAIL, name, "not doc[@name='ANNEX'] with meta, mainBody/annex and TLCReference docType ANNEX")

    meta = d.find(A + "meta")
    for sec in (meta if meta is not None else []):
        if not isinstance(sec.tag, str) or sec.get("source") is None:
            continue
        org = _resolve(refs, sec.get("source"))
        if org is not None and _local(org) == "TLCOrganization" and (org.get("href") or "").startswith(AUTH + "corporate-body/"):
            r.note("META_SOURCE", PASS, name)
        elif org is not None and org.get("href") == ODOS_ORG_HREF:
            r.note("META_SOURCE", DEVIATION, name, f"{_local(sec)}/@source is the ODOS converter, which is not an EU body; naming the Publications Office or an institution would be false")  # fmt: skip
        else:
            r.note("META_SOURCE", FAIL, name, f"{_local(sec)}/@source {sec.get('source')!r} is not a TLCOrganization of the corporate-body table")  # fmt: skip

    if any(v is None for v in lv.values()):
        r.note("FRBR_MANDATORY", FAIL, name, "missing FRBR level(s)")
        return
    missing = [f"{lvl}/{t}" for lvl, n in lv.items() for t in ("FRBRthis", "FRBRuri", "FRBRdate", "FRBRauthor") if n.find(A + t) is None]
    r.note("FRBR_MANDATORY", FAIL if missing else PASS, name, f"missing {missing}")
    r.note("FRBR_COUNTRY", PASS if [c.get("value") for c in w.findall(A + "FRBRcountry")] == ["EU"] else FAIL, name, "FRBRcountry is not 'EU'")

    if local in ("act", "bill"):
        st = w.find(A + "FRBRsubtype")
        if st is None or st.get("value") != d.get("name"):
            r.note("FRBR_SUBTYPE", FAIL, name, f"FRBRsubtype {None if st is None else st.get('value')!r}, act/@name {d.get('name')!r}")
        elif not st.get("refersTo"):
            r.note("FRBR_SUBTYPE", MISSING, name, "FRBRsubtype/@refersTo: the procedure (TLCProcess) is not determined from the source")
        else:
            p = _resolve(refs, st.get("refersTo"))
            r.note("FRBR_SUBTYPE", PASS if p is not None and _local(p) == "TLCProcess" else FAIL, name, f"FRBRsubtype/@refersTo {st.get('refersTo')!r} is not a TLCProcess")  # fmt: skip

    numbers = [n.get("value") or "" for n in w.findall(A + "FRBRnumber")]
    cuids = list(d.find(f"{A}meta/{A}identification").iter(V + "docCUID"))
    r.note("FRBR_NUMBER", PASS if bool(numbers) != bool(cuids) else FAIL, name, f"{len(numbers)} FRBRnumber, {len(cuids)} docCUID (one of the two required, not both)")  # fmt: skip
    this = _value(w, "FRBRthis")
    if oj:
        if not this:
            r.note("FRBR_NUMBER_OJ", MISSING, name, f"FRBRnumber {numbers} cannot be the extract of the official URI: FRBRthis is not known")
        else:
            ext = "eli/" + this.split("/eli/", 1)[1] if "/eli/" in this else this.split("/resource/", 1)[-1]
            ok = any(n in (ext, ext.removesuffix("/oj")) for n in numbers)
            r.note("FRBR_NUMBER_OJ", PASS if ok else FAIL, name, f"FRBRnumber {numbers} is not the extract {ext!r} of FRBRthis")

    pres = [c.get("value") for c in w.findall(A + "FRBRprescriptive")]
    if is_gazette:
        r.note("FRBR_PRESCRIPTIVE", FAIL if pres else PASS, name, "FRBRprescriptive is not used for an officialGazette")
    elif is_act or is_annex:
        want = ["false"] if d.get("name") == "REC" else ["true"]
        r.note("FRBR_PRESCRIPTIVE", PASS if pres == want else FAIL, name, f"FRBRprescriptive {pres}, expected {want}")

    lang = ex.find(A + "FRBRlanguage")
    code = lang.get("language") if lang is not None else None
    tlcs = [n for n in refs.values() if _local(n) == "TLCReference" and n.get("name") == "language"]
    problems = []
    if not re.fullmatch(r"[a-z]{2}", code or ""):
        problems.append(f"FRBRlanguage/@language {code!r} is not a 2-letter code")
    if not any(re.fullmatch(re.escape(AUTH) + r"language/[A-Z]{3}", n.get("href") or "") and n.get("showAs") == code for n in tlcs):
        problems.append("no TLCReference name='language' with a language/XXX href and @showAs = the 2-letter code")
    if oj and lang is not None:
        t = _resolve(refs, lang.get("refersTo"))
        three = (t.get("href") or "").rsplit("/", 1)[-1] if t is not None else None
        if t is None or t not in tlcs or not (t.get(XID) == t.get("eId") == three):
            problems.append(f"FRBRlanguage/@refersTo {lang.get('refersTo')!r} does not point to the language TLCReference with eId = xml:id = 3-letter code")  # fmt: skip
    r.note("FRBR_LANGUAGE", FAIL if problems else PASS, name, "; ".join(problems))

    version = mf.find(f"{A}preservation/{V}akn4euVersion")
    if version is None:
        r.note("AKN4EU_VERSION", FAIL, name, "no preservation/akn4eu:akn4euVersion")
    elif version.get("value") != TARGET_VERSION:
        r.note("AKN4EU_VERSION", FAIL, name, f"declares AKN4EU {version.get('value')!r}: these rules are those of {TARGET_VERSION}; a file of another version must be checked against that version")  # fmt: skip
    else:
        r.note("AKN4EU_VERSION", PASS, name)
    doc = mf.find(f"{A}preservation/{V}akn4euDocumentation")
    r.note("AKN4EU_DOCUMENTATION", PASS if doc is not None and doc.get("href") == AKN4EU_DOCUMENTATION else FAIL, name,
           f"akn4euDocumentation/@href {None if doc is None else doc.get('href')!r}")  # fmt: skip

    if not oj:
        r.note("OJ_PUBLICATION", FAIL if d.find(f"{A}meta/{A}publication") is not None else NA, name, "publication is forbidden outside the Official Journal")  # fmt: skip
        return
    _oj_metadata(name, d, docs, lv, refs, this, is_act, is_annex, is_gazette, r)


def _oj_metadata(name, d, docs, lv, refs, this, is_act, is_annex, is_gazette, r: _Results) -> None:
    w, ex, mf = lv["FRBRWork"], lv["FRBRExpression"], lv["FRBRManifestation"]
    uri = _value(w, "FRBRuri")
    lang3 = next(((n.get("href") or "").rsplit("/", 1)[-1].lower() for n in refs.values() if _local(n) == "TLCReference" and n.get("name") == "language"), "")  # fmt: skip
    # official URIs
    if not this:
        what = "the act's ELI" if is_act else "the annex's own ELI" if is_annex else "the Official Journal URI"
        r.note("OJ_URI", MISSING, name, f"FRBRthis/FRBRuri empty: {what} is neither printed in the source nor supplied")
    else:
        problems = []
        if is_act:
            m = ELI_ACT.match(this)
            if m is None or m["type"] != (d.get("name") or "").lower():
                problems.append(f"FRBRthis {this!r} is not the ELI .../eli/{(d.get('name') or '').lower()}/<year>/<number>/oj")
            if uri != this:
                problems.append("FRBRuri differs from FRBRthis")
        elif is_annex:
            if not ELI_ANNEX.match(this):
                problems.append(f"FRBRthis {this!r} is not an annex ELI .../anx.../oj")
            act_eli = next((_value(_levels(x)["FRBRWork"], "FRBRthis") for x in docs.values() if _local(x) == "act"), None)
            if act_eli and uri != act_eli:
                problems.append(f"FRBRuri {uri!r} is not the act's ELI")
        elif is_gazette:
            if not this.startswith(OJ_RESOURCE) or "/eli/" in this:
                problems.append(f"FRBRthis {this!r} is not an Official Journal resource URI")
            if uri != this:
                problems.append("FRBRuri differs from FRBRthis")
        if not is_annex:  # Expression and Manifestation (the annex sample follows no stated pattern there)
            # an OJ resource URI takes the language either as "/eng" (pre-ABA, Part 2.8 p.208) or ".ENG" (ABA, p.199)
            expr = [f"{this}/{lang3}"] + ([f"{this}.{lang3.upper()}"] if is_gazette else [])
            manif = [f"{this}/{lang3}/akn4eu"] + ([f"{this}.{lang3.upper()}.akn4eu_leg"] if is_gazette else [])
            if _value(ex, "FRBRthis") not in expr:
                problems.append(f"FRBRExpression/FRBRthis {_value(ex, 'FRBRthis')!r}, expected {' or '.join(expr)}")
            if _value(mf, "FRBRthis") not in manif:
                problems.append(f"FRBRManifestation/FRBRthis {_value(mf, 'FRBRthis')!r}, expected {' or '.join(manif)}")
        r.note("OJ_URI", FAIL if problems else PASS, name, "; ".join(problems))

    pub_date = next((x.get("date") for x in w.findall(A + "FRBRdate") if x.get("name") == "publication"), None)
    pub = d.find(f"{A}meta/{A}publication")
    if pub_date is None:
        r.note("OJ_DATES", FAIL, name, "no FRBRWork/FRBRdate[@name='publication']")
    elif pub is not None and pub.get("date") != pub_date:
        r.note("OJ_DATES", FAIL, name, f"FRBRdate publication {pub_date} differs from publication/@date {pub.get('date')}")
    else:
        r.note("OJ_DATES", PASS, name)

    authors = [a.get("href") or "" for a in w.findall(A + "FRBRauthor")]
    orgs = [_resolve(refs, a) for a in authors]
    problems = []
    if not authors or any(o is None or _local(o) != "TLCOrganization" or not (o.get("href") or "").startswith(AUTH + "corporate-body/") for o in orgs):  # fmt: skip
        problems.append(f"FRBRWork/FRBRauthor {authors} does not refer to institutions of the corporate-body table")
    elif is_gazette and [o.get("href") for o in orgs] != [AUTH + "corporate-body/EURUN"]:
        problems.append("officialGazette author is not EURUN")
    below = [a.get("href") for lvl in (ex, mf) for a in lvl.findall(A + "FRBRauthor")]
    if any(below):
        problems.append(f"FRBRauthor of FRBRExpression/FRBRManifestation not empty: {below}")
    r.note("OJ_AUTHOR", FAIL if problems else PASS, name, "; ".join(problems))

    if is_act or is_annex:
        attrs = {k: pub.get(k) for k in ("date", "number", "showAs", "name")} if pub is not None else {}
        r.note("OJ_PUBLICATION", PASS if pub is not None and all(attrs.values()) else FAIL, name,
               "no meta/publication" if pub is None else f"publication attributes {attrs}")  # fmt: skip
    elif pub is not None:
        r.note("OJ_PUBLICATION", FAIL, name, "publication is used only for the published act and its annexes")

    problems = []
    for n in d.iterfind(f"{A}meta/{A}references/*"):
        href = n.get("href") or ""
        if _local(n) not in TLC or not href.startswith(AUTH):
            continue
        code = href.rstrip("/").rsplit("/", 1)[-1]
        label = f"{_local(n)} {n.get(XID)!r}"
        if n.get("name") != "language" and n.get(XID) != code:  # language: xml:id optional (p.113)
            problems.append(f"{label}: xml:id is not the authority code {code!r}")
        if n.get("name") not in TLC_EXCEPTIONS and n.get("showAs") not in ("", None):
            problems.append(f"{label}: @showAs {n.get('showAs')!r} (must be empty)")
        if n.get(XID) and n.get("eId") != n.get(XID):
            problems.append(f"{label}: eId {n.get('eId')!r} differs from xml:id")
    r.note("TLC_AUTHORITY", FAIL if problems else PASS, name, "; ".join(problems[:10]) + (f" (+{len(problems) - 10} more)" if len(problems) > 10 else ""))  # fmt: skip

    if is_act:
        problems = []
        for t, e in ACT_EIDS.items():
            n = d.find(f"{A}preface/{A}longTitle") if t == "longTitle" else d.find(A + t)
            if n is not None and n.get("eId") != e:
                problems.append(f"{t} eId {n.get('eId')!r}, expected {e!r}")
        for tag, prefix in (("citation", "cit_"), ("recital", "rct_")):
            for i, n in enumerate(d.iter(A + tag), start=1):
                if not re.fullmatch(prefix + r"\d+", n.get("eId") or ""):
                    problems.append(f"{tag} {i}: eId {n.get('eId')!r}, expected {prefix}N")
        r.note("ELI_EIDS", FAIL if problems else PASS, name, "; ".join(problems[:10]))
    if is_annex:
        mb = d.find(A + "mainBody")
        bad = [n.get("eId") for n in d.iter() if isinstance(n.tag, str) and n.get("eId") and not n.xpath("ancestor::a:meta", namespaces={"a": AKN_NS})
               and not re.match(r"anx(_\w+)?(/|$)", n.get("eId"))]  # fmt: skip
        if mb is not None and mb.get("eId"):
            bad.insert(0, f"mainBody {mb.get('eId')!r}")
        r.note("ANNEX_EIDS", FAIL if bad else PASS, name, f"eIds not in the annex's context: {bad[:10]}")


# ---- the DocumentModel ------------------------------------------------------------------------------------------------------
def _model(model: DocumentModel, result, text: dict, source: dict | None, docs: dict, r: _Results) -> None:
    unmapped = list(dict.fromkeys(list(result.excluded.get("unmapped", [])) + [u["model_id"] for u in result.unmapped]))
    included = set(result.included_ids)
    furniture = {e.id for e in model.furniture}
    lost = [e.id for e in model.elements if e.type != T.DOCUMENT and e.id not in included and e.id not in furniture]
    bad = list(dict.fromkeys(unmapped + lost))
    r.note("MODEL_COMPLETE", FAIL if bad else PASS, None, f"{len(bad)} model element(s) not in the XML: {bad[:20]}")
    r.note("MODEL_TEXT_ORDER", PASS if text.get("same_order_and_text") else FAIL, None,
           f"{len(text.get('text_mismatches', []))} text mismatch(es), {len(text.get('missing_nodes', []))} missing node(s), "
           f"document order preserved: {text.get('document_order_preserved')}, footnote order preserved: {text.get('footnote_order_preserved')}")  # fmt: skip

    act = docs.get(result.act_file)
    annexes = model.of_type(T.ANNEX)
    hrefs = [x.get("href") for x in act.iterfind(f"{A}attachments/{A}attachment/{A}documentRef")] if act is not None else []
    problems = [f"{len(annexes)} annexes in the model, {len(hrefs)} referenced by the act"] if len(hrefs) != len(annexes) else []
    for el, href in zip(annexes, hrefs):
        num = docs[href].findtext(f"{A}mainBody/{A}annex/{A}num") if href in docs else None
        if el.id not in included or num != el.marker:
            problems.append(f"{el.id}: {href!r} has number {num!r}, model {el.marker!r}")
    r.note("MODEL_ANNEXES", FAIL if problems else PASS, None, "; ".join(problems[:20]))

    md = model.metadata
    want = RESOURCE_TYPE.get(md.document_type or "")
    r.note("MODEL_ACT_TYPE", PASS if act is not None and want and act.get("name") == want else FAIL, result.act_file,
           f"act/@name {None if act is None else act.get('name')!r} for the printed type {md.document_type!r} (expected {want!r})")  # fmt: skip
    pub = act.find(f"{A}meta/{A}publication") if act is not None else None
    if not (md.publication_date and md.publication_reference):
        r.note("MODEL_PUBLICATION", MISSING, result.act_file, "the Official Journal date or reference is not printed in the extracted pages")
    else:
        ok = pub is not None and (pub.get("date"), pub.get("number")) == (md.publication_date, md.publication_reference)
        r.note("MODEL_PUBLICATION", PASS if ok else FAIL, result.act_file, f"publication {None if pub is None else dict(pub.attrib)} vs printed {md.publication_reference} of {md.publication_date}")  # fmt: skip

    review = model.review or None
    source = source or {"kind": "effective_reviewed_model" if review else "document_model", "model_revision": (review or {}).get("model_revision")}  # fmt: skip
    corrected = [e.id for e in model.elements if e.reviewed]
    if source.get("kind") == "effective_reviewed_model":
        problems = []
        if review is None or review.get("model_revision") != source.get("model_revision"):
            problems.append(f"the exported model is not the effective model of revision {source.get('model_revision')}")
        problems += [f"corrected element {i} is not in the XML" for i in corrected if i not in included]
        r.note("MODEL_REVIEW", FAIL if problems else PASS, None, "; ".join(problems))
    elif source.get("review_corrections"):
        r.note("MODEL_REVIEW", FAIL, None, f"a review with {source['review_corrections']} correction(s) exists, but its effective model was not exported")
    else:
        r.note("MODEL_REVIEW", PASS, None)


# ---- summary ------------------------------------------------------------------------------------------------------------------
def _summary(r: _Results) -> dict:
    rules = []
    for rule, (layer, level, source, requirement) in RULES.items():
        res = r.out[rule]
        rules.append({"rule": rule, "layer": layer, "level": level, "source": source, "requirement": requirement,
                      "status": res["status"], "findings": res["findings"][:MAX_FINDINGS], "findings_total": len(res["findings"])})  # fmt: skip
    pick = lambda status, level="MUST": [x["rule"] for x in rules if x["status"] == status and x["level"] == level]  # noqa: E731
    failed, missing, deviations = pick(FAIL), pick(MISSING), pick(DEVIATION)
    if failed:
        verdict = f"FAILED: {len(failed)} mandatory rule(s) violated"
    elif missing or deviations:
        verdict = (f"NOT conformant: {len(missing)} mandatory rule(s) need information the source does not provide, "
                   f"{len(deviations)} deliberate deviation(s); no rule is violated otherwise")  # fmt: skip
    else:
        verdict = "all implemented mandatory rules met (not an official AKN4EU validation)"
    return {
        "target_version": TARGET_VERSION,
        "specification": SPECIFICATION,
        "performed_by": "ODOS rule implementation (odos.akn.akn4eu_validate), not the official AKN4EU validator",
        "verdict": verdict,
        "passed": not failed,  # no mandatory rule violated; missing input and deviations are reported, not hidden
        "complete": not (failed or missing or deviations),
        "counts": dict(Counter(x["status"] for x in rules)),
        "failed": failed,
        "missing_input": missing,
        "deviations": deviations,
        "warnings": pick(WARN, "SHOULD") + pick(MISSING, "SHOULD"),  # SHOULD rules not met: never part of "failed"
        "layers": {layer: {s: [x["rule"] for x in rules if x["layer"] == layer and x["status"] == s] for s in (FAIL, MISSING, DEVIATION)}
                   for layer in ("xml", "package", "metadata", "model")},  # fmt: skip
        "rules": rules,
        "not_checked": NOT_CHECKED,
        "specification_notes": SPECIFICATION_NOTES,
        "meaning": "Rules read from the AKN4EU 5.0.1.0 specification and implemented by ODOS. Passing them is not official "
                   "AKN4EU conformance: the official validation artefacts were not available and only the listed rules are checked.",
    }  # fmt: skip
