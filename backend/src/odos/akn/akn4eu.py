"""AKN4EU export profile (``akn4eu``) for EU legislation, separate from the generic AKN exports.

Modelled on the official AKN4EU 5.0.1.0 samples of the Publications Office (above all the published
Implementing Regulation (EU) 2025/864) and validated against the OASIS AKN 3.1 schema, the base of
AKN4EU 5.x. The result is *sample-compatible*; no official AKN4EU schema or Schematron was available,
so AKN4EU conformance is not verified (see Documentation/akn4eu-mapping.md).

What differs from the generic EU export (``eu_generator``), each following the samples:

- ``xml:id`` on every content element; AKN4EU-style ``eId`` (``art_1``, ``art_1/unp_1``, ``rct_1`` ...)
  only where the samples use one;
- FRBR identifiers in the AKN4EU layout, references to the EU authority tables; an ELI only when the
  caller supplies one that agrees with the printed type and number, otherwise empty as in the drafting
  samples (nothing is invented);
- footnotes as inline ``authorialNote`` at their "( n )" reference, points inside ``list``, the binding
  clause in ``body/clause``, each annex a separate ``doc name="ANNEX"`` file linked by ``documentRef``.

No ODOS attributes are written into the XML: provenance, uncertainty and review state go to the
traceability data. Text is written verbatim from the model; the only rearrangements (a footnote
reference moved into ``authorialNote/@marker``, the "( n )" prefix of a footnote's own text) are
recorded per element so that the original text can be rebuilt and checked.
"""

from __future__ import annotations

import re

from lxml import etree
from pydantic import BaseModel, Field

from odos.akn.eu_generator import BLOCKS, local_name
from odos.akn.generator import XML_ILLEGAL
from odos.akn.mapping import AKN_NS
from odos.normalization.lang_de import MONTHS
from odos.document_model import DocumentModel, Element, ElementType as T

A = f"{{{AKN_NS}}}"
AKN4EU_NS = "http://imfc.europa.eu/akn4eu"
AKN4EU_VERSION = "5.0.0.1"  # the value the files of the AKN4EU 5.0.1.0 sample package declare
AKN4EU_DOCUMENTATION = "https://op.europa.eu/en/web/eu-vocabularies/dataset/-/resource?uri=http://publications.europa.eu/resource/dataset/akn4eu"  # fmt: skip
AUTH = "http://publications.europa.eu/resource/authority/"
PLACEHOLDER_DATE = "2999-01-01"  # AKN4EU's "no date" value (all samples)
XID = "{http://www.w3.org/XML/1998/namespace}id"
LANG = ("de", "DEU", "deu")  # ISO 639-1, EU authority code, ELI language segment; the EU parser reads German acts

RESOURCE_TYPE = {
    "VERORDNUNG": "REG", "DURCHFÜHRUNGSVERORDNUNG": "REG_IMPL", "DELEGIERTE VERORDNUNG": "REG_DEL",
    "RICHTLINIE": "DIR", "DURCHFÜHRUNGSRICHTLINIE": "DIR_IMPL", "DELEGIERTE RICHTLINIE": "DIR_DEL",
    "BESCHLUSS": "DEC", "DURCHFÜHRUNGSBESCHLUSS": "DEC_IMPL", "DELEGIERTER BESCHLUSS": "DEC_DEL",
}  # fmt: skip
# corporate bodies recognised in printed text: authority code, pattern, German label of the authority table
CORPORATE = [
    ("EP", re.compile(r"Europäischen Parlaments", re.I), "Europäisches Parlament"),
    ("CONSIL", re.compile(r"\bRates\b", re.I), "Rat der Europäischen Union"),
    ("COM", re.compile(r"\bKommission\b", re.I), "Europäische Kommission"),
]
PLACES = {"Straßburg": "FRA_SXB", "Brüssel": "BEL_BRU", "Luxemburg": "LUX_LUX"}

HIER = {T.CHAPTER: "chapter", T.SECTION: "section", T.ARTICLE: "article", T.ARTICLE_PARAGRAPH: "paragraph",
        T.ANNEX_PART: "part", T.ANNEX_HEADING: "level"}  # fmt: skip
CONTAINERS = (T.CHAPTER, T.SECTION, T.ANNEX_PART, T.ANNEX_HEADING)  # num + heading + hierarchical children
POINTS = (T.NUMBERED_POINT, T.POINT, T.SUBPOINT)
NOTES = (T.FOOTNOTE,)
NO_XML_ID = {"attachments"}  # elements whose schema type has no xml:id attribute
BINDING_CLAUSE = re.compile(r"^Diese[rs]? (Verordnung|Richtlinie|Beschluss) ist in allen ihren Teilen verbindlich")
DONE_AT = re.compile(r"^(Geschehen zu )(\S+)( am )(\d{1,2}\. \w+ \d{4})(\.)$")
SIGNATORY = re.compile(r"(Im Namen d(?:es|er) .+?) (Die Präsidentin|Der Präsident) (.+?)(?= Im Namen d(?:es|er) |$)")
TITLE = re.compile(r"^(?P<type>.+?) (?P<num>\((?P<dom>EU|EG|EWG|Euratom)\) (?P<no>\d{4}/\d+))(?P<rest> .+)?$")


def signatories(e: Element) -> tuple[list[tuple[str, str, str]], bool]:
    """(organization, role, person) per signatory, if the signature block is unambiguous; and whether it
    came from a table (Docling: one column per signatory, rows organization / role / person) or from text."""
    rows = e.table.rows if e.table else None
    if rows:
        ok = len(rows) == 3 and len({len(r) for r in rows}) == 1 and all(
            re.fullmatch(r"Im Namen d(?:es|er) .+", rows[0][c] or "") and rows[1][c] in ("Die Präsidentin", "Der Präsident") and rows[2][c]
            for c in range(len(rows[0])))  # fmt: skip
        return ([(rows[0][c], rows[1][c], rows[2][c]) for c in range(len(rows[0]))] if ok else []), True
    if e.type in (T.TEXT, T.SIGNATURE):
        found = SIGNATORY.findall(e.content_text)
        if found and " ".join(" ".join(s) for s in found) == e.content_text:
            return found, False
    return [], False


class Akn4EuResult(BaseModel):
    files: dict[str, bytes]  # file name -> XML, the act first, then the annexes in order
    act_file: str
    entries: list[dict]  # one per included model element, in document order
    included_ids: list[str]
    excluded: dict[str, list[str]]
    unmapped: list[dict] = Field(default_factory=list)
    warnings: list[dict] = Field(default_factory=list)
    identifiers: dict
    scope: dict


def german_date(text: str) -> str | None:
    m = re.fullmatch(r"(?:vom )?(\d{1,2})\. (\w+) (\d{4})", text.strip())
    if not m or m.group(2) not in MONTHS:
        return None
    return f"{int(m.group(3)):04d}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"


def node_text(node, notes: dict[str, str] | None = None) -> str:
    """String value of a node without authorialNote content; with ``notes`` (note xml:id -> reference
    text) the footnote references the notes replaced are put back."""
    out = [node.text or ""]
    for c in node:
        if not isinstance(c.tag, str):
            out.append(c.tail or "")
            continue
        if c.tag == A + "authorialNote":
            out.append((notes or {}).get(c.get(XID), ""))
        else:
            out.append(node_text(c, notes))
        out.append(c.tail or "")
    return "".join(out)


def check_eli(eli: str | None, rtype: str, number: str) -> str | None:
    """A caller-supplied ELI is used only if it is an EU ELI for exactly this act (type, year, number)."""
    if eli is None:
        return None
    year, no = number.split("/", 1)
    want = f"http://data.europa.eu/eli/{rtype.lower()}/{year}/{int(no)}/oj"
    if eli.rstrip("/") != want:
        raise ValueError(f"ELI {eli!r} does not match the printed act ({want}); refusing to use it")
    return want


class _File:
    def __init__(self, name: str):
        self.name = name
        self.ids: set[str] = set()
        self.eids: set[str] = set()
        self.refs: dict[str, tuple] = {}  # xml:id -> (tag, attrs), written into meta/references at the end

    def reg(self, base: str) -> str:
        out, n = base, 2
        while out in self.ids:
            out = f"{base}-{n}"
            n += 1
        self.ids.add(out)
        return out


class _G:
    def __init__(self, model: DocumentModel):
        self.m = model
        self.by_id = model.by_id()
        self.entries: dict[str, dict] = {}
        self.order: list[str] = []
        self.unmapped: list[dict] = []
        self.warnings: list[dict] = []
        self.texts: dict[str, list] = {}  # model id -> XML nodes carrying its text (footnote anchors)
        self.note_refs: dict[str, str] = {}  # note xml:id -> reference text it replaced ("" if none)
        self.f: _File

    # -- small helpers -----------------------------------------------------------------------------------
    def children(self, el: Element) -> list[Element]:
        return [self.by_id[c] for c in el.children_ids]

    def node(self, parent, tag: str, xid: str | None = None, **attrs) -> etree._Element:
        n = etree.SubElement(parent, A + tag, **{k: v for k, v in attrs.items() if v is not None})
        if xid:
            n.set(XID, self.f.reg(xid))
        return n

    def eid(self, node, base: str) -> None:
        out, n = base, 2
        while out in self.f.eids:
            out = f"{base}-{n}"
            n += 1
        if out != base:
            self.warnings.append({"code": "DUPLICATE_EID", "eId": base, "used": out})
        self.f.eids.add(out)
        node.set("eId", out)

    def ref(self, key: str, tag: str, **attrs) -> str:
        if key not in self.f.refs or attrs:
            self.f.refs[key] = (tag, attrs or self.f.refs.get(key, (tag, {}))[1])
        return key

    def text(self, parent, tag: str, value: str, xid: str, el: Element, **attrs) -> etree._Element:
        if XML_ILLEGAL.search(value):
            raise ValueError(f"{el.id}: text contains characters that are illegal in XML 1.0")
        n = self.node(parent, tag, xid, **attrs)
        n.text = value
        self.texts.setdefault(el.id, []).append(n)
        return n

    def trace(self, el: Element, akn: str, node=None, **ids) -> dict:
        e = {
            "model_id": el.id, "model_type": el.type.value, "file": self.f.name, "akn_element": akn,
            "xml_id": node.get(XID) if node is not None else None, "eId": node.get("eId") if node is not None else None,
            "num_id": None, "heading_id": None, "text_ids": [], "marker": el.marker, "title": el.title,
            "content_text": el.content_text, "original_text": el.original_text, "source_refs": el.source_refs,
            "docling_label": el.docling_label, "pages": el.pages, "provenance": [p.model_dump() for p in el.provenance],
            "source_spans": [s.model_dump() for s in el.source_spans], "uncertain": el.uncertain,
            "uncertainty_reasons": el.uncertainty_reasons, "reviewed": el.reviewed, **ids,
        }  # fmt: skip
        self.entries[el.id] = e
        self.order.append(el.id)
        if el.uncertain:
            self.warnings.append({"code": "UNCERTAIN_ELEMENT_INCLUDED", "model_id": el.id, "reasons": el.uncertainty_reasons})  # fmt: skip
        return e

    def skip(self, el: Element, why: str) -> None:
        self.unmapped.append({"model_id": el.id, "type": el.type.value, "reason": why, "original_text": el.original_text[:120]})  # fmt: skip
        self.warnings.append({"code": "UNMAPPED_ELEMENT", "model_id": el.id, "reason": why})

    def num_heading(self, node, el: Element, xid: str, entry: dict) -> None:
        if el.marker:
            entry["num_id"] = self.text(node, "num", el.marker, xid + "__num", el).get(XID)
        if el.title:
            entry["heading_id"] = self.text(node, "heading", el.title, xid + "__heading", el).get(XID)

    def own_p(self, parent, el: Element, xid: str, value: str | None = None) -> None:
        p = self.text(parent, "p", el.content_text if value is None else value, xid, el)
        self.entries[el.id]["text_ids"].append(p.get(XID))

    # -- footnotes: authorialNote at the reference ---------------------------------------------------------
    def notes_of(self, el: Element) -> None:
        for k in self.children(el):
            if k.type in NOTES:
                self.note(k, el)
            elif k.type == T.FOOTNOTE_HEADING:
                self.skip(k, "footnote headings are not part of the EU model mapping")

    def note(self, f: Element, anchor: Element) -> None:
        owner = anchor
        while owner is not None and not self.texts.get(owner.id):
            owner = self.by_id.get(owner.parent_id) if owner.parent_id else None
        if owner is None:
            self.skip(f, "no text node to attach the footnote to")
            return
        ref = f.marker or ""
        hits = []  # (node, child or None for node.text)
        for n in self.texts[owner.id]:
            if ref and (n.text or "").count(ref):
                hits += [(n, None)] * (n.text or "").count(ref)
            for c in n:
                if ref and (c.tail or "").count(ref):
                    hits += [(n, c)] * (c.tail or "").count(ref)
        xid = self.f.reg(f"fn_{(f.number or str(len(self.note_refs) + 1))}")
        note = etree.Element(A + "authorialNote", marker=f.number or ref.strip("() ") or "*", placement="bottom")
        note.set(XID, xid)
        placed = "at_reference"
        if owner is anchor and len(hits) == 1:
            n, c = hits[0]
            if c is None:
                before, _, after = (n.text or "").partition(ref)
                n.text, note.tail = before, after
                n.insert(0, note)
            else:
                before, _, after = (c.tail or "").partition(ref)
                c.tail, note.tail = before, after
                c.addnext(note)
            self.note_refs[xid] = ref
        else:  # reference not found exactly once in the anchor's text: keep the text as is, note at its end
            placed = "end_of_text"
            self.texts[owner.id][-1].append(note)
            self.note_refs[xid] = ""
            self.warnings.append({"code": "FOOTNOTE_REFERENCE_NOT_LOCATED", "model_id": f.id, "anchor": anchor.id,
                                  "detail": f"reference {ref!r} found {len(hits)} times; note appended, text unchanged"})  # fmt: skip
        body, prefix = f.content_text, ""
        if ref and body.startswith(ref):  # "( 1 ) ABl. C ..." -> marker="1", p "ABl. C ..."
            rest = body[len(ref) :]
            prefix = ref + rest[: len(rest) - len(rest.lstrip())]
        p = self.text(note, "p", body[len(prefix) :], xid + "__p", f)
        e = self.trace(f, "authorialNote", note, text_ids=[p.get(XID)])
        e["footnote"] = {"reference_text": ref, "placed": placed, "anchor_model_id": anchor.id,
                         "anchor_xml_id": note.getparent().get(XID), "stripped_prefix": prefix}  # fmt: skip

    # -- blocks and running text -------------------------------------------------------------------------
    def block(self, parent, b: Element, base: str) -> None:
        if b.type == T.TABLE or b.table is not None:
            t = self.node(parent, "table", base + "__tbl")
            e = self.trace(b, "table", t)
            cells = []
            for r, row in enumerate(b.table.rows if b.table else [], start=1):
                tr = self.node(t, "tr", f"{t.get(XID)}__tr_{r}")
                for c, cell in enumerate(row, start=1):
                    td = self.node(tr, "td", f"{tr.get(XID)}__td_{c}")
                    if cell:
                        cells.append(self.text(td, "p", cell, f"{td.get(XID)}__p", b).get(XID))
            e["cell_ids"] = cells
        else:
            p = self.text(parent, "p", b.content_text or b.original_text, base + "__p", b)
            self.trace(b, "p", p, text_ids=[p.get(XID)])
            if b.type in (T.UNMARKED_LIST_ITEM, T.UNRECOGNIZED):
                self.warnings.append({"code": f"{b.type.value.upper()}_AS_P", "model_id": b.id})
        self.notes_of(b)

    def item(self, parent, it, base: str) -> None:
        kind, el = it
        if kind == "own":
            self.own_p(parent, el, base + "__p")
        else:
            self.block(parent, el, base)

    def fill(self, node, xid: str, owner: Element | None, own: str, kids: list[Element]) -> None:
        """Running content of a paragraph or point: content/p, subparagraphs, or a list with points."""
        ok = []
        for k in kids:
            if k.type in POINTS or k.type in BLOCKS:
                ok.append(k)
            elif k.type not in NOTES:
                self.skip(k, f"no mapping for {k.type.value} inside {owner.type.value if owner else 'paragraph'}")
        items = ([("own", owner)] if own and owner is not None else []) + [("kid", k) for k in ok]
        pts = [i for i, (kind, k) in enumerate(items) if kind == "kid" and k.type in POINTS]
        if not pts:
            if len(items) == 1:
                self.item(self.node(node, "content", xid + "__content"), items[0], xid + "__content")
            for j, it in enumerate(items if len(items) > 1 else [], start=1):
                sp = self.node(node, "subparagraph", f"{xid}__subpara_{j}")
                self.item(self.node(sp, "content", sp.get(XID) + "__content"), it, sp.get(XID) + "__content")
            return
        first, last = pts[0], pts[-1]
        lst = self.node(node, "list", xid + "__list")
        for j, it in enumerate(items[:first], start=1):  # introductory text of the list
            sp = self.node(lst, "subparagraph", f"{lst.get(XID)}__intro_{j}", refersTo="~" + self.ref("INP", "TLCConcept", href=AUTH + "subdivision/INP", showAs=""))  # fmt: skip
            self.item(self.node(sp, "content", sp.get(XID) + "__content"), it, sp.get(XID) + "__content")
        for j, (kind, k) in enumerate(items[first : last + 1], start=1):
            if k.type in POINTS:
                self.point(k, lst, xid)
            else:
                sp = self.node(lst, "subparagraph", f"{lst.get(XID)}__between_{j}")
                self.item(self.node(sp, "content", sp.get(XID) + "__content"), (kind, k), sp.get(XID) + "__content")
                self.warnings.append({"code": "TEXT_BETWEEN_POINTS", "model_id": k.id})
        for j, it in enumerate(items[last + 1 :], start=1):  # text after the points closes the paragraph
            sp = self.node(node, "subparagraph", f"{xid}__after_{j}")
            self.item(self.node(sp, "content", sp.get(XID) + "__content"), it, sp.get(XID) + "__content")

    def point(self, el: Element, parent, owner_xid: str) -> None:
        xid = f"{owner_xid}__{local_name(el)}"
        n = self.node(parent, "point", xid)
        e = self.trace(el, "point", n)
        self.num_heading(n, el, n.get(XID), e)
        self.fill(n, n.get(XID), el, el.content_text, self.children(el))
        self.notes_of(el)

    # -- hierarchy ---------------------------------------------------------------------------------------
    def hier_kids(self, node, xid: str, el: Element, unp: tuple[str, str] | None) -> None:
        """Children of a chapter/article/annex/part/level. Runs of running text and points become
        unnumbered paragraphs (``unp``: eId base and local name, e.g. ("art_3", "unp"), ("anx", "par"))."""
        run: list[Element] = []
        j = 0

        def flush():
            nonlocal j, run
            if not run:
                return
            j += 1
            p = self.node(node, "paragraph", f"{xid}__unp_{j}")
            if unp:
                self.eid(p, f"{unp[0]}/{unp[1]}_{j}")
            self.fill(p, p.get(XID), None, "", run)
            run = []

        for k in self.children(el):
            if k.type in NOTES:
                continue
            if k.type == T.ARTICLE_PARAGRAPH:  # numbered "(n)" paragraphs: in articles and in annex sections
                flush()
                self.paragraph(k, node, xid)
            elif k.type == T.ARTICLE:
                flush()
                self.article(k, node)
            elif k.type in CONTAINERS:
                flush()
                self.container(k, node, xid)
            elif k.type in POINTS or k.type in BLOCKS:
                run.append(k)
            else:
                self.skip(k, f"no mapping for {k.type.value} inside {el.type.value}")
        flush()

    def container(self, el: Element, parent, pxid: str | None) -> None:
        n = self.node(parent, HIER[el.type], f"{pxid}__{local_name(el)}" if pxid else local_name(el))
        e = self.trace(el, HIER[el.type], n)
        self.num_heading(n, el, n.get(XID), e)
        self.notes_of(el)
        self.hier_kids(n, n.get(XID), el, None)

    def article(self, el: Element, parent) -> None:
        local = f"art_{el.number}" if el.number else local_name(el)
        n = self.node(parent, "article", local)
        self.eid(n, local)
        e = self.trace(el, "article", n)
        self.num_heading(n, el, n.get(XID), e)
        self.notes_of(el)
        self.hier_kids(n, n.get(XID), el, (n.get("eId"), "unp"))

    def paragraph(self, el: Element, parent, pxid: str) -> None:
        n = self.node(parent, "paragraph", f"{pxid}__{local_name(el)}")
        e = self.trace(el, "paragraph", n)
        self.num_heading(n, el, n.get(XID), e)
        self.fill(n, n.get(XID), el, el.content_text, self.children(el))
        self.notes_of(el)

    # -- xml:id for every remaining content element ------------------------------------------------------------
    def fill_ids(self, node, base: str) -> None:
        seen: dict[str, int] = {}
        for c in node:
            if not isinstance(c.tag, str):
                continue
            tag = etree.QName(c).localname
            if tag == "meta":
                continue
            seen[tag] = seen.get(tag, 0) + 1
            if c.get(XID) is None and tag not in NO_XML_ID:
                c.set(XID, self.f.reg(f"{base}__{tag}_{seen[tag]}" if base else f"{tag}_{seen[tag]}"))
            self.fill_ids(c, c.get(XID) or f"{base}__{tag}")


def generate_akn4eu(model: DocumentModel, retrieval_date: str, eli: str | None = None) -> Akn4EuResult:
    if model.profile != "eu_legislation":
        raise ValueError("the akn4eu profile needs a model parsed with the eu_legislation profile")
    md = model.metadata
    if not (md.adoption_date and md.document_number and md.document_type):
        raise ValueError("EU metadata incomplete (adoption date, type or number missing in the source); refusing to invent them")  # fmt: skip
    rtype = RESOURCE_TYPE.get(md.document_type)
    if rtype is None:
        raise ValueError(f"no AKN4EU resource type for the printed document type {md.document_type!r}")
    eli = check_eli(eli, rtype, md.document_number)
    year, no = md.document_number.split("/", 1)
    slug = f"{rtype.lower()}_{year}_{int(no)}"
    g = _G(model)
    by_id = g.by_id
    tops = [by_id[c] for c in by_id[model.root_id].children_ids]
    annexes = [e for e in tops if e.type == T.ANNEX]
    authors = [c for c, rx, _ in CORPORATE if rx.search(md.issuing_bodies or "")]
    if not authors:
        g.warnings.append({"code": "AUTHOR_NOT_DETERMINED", "detail": f"issuing bodies {md.issuing_bodies!r} not in the authority mapping"})  # fmt: skip
    if eli is None:
        g.warnings.append({"code": "NO_ELI", "detail": "no ELI printed or supplied: FRBRthis/FRBRuri left empty as in the AKN4EU drafting samples"})  # fmt: skip
    elif len(annexes) > 1:
        g.warnings.append({"code": "ANNEX_ELI_UNKNOWN", "detail": "the ELI of each of several annexes is not known; annex FRBRthis left empty"})  # fmt: skip
    files: dict[str, etree._Element] = {}
    act_file = f"act-{slug}-{LANG[0]}.xml"
    labels = {c: label for c, _, label in CORPORATE}

    def comment(root, what: str) -> None:
        n_unc = sum(1 for e in model.elements if e.uncertain)
        root.addprevious(etree.Comment(
            f" PROTOTYPE CONVERSION: {what} generated by ODOS from Docling output of {md.title}, modelled on the AKN4EU "
            f"{AKN4EU_VERSION} samples. Text is the extracted text, not the authentic Official Journal edition. "
            f"Sample-compatible AKN4EU, NOT officially verified. {n_unc} model elements are uncertain; provenance, "
            "uncertainty and review state are in akn4eu_traceability.json. "))  # fmt: skip

    def identification(meta, annex_no: int | None) -> None:
        ident = etree.SubElement(meta, A + "identification", source="~" + g.ref("ODOS", "TLCOrganization", href="/ontology/organization/odos", showAs="ODOS prototype converter (AMOS 2026)"))  # fmt: skip
        work = eli or ""
        this = work
        if annex_no is not None:
            this = f"{eli.removesuffix('/oj')}/anx/oj" if eli and len(annexes) == 1 else ""
        w = etree.SubElement(ident, A + "FRBRWork")
        etree.SubElement(w, A + "FRBRthis", value=this)
        etree.SubElement(w, A + "FRBRuri", value=work)
        for name, d in (("adoption", md.adoption_date), ("publication", md.publication_date)):
            if d:
                fd = etree.SubElement(w, A + "FRBRdate", date=d, name=name, eId=name)
                fd.set(XID, g.f.reg(name))
        for c in authors or [""]:
            etree.SubElement(w, A + "FRBRauthor", href=("#" + g.ref(c, "TLCOrganization", href=AUTH + f"corporate-body/{c}", showAs=labels[c])) if c else "")  # fmt: skip
        etree.SubElement(w, A + "FRBRcountry", value="EU")
        if annex_no is None:
            etree.SubElement(w, A + "FRBRsubtype", value=rtype)
        etree.SubElement(w, A + "FRBRnumber", value=md.document_number)
        if eli:
            etree.SubElement(w, A + "FRBRnumber", value=f"eli/{rtype.lower()}/{year}/{int(no)}" + ("/anx" if annex_no is not None else ""),
                             refersTo="#" + g.ref("ELI", "TLCReference", name="identifier", href=AUTH + "document-identifier-format/ELI", showAs=""))  # fmt: skip
        etree.SubElement(w, A + "FRBRprescriptive", value="true")
        ex = etree.SubElement(ident, A + "FRBRExpression")
        etree.SubElement(ex, A + "FRBRthis", value=f"{this}/{LANG[2]}" if this else "")
        etree.SubElement(ex, A + "FRBRuri", value=f"{work}/{LANG[2]}" if work else "")
        etree.SubElement(ex, A + "FRBRdate", date=PLACEHOLDER_DATE, name="")
        etree.SubElement(ex, A + "FRBRauthor", href="")
        lang = etree.SubElement(ex, A + "FRBRlanguage", language=LANG[0], refersTo="~" + g.ref(LANG[1], "TLCReference", name="language", href=AUTH + f"language/{LANG[1]}", showAs=LANG[0]))  # fmt: skip
        lang.set(XID, g.f.reg("FRBRlanguage"))
        mf = etree.SubElement(ident, A + "FRBRManifestation")
        etree.SubElement(mf, A + "FRBRthis", value=f"{this}/{LANG[2]}/akn4eu" if this else "")
        etree.SubElement(mf, A + "FRBRuri", value=f"{work}/{LANG[2]}/akn4eu" if work else "")
        etree.SubElement(mf, A + "FRBRdate", date=retrieval_date, name="conversion")
        etree.SubElement(mf, A + "FRBRauthor", href="#ODOS")
        pres = etree.SubElement(mf, A + "preservation", nsmap={"akn4eu": AKN4EU_NS})
        etree.SubElement(pres, f"{{{AKN4EU_NS}}}akn4euVersion", value=AKN4EU_VERSION)
        etree.SubElement(pres, f"{{{AKN4EU_NS}}}akn4euDocumentation", href=AKN4EU_DOCUMENTATION)
        if md.publication_date and md.publication_reference:
            show = ", ".join(x for x in (f"{md.publication_journal or ''} {md.publication_reference}".strip(), md.publication_date_text) if x)  # fmt: skip
            etree.SubElement(meta, A + "publication", date=md.publication_date, number=md.publication_reference,
                             showAs=show, name=md.publication_journal or "Official Journal of the European Union")  # fmt: skip

    def references(meta, doc_type: str, show: str) -> None:
        g.ref(doc_type, "TLCReference", name="docType", href=AUTH + f"resource-type/{doc_type}", showAs=show)
        g.ref("EU", "TLCReference", name="legalActDomain", href=AUTH + "dataset/legal-act-domain/EU", showAs="EU")
        refs = etree.SubElement(meta, A + "references", source="~ODOS")
        for key, (tag, attrs) in g.f.refs.items():
            etree.SubElement(refs, A + tag, **attrs).set(XID, key)

    # ================================ the act ================================================================
    g.f = act_f = _File(act_file)
    root = etree.Element(A + "akomaNtoso", nsmap={None: AKN_NS})
    comment(root, "act")
    act = etree.SubElement(root, A + "act", name=rtype)
    meta = etree.SubElement(act, A + "meta")
    identification(meta, None)

    # ---- coverPage (OJ section headings printed above the title) and preface -------------------------------------
    front = [e for e in tops if e.region == "front"]
    t_idx = next((i for i, e in enumerate(front) if e.type == T.DOC_TITLE), None)
    if t_idx:
        cover = g.node(act, "coverPage", "coverPage")
        c = g.node(cover, "container", "coverPage__ojSection", name="ojSectionHeadings")
        for e in front[:t_idx]:
            g.trace(e, "p")
            g.own_p(c, e, f"{c.get(XID)}__p")
            g.notes_of(e)
        g.warnings.append({"code": "OJ_SECTION_HEADINGS_IN_COVERPAGE", "detail": "OJ section headings printed above the title kept in coverPage/container[@name='ojSectionHeadings'] (ODOS name)"})  # fmt: skip
    rest = front[t_idx:] if t_idx is not None else front
    if rest:
        pre = g.node(act, "preface", "preface")
        lt = lp = None
        for e in rest:
            eea = e.original_text.strip() == "(Text von Bedeutung für den EWR)"
            # long title: the title, then (until the EEA notice) the adoption date and the subject
            if e.type == T.DOC_TITLE or (lt is not None and not eea and not pre.findall(A + "container")):
                if lt is None:
                    lt = g.node(pre, "longTitle", "preface__longTitle")
                    g.eid(lt, "tit_1")
                    lp = g.node(lt, "p", "preface__longTitle__p")
                tr = g.trace(e, "p")
                if len(lp):
                    lp[-1].tail = " "
                if e.type == T.DOC_TITLE:
                    dt = g.text(lp, "docType", "", "preface__docType", e, refersTo="#" + g.ref(rtype, "TLCReference"))
                    m = TITLE.match(e.content_text)
                    if m and m.group("no") == md.document_number:
                        dt.text = m.group("type") + " "
                        dn = g.node(dt, "docNumber", "preface__docNumber")
                        dn.text = "("
                        dom = g.node(dn, "inline", "preface__docNumber__domain", name="legalActDomain", refersTo="~EU")
                        dom.text = m.group("dom")
                        dom.tail = ") " + m.group("no")
                        dn.tail = m.group("rest") or ""
                    else:
                        dt.text = e.content_text
                        g.warnings.append({"code": "TITLE_NOT_SEGMENTED", "model_id": e.id})
                    tr["text_ids"].append(dt.get(XID))
                elif md.adoption_date and german_date(e.content_text) == md.adoption_date:
                    d = g.text(lp, "date", e.content_text, "preface__date", e, date=md.adoption_date)
                    tr["text_ids"].append(d.get(XID))
                else:
                    d = g.text(lp, "docPurpose", e.content_text, "preface__docPurpose", e)
                    tr["text_ids"].append(d.get(XID))
            elif eea:
                c = g.node(pre, "container", "preface__eeaRelevance", name="eeaRelevance")
                g.trace(e, "p")
                g.own_p(c, e, f"{c.get(XID)}__p")
            else:
                c = g.node(pre, "container", f"preface__container_{len(pre) + 1}", name="unclassified")
                g.trace(e, "p")
                g.own_p(c, e, f"{c.get(XID)}__p")
                g.warnings.append({"code": "FRONT_ITEM_UNCLASSIFIED", "model_id": e.id})
            g.notes_of(e)

    # ---- preamble --------------------------------------------------------------------------------------------
    pre_el = next((e for e in tops if e.type == T.PREAMBLE), None)
    if pre_el is not None:
        pa = g.node(act, "preamble", "preamble")
        g.eid(pa, "pbl_1")
        g.trace(pre_el, "preamble", pa)["role"] = "container_shell"
        cits = recs = None
        for e in g.children(pre_el):
            if e.type in (T.PREAMBLE_FORMULA, T.ENACTING_FORMULA):
                name = "actingEntity" if e.type == T.PREAMBLE_FORMULA else "enactingFormula"
                f = g.node(pa, "formula", f"preamble__{name}", name=name)
                g.trace(e, "formula", f)
                g.own_p(f, e, f"{f.get(XID)}__p")
            elif e.type == T.CITATION:
                if cits is None:
                    cits = g.node(pa, "citations", "preamble__citations")
                c = g.node(cits, "citation", f"cit_{len(cits) + 1}")
                g.eid(c, f"cit_{len(cits)}")
                g.trace(e, "citation", c)
                g.own_p(c, e, f"{c.get(XID)}__p")
            elif e.type in (T.RECITALS_INTRO, T.RECITAL):
                if recs is None:
                    recs = g.node(pa, "recitals", "preamble__recitals")
                if e.type == T.RECITALS_INTRO:
                    intro = g.node(recs, "intro", "preamble__recitals__intro")
                    g.trace(e, "intro", intro)
                    g.own_p(intro, e, f"{intro.get(XID)}__p")
                else:
                    r = g.node(recs, "recital", f"rct_{e.number or len(recs)}")
                    g.eid(r, f"rct_{e.number or len(recs)}")
                    tr = g.trace(e, "recital", r)
                    g.num_heading(r, e, r.get(XID), tr)
                    g.own_p(r, e, f"{r.get(XID)}__p")
                    for k in g.children(e):
                        if k.type in BLOCKS:
                            g.block(r, k, r.get(XID))
                        elif k.type not in NOTES:
                            g.skip(k, f"no mapping for {k.type.value} inside a recital")
            else:
                c = g.node(pa, "container", f"preamble__container_{len(pa) + 1}", name="unclassified")
                g.trace(e, "p", c)
                g.own_p(c, e, f"{c.get(XID)}__p")
                g.warnings.append({"code": "PREAMBLE_ITEM_UNCLASSIFIED", "model_id": e.id})
            g.notes_of(e)

    # ---- body --------------------------------------------------------------------------------------------------
    body = g.node(act, "body", "body")
    g.eid(body, "ent_1")
    for e in tops:
        if e.type == T.ARTICLE:
            g.article(e, body)
        elif e.type in CONTAINERS:
            g.container(e, body, None)
        elif e.region == "body":
            g.skip(e, f"top-level {e.type.value} outside chapters")

    # ---- conclusions (the binding clause goes to body/clause, as in the samples) --------------------------------
    con = next((e for e in tops if e.type == T.CONCLUSIONS), None)
    if con is not None:
        kids = g.children(con)
        cn = None
        for e in kids:
            if e.type == T.FINAL_FORMULA and BINDING_CLAUSE.match(e.content_text) and cn is None:
                cl = g.node(body, "clause", "body__clause")
                g.trace(e, "clause", cl)
                g.own_p(g.node(cl, "content", "body__clause__content"), e, "body__clause__p")
                g.notes_of(e)
                continue
            if cn is None:
                cn = g.node(act, "conclusions", "conclusions")
                g.eid(cn, "fnp_1")
                g.trace(con, "conclusions", cn)["role"] = "container_shell"
            m = DONE_AT.match(e.content_text) if e.type == T.FINAL_FORMULA else None
            sig, from_table = signatories(e)
            if m:
                p = g.text(cn, "p", m.group(1), "conclusions__doneAt", e)
                g.trace(e, "p", p, text_ids=[p.get(XID)])
                place = PLACES.get(m.group(2))
                loc = g.node(p, "location", "conclusions__doneAt__location", refersTo=("#" + g.ref(place, "TLCLocation", href=AUTH + f"place/{place}", showAs=m.group(2))) if place else None)  # fmt: skip
                loc.text, loc.tail = m.group(2), m.group(3)
                iso = german_date(m.group(4))
                dt = g.node(p, "date", "conclusions__doneAt__date", date=iso) if iso else None
                if dt is not None:
                    dt.text, dt.tail = m.group(4), m.group(5)
                else:
                    loc.tail = m.group(3) + m.group(4) + m.group(5)
            elif sig:
                tr = g.trace(e, "signature")
                cols = []  # per signatory: the organization, role, person nodes
                for i, (org, role, person) in enumerate(sig, start=1):
                    b = g.node(cn, "block", f"conclusions__signatory_{i}", name="signatory")
                    s = g.node(b, "signature", f"{b.get(XID)}__signature")
                    if not from_table:
                        tr["text_ids"].append(s.get(XID))  # signature has mixed content; block gets indented by pretty printing
                    code = next((c for c, rx, _ in CORPORATE if rx.search(org)), None)
                    o = g.node(s, "organization", f"{s.get(XID)}__organization", refersTo=("#" + g.ref(code, "TLCOrganization", href=AUTH + f"corporate-body/{code}", showAs=labels[code])) if code else None)  # fmt: skip
                    r = g.node(s, "role", f"{s.get(XID)}__role", refersTo="#" + g.ref("PRESID", "TLCRole", href=AUTH + "role/PRESID", showAs="Präsident"))  # fmt: skip
                    pe = g.node(s, "person", f"{s.get(XID)}__person", refersTo="")
                    o.text, o.tail, r.text, r.tail, pe.text = org, " ", role, " ", person
                    cols.append([o, r, pe])
                if from_table:  # the table's cells, row by row, are the organization/role/person texts column by column
                    tr["cell_ids"] = [cols[c][r].get(XID) for r in range(3) for c in range(len(cols))]
                g.texts.setdefault(e.id, []).extend(cn.findall(f"{A}block/{A}signature")[-len(sig) :])
            elif e.table is not None:
                g.block(cn, e, f"conclusions__{len(cn) + 1}")
                g.warnings.append({"code": "SIGNATURE_NOT_STRUCTURED", "model_id": e.id, "detail": "signature block kept as a table"})  # fmt: skip
            else:
                p = g.text(cn, "p", e.content_text, f"conclusions__p_{len(cn) + 1}", e)
                g.trace(e, "p", p, text_ids=[p.get(XID)])
                if e.type == T.TEXT:
                    g.warnings.append({"code": "SIGNATURE_NOT_STRUCTURED", "model_id": e.id})
            g.notes_of(e)

    # ---- annexes: separate doc name="ANNEX" files ------------------------------------------------------------------
    annex_roots: list[tuple[str, etree._Element]] = []
    if annexes:
        atts = g.node(act, "attachments")  # attachments takes no xml:id (schema)
        for e in annexes:
            n = e.id.rsplit("-", 1)[-1]
            name = f"ANNEX-{slug}_anx_{n}-{LANG[0]}.xml"
            at = g.node(atts, "attachment", f"attachments__attachment_{n}")
            g.node(at, "documentRef", f"{at.get(XID)}__documentRef", href=name, showAs=e.marker or "ANNEX")
            g.f = _File(name)
            aroot = etree.Element(A + "akomaNtoso", nsmap={None: AKN_NS})
            comment(aroot, f"annex {e.marker or n}")
            doc = etree.SubElement(aroot, A + "doc", name="ANNEX")
            dmeta = etree.SubElement(doc, A + "meta")
            identification(dmeta, int(n) if n.isdigit() else 0)
            main = g.node(doc, "mainBody", "mainBody")
            anx = g.node(main, "annex", "anx")
            tr = g.trace(e, "annex", anx)
            g.num_heading(anx, e, "anx", tr)
            g.notes_of(e)
            g.hier_kids(anx, "anx", e, ("anx", "par"))
            g.fill_ids(doc, "")
            references(dmeta, "ANNEX", "Anhang")
            annex_roots.append((name, aroot))
            g.f = act_f

    g.fill_ids(act, "")
    references(meta, rtype, md.document_type)
    files[act_file] = root
    for name, r in annex_roots:
        files[name] = r

    # ---- accounting --------------------------------------------------------------------------------------------
    included = list(g.order)
    inc = set(included)
    excluded: dict[str, list[str]] = {"document_root": [], "page_furniture": [e.id for e in model.furniture], "unmapped": []}  # fmt: skip
    for e in model.elements:
        if e.id not in inc:
            (excluded["document_root"] if e.type == T.DOCUMENT else excluded["unmapped"]).append(e.id)
    for u in g.unmapped:
        if u["model_id"] not in excluded["unmapped"]:
            excluded["unmapped"].append(u["model_id"])
    for mw in model.warnings:
        if mw.element_id in inc:
            g.warnings.append({"code": "MODEL_WARNING", "model_id": mw.element_id, "model_code": mw.code, "message": mw.message})  # fmt: skip

    out = {k: etree.tostring(v.getroottree(), pretty_print=True, encoding="UTF-8", xml_declaration=True) for k, v in files.items()}  # fmt: skip
    return Akn4EuResult(
        files=out, act_file=act_file, entries=[g.entries[i] for i in included], included_ids=included,
        excluded=excluded, unmapped=g.unmapped, warnings=g.warnings,
        identifiers={"eli": eli, "eli_source": "supplied by caller, checked against the printed type and number" if eli else None,
                     "resource_type": rtype, "authors": authors, "language": LANG[1], "akn4eu_version": AKN4EU_VERSION},
        scope={"complete": True, "profile": "akn4eu", "articles": len(model.of_type(T.ARTICLE)),
               "recitals": len(model.of_type(T.RECITAL)), "annexes": len(annexes), "retrieval_date": retrieval_date},
    )  # fmt: skip
