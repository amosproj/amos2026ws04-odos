"""Akoma Ntoso generator for EU legislation (profile ``eu_legislation``; validated against AKN 3.1).

Maps the EU Internal Document Model to an ``<act name="regulation">`` (see Documentation/akn-eu-mapping.md).
Reuses the German generator's helpers (eIds, verbatim text nodes, ``odos:src`` marks, traceability,
tables, notes) but none of its German-law mapping. Every element is either written to the XML or
listed as excluded/unmapped; text is written verbatim from the model.
"""

from __future__ import annotations

import re

from lxml import etree

from odos.akn.generator import A, NSMAP, O, AknWriter, GenerationResult, TraceEntry
from odos.document_model import DocumentModel, Element, ElementType as T

EU_HIER: dict[T, tuple[str, str]] = {
    T.CHAPTER: ("chapter", "chp"),
    T.SECTION: ("section", "sec"),
    T.ARTICLE: ("article", "art"),
    T.ARTICLE_PARAGRAPH: ("paragraph", "para"),
    T.NUMBERED_POINT: ("point", "point"),
    T.POINT: ("point", "point"),
    T.SUBPOINT: ("point", "point"),
    T.ANNEX_PART: ("part", "part"),
    T.ANNEX_HEADING: ("level", "lvl"),
}
HEADED = (T.CHAPTER, T.SECTION, T.ARTICLE, T.ANNEX_PART, T.ANNEX_HEADING)  # num + heading, no own text
BLOCKS = (T.TEXT, T.TABLE, T.UNMARKED_LIST_ITEM, T.UNRECOGNIZED)
NOTES = (T.FOOTNOTE, T.FOOTNOTE_HEADING)
SUBTYPES = {"VERORDNUNG": "regulation", "DURCHFÜHRUNGSVERORDNUNG": "regulation", "DELEGIERTE VERORDNUNG": "regulation",
            "RICHTLINIE": "directive", "BESCHLUSS": "decision"}  # fmt: skip


def local_name(el: Element) -> str:
    """eId part from the stable model id: 'run2-pt-a' -> 'point_a-run2', 'h-1.2' -> 'lvl_1.2'."""
    last = el.id.rsplit("/", 1)[-1]
    run = ""
    if m := re.match(r"^run(\d+)-(.*)$", last):
        run, last = f"-run{m.group(1)}", m.group(2)
    slug, _, num = last.partition("-")
    prefix = EU_HIER[el.type][1] if el.type in EU_HIER else slug
    return f"{prefix}_{num.lower()}{run}" if num else f"{prefix}{run}"


class _EuGen(AknWriter):
    def _mark(self, node, el: Element, tag: str | None = None) -> None:
        super()._mark(node, el, tag)
        if el.source_spans:  # segment of a split Docling item: exact character range(s) in that item
            node.set(O + "span", " ".join(f"{s.ref}@{s.start}-{s.end}" for s in el.source_spans))

    def reg(self, eid: str) -> str:
        return self._reg(eid)

    def trace(self, el: Element, akn: str | None, role: str = "content", **ids) -> TraceEntry:
        e = super().trace(el, akn, role, **ids)
        e.source_spans = [s.model_dump() for s in el.source_spans]
        return e

    def note_or_skip(self, k: Element, anchor_eid: str) -> bool:
        if k.type in NOTES:
            self.loose_notes.append((k, anchor_eid))
            return True
        return False

    # -- blocks ------------------------------------------------------------------------------------------
    def eu_block(self, parent, b: Element, base: str) -> None:
        """TEXT/TABLE -> p/table; footnotes hanging under the block are routed to meta/notes."""
        if b.type == T.UNRECOGNIZED:
            self.warnings.append({"code": "UNRECOGNIZED_AS_P", "model_id": b.id})
        self.block(parent, b, base)
        anchor = self.entries[b.id].eId
        for k in self.children(b):
            if not self.note_or_skip(k, anchor):
                self.skip(k, f"no mapping for {k.type.value} inside {b.type.value}")

    # -- hierarchical units ------------------------------------------------------------------------------
    def unit(self, el: Element, parent_node, parent_eid: str | None) -> None:
        tag, _ = EU_HIER[el.type]
        eid = self.reg(f"{parent_eid}__{local_name(el)}" if parent_eid else local_name(el))
        node = etree.SubElement(parent_node, A + tag, eId=eid)
        self._mark(node, el)
        ids = {"eId": eid, "num_eId": self._num(node, el, eid)}
        if el.type in HEADED and el.title:
            ids["heading_eId"] = self.reg(eid + "__heading")
            self.text(node, "heading", el.title, ids["heading_eId"], el)
        self.trace(el, tag, **ids)
        own = "" if el.type in HEADED else el.content_text
        self.children_of(el, node, eid, own)

    def children_of(self, el: Element, node, eid: str, own: str) -> None:
        kids = [k for k in self.children(el) if not self.note_or_skip(k, eid)]
        for k in kids:
            if k.type not in EU_HIER and k.type not in BLOCKS:
                self.skip(k, f"no mapping for {k.type.value} inside {el.type.value}")
        kids = [k for k in kids if k.type in EU_HIER or k.type in BLOCKS]
        subs = [i for i, k in enumerate(kids) if k.type in EU_HIER]
        if not subs:  # <content> with own text and blocks
            if own or kids:
                content = etree.SubElement(node, A + "content", eId=self.reg(eid + "__content"))
                self._own_p(content, el, eid + "__content", own)
                for k in kids:
                    self.eu_block(content, k, eid + "__content")
            return
        first, last = subs[0], subs[-1]
        if own or first > 0:  # own text and leading blocks introduce the sub-units
            intro = etree.SubElement(node, A + "intro", eId=self.reg(eid + "__intro"))
            self._own_p(intro, el, eid + "__intro", own)
            for k in kids[:first]:
                self.eu_block(intro, k, eid + "__intro")
        i = first
        while i <= last:
            k = kids[i]
            if k.type in EU_HIER:
                self.unit(k, node, eid)
                i += 1
                continue
            # unnumbered text between numbered units: keep it in place
            run = []
            while i <= last and kids[i].type not in EU_HIER:
                run.append(kids[i])
                i += 1
            hc = etree.SubElement(node, A + "hcontainer", eId=self.reg(f"{eid}__hcontainer_{i}"), name="unnumberedParagraph")
            content = etree.SubElement(hc, A + "content", eId=self.reg(hc.get("eId") + "__content"))
            for b in run:
                self.eu_block(content, b, hc.get("eId") + "__content")
            self.warnings.append({"code": "TEXT_BETWEEN_UNITS", "model_id": el.id, "detail": f"{len(run)} unnumbered block(s) kept as hcontainer"})  # fmt: skip
        if last < len(kids) - 1:
            wrap = etree.SubElement(node, A + "wrapUp", eId=self.reg(eid + "__wrapup"))
            for k in kids[last + 1 :]:
                self.eu_block(wrap, k, eid + "__wrapup")

    # -- p with an optional inline wrapper (docTitle, docDate) -------------------------------------------
    def para(self, parent, el: Element, eid: str, inline: str | None = None, **attrs) -> None:
        p = etree.SubElement(parent, A + "p", eId=self.reg(eid))
        if inline is None:
            p.text = el.content_text
            self._mark(p, el)
            text_eid = p.get("eId")
        else:
            node = self.text(p, inline, el.content_text, self.reg(eid + "__" + inline.lower()), el)
            for k, v in attrs.items():
                node.set(k, v)
            text_eid = node.get("eId")
        self.trace(el, inline or "p", eId=text_eid, text_eId=text_eid)
        e = self.entries[el.id]
        e.content_text = el.content_text


def generate_eu_akn(model: DocumentModel, retrieval_date: str) -> GenerationResult:
    if model.profile != "eu_legislation":
        raise ValueError("generate_eu_akn needs a model parsed with the eu_legislation profile")
    md = model.metadata
    if not (md.adoption_date and md.document_number and md.document_type):
        raise ValueError("EU metadata incomplete (adoption date, type or number missing in the source); refusing to invent them")  # fmt: skip
    g = _EuGen(model)
    by_id = model.by_id()
    root = etree.Element(A + "akomaNtoso", nsmap=NSMAP)
    root.addprevious(etree.Comment(
        f" PROTOTYPE CONVERSION: generated by ODOS from Docling output of {md.title}. Text is the extracted text, "
        "not the authentic Official Journal edition. Work/Expression URIs are ODOS-derived, not official identifiers. "
    ))  # fmt: skip
    subtype = SUBTYPES.get(md.document_type, md.document_type.lower())
    work = f"/akn/eu/act/{subtype}/{md.adoption_date}/{md.document_number.replace('/', '-')}"
    expr_date = md.publication_date or retrieval_date
    expr = f"{work}/deu@{expr_date}"
    act = etree.SubElement(root, A + "act", name=subtype, contains="originalVersion")

    def frbr(parent, suffix: str = "", p: str = "") -> None:
        # p: eId prefix of the TLC references; eIds must be unique across the whole act incl. attachments
        ident = etree.SubElement(parent, A + "identification", source=f"#{p}odos")
        w = etree.SubElement(ident, A + "FRBRWork")
        etree.SubElement(w, A + "FRBRthis", value=f"{work}/!{suffix or 'main'}")
        etree.SubElement(w, A + "FRBRuri", value=work)
        etree.SubElement(w, A + "FRBRalias", value=md.title, name="title")
        etree.SubElement(w, A + "FRBRdate", date=md.adoption_date, name="adoption")
        etree.SubElement(w, A + "FRBRauthor", href=f"#{p}issuingBodies")
        etree.SubElement(w, A + "FRBRcountry", value="eu")
        etree.SubElement(w, A + "FRBRsubtype", value=subtype)
        etree.SubElement(w, A + "FRBRnumber", value=md.document_number)
        e = etree.SubElement(ident, A + "FRBRExpression")
        etree.SubElement(e, A + "FRBRthis", value=f"{expr}/!{suffix or 'main'}")
        etree.SubElement(e, A + "FRBRuri", value=expr)
        etree.SubElement(e, A + "FRBRdate", date=expr_date, name="publication" if md.publication_date else "Abruf")
        etree.SubElement(e, A + "FRBRauthor", href=f"#{p}unspecified")
        etree.SubElement(e, A + "FRBRlanguage", language="deu")
        mf = etree.SubElement(ident, A + "FRBRManifestation")
        etree.SubElement(mf, A + "FRBRthis", value=f"{expr}/!{suffix or 'main'}.xml")
        etree.SubElement(mf, A + "FRBRuri", value=f"{expr}.akn")
        etree.SubElement(mf, A + "FRBRdate", date=retrieval_date, name="Konvertierung")
        etree.SubElement(mf, A + "FRBRauthor", href=f"#{p}odos")

    def references(parent, p: str = "") -> None:
        refs = etree.SubElement(parent, A + "references", source=f"#{p}odos")
        etree.SubElement(refs, A + "TLCOrganization", eId=f"{p}odos", href="/ontology/organization/odos", showAs="ODOS prototype converter (AMOS 2026)")  # fmt: skip
        etree.SubElement(refs, A + "TLCOrganization", eId=f"{p}unspecified", href="/ontology/organization/unspecified", showAs="Not determined from the source")  # fmt: skip
        etree.SubElement(refs, A + "TLCOrganization", eId=f"{p}issuingBodies", href="/ontology/organization/eu/issuingBodies", showAs=md.issuing_bodies or "")  # fmt: skip

    meta = etree.SubElement(act, A + "meta")
    frbr(meta)
    if md.publication_date and md.publication_reference:
        etree.SubElement(meta, A + "publication", date=md.publication_date, name="OJ",
                         showAs=md.publication_journal or "", number=md.publication_reference)  # fmt: skip
    references(meta)
    notes_parent = etree.SubElement(meta, A + "notes", source="#odos")
    prop = etree.SubElement(meta, A + "proprietary", source="#odos")
    etree.SubElement(prop, O + "profile", name="eu_legislation")
    etree.SubElement(prop, O + "identifiers", derived="FRBRuri FRBRthis FRBRsubtype",
                     note="URIs and subtype are derived by ODOS from the printed type, number and dates; not official (no ELI)")  # fmt: skip
    etree.SubElement(prop, O + "source", file=model.source.filename or "", **{"docling-json-sha256": model.source.docling_json_sha256})  # fmt: skip

    root_el = by_id[model.root_id]
    tops = [by_id[c] for c in root_el.children_ids]

    # ---- preface: title block -----------------------------------------------------------------------
    front = [e for e in tops if e.region == "front"]
    if front:
        pre = etree.SubElement(act, A + "preface", eId="preface")
        g.eids.add("preface")
        for i, e in enumerate(front, start=1):
            if e.type == T.DOC_TITLE:
                g.para(pre, e, f"preface__p_{i}", "docTitle")
            elif md.adoption_date_text and e.original_text.strip() == md.adoption_date_text:
                g.para(pre, e, f"preface__p_{i}", "docDate", date=md.adoption_date)
            else:
                g.para(pre, e, f"preface__p_{i}")
            for k in g.children(e):
                if not g.note_or_skip(k, g.entries[e.id].eId):
                    g.skip(k, "child of front matter")

    # ---- preamble ----------------------------------------------------------------------------------------
    pre_el = next((e for e in tops if e.type == T.PREAMBLE), None)
    if pre_el is not None:
        pa = etree.SubElement(act, A + "preamble", eId=g.reg("preamble"))
        g.trace(pre_el, "preamble", "container_shell", eId="preamble")
        cits = recs = None
        for e in g.children(pre_el):
            if e.type in (T.PREAMBLE_FORMULA, T.ENACTING_FORMULA):
                name = "openingFormula" if e.type == T.PREAMBLE_FORMULA else "enactingFormula"
                f = etree.SubElement(pa, A + "formula", eId=g.reg(f"preamble__formula_{name}"), name=name)
                g.para(f, e, f"{f.get('eId')}__p_1")
            elif e.type == T.CITATION:
                if cits is None:
                    cits = etree.SubElement(pa, A + "citations", eId=g.reg("preamble__cits"))
                c = etree.SubElement(cits, A + "citation", eId=g.reg(f"preamble__cits__{local_name(e).replace('citation', 'cit')}"))
                g.para(c, e, f"{c.get('eId')}__p_1")
                _notes_of(g, e)
            elif e.type in (T.RECITALS_INTRO, T.RECITAL):
                if recs is None:
                    recs = etree.SubElement(pa, A + "recitals", eId=g.reg("preamble__recs"))
                if e.type == T.RECITALS_INTRO:
                    intro = etree.SubElement(recs, A + "intro", eId=g.reg("preamble__recs__intro"))
                    g.para(intro, e, "preamble__recs__intro__p_1")
                    continue
                r = etree.SubElement(recs, A + "recital", eId=g.reg(f"preamble__recs__{local_name(e).replace('rec_', 'rec_')}"))
                g._mark(r, e)
                num = g._num(r, e, r.get("eId"))
                p = g.text(r, "p", e.content_text, g.reg(r.get("eId") + "__p_1"), e)
                g.trace(e, "recital", eId=r.get("eId"), num_eId=num, text_eId=p.get("eId"))
                for k in g.children(e):
                    if not g.note_or_skip(k, r.get("eId")):
                        if k.type in BLOCKS:
                            g.eu_block(r, k, r.get("eId"))
                        else:
                            g.skip(k, f"no mapping for {k.type.value} inside a recital")
            else:
                c = etree.SubElement(pa, A + "container", eId=g.reg(f"preamble__container_{len(pa)}"), name="unclassified")
                g.para(c, e, f"{c.get('eId')}__p_1")
                g.warnings.append({"code": "PREAMBLE_ITEM_UNCLASSIFIED", "model_id": e.id})

    # ---- body -----------------------------------------------------------------------------------------------
    body = etree.SubElement(act, A + "body", eId=g.reg("body"))
    for e in tops:
        if e.type in EU_HIER:
            g.unit(e, body, None)
        elif e.region == "body":
            g.skip(e, f"top-level {e.type.value} outside chapters")

    # ---- conclusions ------------------------------------------------------------------------------------------
    con = next((e for e in tops if e.type == T.CONCLUSIONS), None)
    if con is not None:
        cn = etree.SubElement(act, A + "conclusions", eId=g.reg("conclusions"))
        g.trace(con, "conclusions", "container_shell", eId="conclusions")
        for e in g.children(con):
            if e.type == T.FINAL_FORMULA:
                name = "doneAt" if e.original_text.startswith("Geschehen zu") else "finalFormula"
                f = etree.SubElement(cn, A + "formula", eId=g.reg(f"conclusions__formula_{name}"), name=name)
                g.para(f, e, f"{f.get('eId')}__p_1")
            elif e.type == T.SIGNATURE:
                c = etree.SubElement(cn, A + "container", eId=g.reg("conclusions__signatures"), name="signatures")
                g.table(c, e, c.get("eId"))
            else:
                c = etree.SubElement(cn, A + "container", eId=g.reg(f"conclusions__container_{len(cn)}"), name="unclassified")
                g.eu_block(c, e, c.get("eId"))

    # ---- annexes as attachments -------------------------------------------------------------------------------------
    annexes = [e for e in tops if e.type == T.ANNEX]
    if annexes:
        atts = etree.SubElement(act, A + "attachments")
        for e in annexes:
            n = e.id.rsplit("-", 1)[-1]
            aeid = g.reg(f"att_{n}")
            att = etree.SubElement(atts, A + "attachment", eId=aeid)
            g._mark(att, e)
            ids = {"eId": aeid, "num_eId": g._num(att, e, aeid)}
            if e.title:
                ids["heading_eId"] = g.reg(aeid + "__heading")
                g.text(att, "heading", e.title, ids["heading_eId"], e)
            g.trace(e, "attachment", **ids)
            doc = etree.SubElement(att, A + "doc", name="annex")
            dmeta = etree.SubElement(doc, A + "meta")
            frbr(dmeta, f"annex_{n}", p=f"{aeid}__")
            references(dmeta, p=f"{aeid}__")
            main = etree.SubElement(doc, A + "mainBody", eId=g.reg(f"{aeid}__mainbody"))
            for k in g.children(e):
                if g.note_or_skip(k, aeid):
                    continue
                if k.type in EU_HIER:
                    g.unit(k, main, aeid)
                elif k.type in BLOCKS:
                    g.eu_block(main, k, f"{aeid}__mainbody")
                else:
                    g.skip(k, f"no mapping for {k.type.value} inside an annex")
            if len(main) == 0:  # mainBody needs content; an empty annex is reported, never padded with text
                g.warnings.append({"code": "EMPTY_ANNEX", "model_id": e.id})

    # ---- notes ---------------------------------------------------------------------------------------------------------
    for f, anchor in g.loose_notes:
        nid = g.reg(f"fn_{len(notes_parent) + 1}")
        note = etree.SubElement(notes_parent, A + "note", eId=nid)
        note.set(O + "anchor", anchor)
        if f.marker:
            note.set("marker", f.number or f.marker)
        pid = g.reg(f"{nid}__p_1")
        g.text(note, "p", f.content_text, pid, f)
        g.trace(f, "p", eId=pid, text_eId=pid)
    if len(notes_parent) == 0:
        meta.remove(notes_parent)

    # ---- accounting -------------------------------------------------------------------------------------------------------
    included = list(g.order)
    inc = set(included)
    excluded: dict[str, list[str]] = {"document_root": [], "page_furniture": [e.id for e in model.furniture], "unmapped": []}
    for e in model.elements:
        if e.id in inc:
            continue
        (excluded["document_root"] if e.type == T.DOCUMENT else excluded["unmapped"]).append(e.id)
    for u in g.unmapped:
        if u["model_id"] not in excluded["unmapped"]:
            excluded["unmapped"].append(u["model_id"])
    for mw in model.warnings:
        if mw.element_id in inc:
            g.warnings.append({"code": "MODEL_WARNING", "model_id": mw.element_id, "model_code": mw.code, "message": mw.message})  # fmt: skip

    xml = etree.tostring(root.getroottree(), pretty_print=True, encoding="UTF-8", xml_declaration=True)
    return GenerationResult(
        xml=xml, entries=[g.entries[i] for i in included], included_ids=included, excluded=excluded,
        unmapped=g.unmapped, warnings=g.warnings,
        excerpt={"complete": True, "scope": "whole-document", "profile": "eu_legislation",
                 "articles": len(model.of_type(T.ARTICLE)), "recitals": len(model.of_type(T.RECITAL)),
                 "annexes": len(annexes), "retrieval_date": retrieval_date},
    )  # fmt: skip


def _notes_of(g: _EuGen, e: Element) -> None:
    for k in g.children(e):
        if not g.note_or_skip(k, g.entries[e.id].eId):
            g.skip(k, f"no mapping for {k.type.value} inside {e.type.value}")
