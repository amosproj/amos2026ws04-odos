"""AKN4EU sample-compatibility checks (not an official AKN4EU validator).

Each rule states a regularity that holds for *every* XML file of the official AKN4EU 5.0.1.0 sample
package (tests/test_akn4eu.py runs all rules over all 60 samples). Passing them means "built like the
official samples", nothing more: the official AKN4EU validation artefacts were not available, so
conformance to AKN4EU is not verified by these checks.
"""

from __future__ import annotations

import re

from lxml import etree

from odos.akn.akn4eu import AKN4EU_NS, AKN4EU_VERSION, XID
from odos.akn.mapping import AKN_NS

A = f"{{{AKN_NS}}}"
XML_NS = "http://www.w3.org/XML/1998/namespace"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
DOC_TYPES = {"act", "bill", "doc", "documentCollection", "officialGazette"}
NEEDS_XML_ID = {"article", "paragraph", "subparagraph", "point", "list", "recital", "citation", "chapter", "num", "heading", "content"}  # fmt: skip
CONTENT_EID = re.compile(r"^(art_\d+(/unp_\d+)?|rct_\d+|cit_\d+|pbl_\d+|ent_\d+|fnp_\d+|tit_\d+|anx(/par_\d+(/tab_\d+(/(hdt|row)_\d+)?)?)?)$")  # fmt: skip

RULES = {
    "ROOT": "root akomaNtoso in the AKN namespace with one document element (act, bill, doc, documentCollection, officialGazette)",
    "DOC_NAME": "the document element names its AKN4EU type as an upper-case code (@name, e.g. REG, REG_IMPL, ANNEX)",
    "FRBR_LEVELS": "meta/identification has FRBRWork, FRBRExpression and FRBRManifestation",
    "FRBR_COUNTRY": "FRBRWork/FRBRcountry/@value is 'EU'",
    "FRBR_LANGUAGE": "FRBRExpression/FRBRlanguage/@language is a two-letter code",
    "EXPRESSION_DATE": "FRBRExpression/FRBRdate is the AKN4EU placeholder 2999-01-01",
    "AKN4EU_VERSION": f"FRBRManifestation/preservation declares akn4eu:akn4euVersion (samples: {AKN4EU_VERSION})",
    "FOREIGN_MARKUP": "no foreign-namespace attributes (except xsi:schemaLocation on the root); foreign elements only akn4eu:* inside preservation",  # fmt: skip
    "XML_ID": "every " + ", ".join(sorted(NEEDS_XML_ID)) + " outside meta has an xml:id",
    "XML_ID_UNIQUE": "xml:id values are unique",
    "REFERS_TO": "every #/~ reference in @refersTo resolves to an xml:id or eId of the same file",
    "EID_PATTERN": "content eIds follow the sample patterns (art_N, art_N/unp_N, rct_N, cit_N, anx/par_N, ...)",
    "NOTES_INLINE": "no meta/notes; every authorialNote has @marker and @placement",
    "POINT_IN_LIST": "every point is a child of list",
    "ANNEX_DOC": "doc[@name='ANNEX'] has mainBody/annex",
    "ATTACHMENT_REF": "every attachment holds exactly one documentRef with @href (resolving to a package file when a package is checked)",  # fmt: skip
}


def check_document(xml: bytes, package: set[str] | None = None) -> list[dict]:
    """Findings (rule, message) for one XML file; empty means every rule holds."""
    out: list[dict] = []

    def fail(rule: str, msg: str) -> None:
        out.append({"rule": rule, "message": msg})

    root = etree.fromstring(xml)
    docs = [c for c in root if isinstance(c.tag, str)]
    if root.tag != A + "akomaNtoso" or len(docs) != 1 or etree.QName(docs[0]).localname not in DOC_TYPES:
        fail("ROOT", "not an akomaNtoso root with one AKN4EU document element")
        return out
    d = docs[0]
    if not re.fullmatch(r"[A-Z][A-Z_-]*", d.get("name") or ""):
        fail("DOC_NAME", f"@name {d.get('name')!r}")
    meta = d.find(A + "meta")
    ident = meta.find(A + "identification") if meta is not None else None
    levels = {lvl: ident.find(A + lvl) if ident is not None else None for lvl in ("FRBRWork", "FRBRExpression", "FRBRManifestation")}  # fmt: skip
    if any(v is None for v in levels.values()):
        fail("FRBR_LEVELS", "missing FRBR level(s)")
    else:
        if [c.get("value") for c in levels["FRBRWork"].findall(A + "FRBRcountry")] != ["EU"]:
            fail("FRBR_COUNTRY", "FRBRcountry is not 'EU'")
        lang = levels["FRBRExpression"].find(A + "FRBRlanguage")
        if lang is None or not re.fullmatch(r"[a-z]{2}", lang.get("language") or ""):
            fail("FRBR_LANGUAGE", "FRBRlanguage/@language is not a two-letter code")
        if [x.get("date") for x in levels["FRBRExpression"].findall(A + "FRBRdate")] != ["2999-01-01"]:
            fail("EXPRESSION_DATE", "FRBRExpression/FRBRdate is not the placeholder date")
        if levels["FRBRManifestation"].find(f"{A}preservation/{{{AKN4EU_NS}}}akn4euVersion") is None:
            fail("AKN4EU_VERSION", "no akn4eu:akn4euVersion")
    in_meta = set(meta.iter()) if meta is not None else set()
    ids: list[str] = []
    for n in root.iter():
        if not isinstance(n.tag, str):
            continue
        q = etree.QName(n)
        for a in n.attrib:
            ns = etree.QName(a).namespace
            if ns and ns != XML_NS and not (ns == XSI_NS and n is root):
                fail("FOREIGN_MARKUP", f"attribute {a} on {q.localname}")
        if q.namespace != AKN_NS and not (q.namespace == AKN4EU_NS and n.getparent() is not None and n.getparent().tag == A + "preservation"):  # fmt: skip
            fail("FOREIGN_MARKUP", f"element {n.tag}")
        if n.get(XID):
            ids.append(n.get(XID))
        if n in in_meta:
            continue
        if q.localname in NEEDS_XML_ID and n.get(XID) is None:
            fail("XML_ID", f"{q.localname} without xml:id")
        if n.get("eId") and not CONTENT_EID.match(n.get("eId")):
            fail("EID_PATTERN", f"eId {n.get('eId')!r} on {q.localname}")
        if q.localname == "authorialNote" and not (n.get("marker") and n.get("placement")):
            fail("NOTES_INLINE", "authorialNote without @marker/@placement")
        if q.localname == "point" and n.getparent().tag != A + "list":
            fail("POINT_IN_LIST", f"point {n.get(XID)} inside {etree.QName(n.getparent()).localname}")
        if q.localname == "attachment":
            refs = n.findall(A + "documentRef")
            if len(refs) != 1 or not refs[0].get("href"):
                fail("ATTACHMENT_REF", f"attachment {n.get(XID)} without exactly one documentRef/@href")
            elif package is not None and refs[0].get("href") not in package:
                fail("ATTACHMENT_REF", f"documentRef {refs[0].get('href')!r} is not in the package")
    if len(ids) != len(set(ids)):
        fail("XML_ID_UNIQUE", f"{len(ids) - len(set(ids))} duplicate xml:id value(s)")
    known = set(ids) | {n.get("eId") for n in root.iter() if isinstance(n.tag, str) and n.get("eId")}
    for n in root.iter():
        if isinstance(n.tag, str):
            for v in (n.get("refersTo") or "").split():
                if v[:1] in "#~" and v[1:] not in known:
                    fail("REFERS_TO", f"refersTo {v!r} on {etree.QName(n).localname} does not resolve")
    if meta is not None and meta.find(A + "notes") is not None:
        fail("NOTES_INLINE", "meta/notes present")
    if d.get("name") == "ANNEX" and d.find(f"{A}mainBody/{A}annex") is None:
        fail("ANNEX_DOC", "ANNEX without mainBody/annex")
    return out


def check_package(files: dict[str, bytes]) -> dict:
    """All rules over all files of a package; documentRefs must resolve to files of the package."""
    names = set(files)
    per_file = {name: check_document(xml, names) for name, xml in files.items()}
    return {
        "rules": RULES,
        "passed": not any(per_file.values()),
        "files": {name: {"passed": not f, "findings": f} for name, f in per_file.items()},
        "meaning": "sample compatibility: built like the official AKN4EU 5.0.1.0 samples; not an official AKN4EU validation",
    }
