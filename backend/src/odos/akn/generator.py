"""Akoma Ntoso generator (lxml) for the Internal Document Model (namespace akn/3.0, validated against AKN 3.1).

Only the structure the model actually contains is emitted. Text is copied
verbatim; metadata that the source does not provide is declared as
unspecified rather than invented.
"""

from __future__ import annotations

import re
from datetime import date

from lxml import etree
from pydantic import BaseModel, Field

from odos.akn.mapping import AKN_NS, CONTAINERS, HIERARCHY, ODOS_NS, SUBUNITS
from odos.document_model import DocumentModel, Element, ElementType as T

A = f"{{{AKN_NS}}}"
O = f"{{{ODOS_NS}}}"  # noqa: E741
NSMAP = {None: AKN_NS, "odos": ODOS_NS}
XML_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


class TraceEntry(BaseModel):
    model_id: str
    model_type: str
    akn_element: str | None
    eId: str | None = None  # structural node
    num_eId: str | None = None
    heading_eId: str | None = None
    text_eId: str | None = None  # node carrying the running text
    marker: str | None = None
    title: str | None = None
    content_text: str = ""
    original_text: str
    source_refs: list[str]
    docling_label: str | None
    pages: list[int]
    provenance: list[dict]
    uncertain: bool
    uncertainty_reasons: list[str]
    role: str = "content"  # content | container_shell | preface
    # partial-item provenance of hygiene segments (EU); omitted when empty, so German output is unchanged
    source_spans: list[dict] = Field(default_factory=list, exclude_if=lambda v: not v)
    # human review: which fields of this node were corrected (original_text above stays the source text)
    reviewed: dict | None = Field(default=None, exclude_if=lambda v: not v)


class GenerationResult(BaseModel):
    xml: bytes
    entries: list[TraceEntry]
    included_ids: list[str]
    excluded: dict[str, list[str]]
    unmapped: list[dict] = Field(default_factory=list)
    warnings: list[dict] = Field(default_factory=list)
    excerpt: dict


def _norm_num(number: str | None) -> str:
    return re.sub(r"[^0-9a-z]", "", (number or "").lower()) or "x"


class AknWriter:
    def __init__(self, model: DocumentModel):
        self.m = model
        self.by_id = model.by_id()
        self.entries: dict[str, TraceEntry] = {}
        self.order: list[str] = []
        self.eids: set[str] = set()
        self.unmapped: list[dict] = []
        self.warnings: list[dict] = []
        self.footnotes: list[tuple[Element, str]] = []  # (heading element, anchor eId)
        self.loose_notes: list[tuple[Element, str]] = []  # page footnotes without a "Fußnote" heading

    # -- helpers ---------------------------------------------------------
    def eid(self, parent: str | None, prefix: str, number: str | None = None) -> str:
        local = f"{prefix}_{_norm_num(number)}" if number is not None else prefix
        base = f"{parent}__{local}" if parent else local
        out, n = base, 2
        while out in self.eids:
            out = f"{base}-{n}"
            n += 1
        self.eids.add(out)
        return out

    def text(self, parent: etree._Element, tag: str, value: str, eid: str, el: Element) -> etree._Element:
        if XML_ILLEGAL.search(value):
            raise ValueError(f"{el.id}: text contains characters that are illegal in XML 1.0")
        node = etree.SubElement(parent, A + tag, eId=eid)
        node.text = value
        self._mark(node, el, tag)
        return node

    def _mark(self, node: etree._Element, el: Element, tag: str | None = None) -> None:
        if el.source_refs:
            node.set(O + "src", " ".join(el.source_refs))
        if el.uncertain:
            node.set(O + "uncertain", " ".join(el.uncertainty_reasons))
        if el.reviewed:  # human-corrected: this node's text is not verbatim from the source
            field = {"num": "marker", "heading": "title"}.get(tag or "", "content_text")
            if tag is None or field in el.reviewed.get("fields", {}):  # text nodes: only the corrected field
                node.set(O + "reviewed", " ".join(el.reviewed.get("corrections", [])))

    def trace(self, el: Element, akn: str | None, role: str = "content", **ids) -> TraceEntry:
        e = TraceEntry(
            model_id=el.id, model_type=el.type.value, akn_element=akn, marker=el.marker,
            title=el.title, content_text=el.content_text, original_text=el.original_text,
            source_refs=el.source_refs, docling_label=el.docling_label, pages=el.pages,
            provenance=[p.model_dump() for p in el.provenance], uncertain=el.uncertain,
            uncertainty_reasons=el.uncertainty_reasons, role=role, reviewed=el.reviewed, **ids,
        )  # fmt: skip
        self.entries[el.id] = e
        self.order.append(el.id)
        if el.uncertain:
            self.warnings.append({"code": "UNCERTAIN_ELEMENT_INCLUDED", "model_id": el.id, "reasons": el.uncertainty_reasons})  # fmt: skip
        return e

    def children(self, el: Element) -> list[Element]:
        return [self.by_id[c] for c in el.children_ids]

    def skip(self, el: Element, why: str) -> None:
        self.unmapped.append({"model_id": el.id, "type": el.type.value, "reason": why, "original_text": el.original_text[:120]})  # fmt: skip
        self.warnings.append({"code": "UNMAPPED_ELEMENT", "model_id": el.id, "reason": why})

    # -- hierarchy -------------------------------------------------------
    def shell(self, el: Element, parent_xml, parent_eid: str | None):
        """Teil/Kapitel/Abschnitt that only wraps the excerpted §: num + heading, no other content."""
        tag, prefix = HIERARCHY[el.type]
        eid = self.eid(parent_eid, prefix, el.number)
        node = etree.SubElement(parent_xml, A + tag, eId=eid)
        self._mark(node, el)
        ids = {"eId": eid, "num_eId": self._num(node, el, eid)}
        if el.title:
            ids["heading_eId"] = self._reg(eid + "__heading")
            self.text(node, "heading", el.title, ids["heading_eId"], el)
        self.trace(el, tag, "container_shell", **ids)
        return node, eid

    def container(self, el: Element, parent_xml, parent_eid: str | None, shell: bool) -> None:
        tag, prefix = HIERARCHY[el.type]
        eid = self.eid(parent_eid, prefix, el.number)
        node = etree.SubElement(parent_xml, A + tag, eId=eid)
        if tag == "hcontainer":
            node.set("name", prefix)
        self._mark(node, el)
        ids = {"eId": eid}
        ids["num_eId"] = self._num(node, el, eid)
        if el.title:
            ids["heading_eId"] = eid + "__heading"
            self.eids.add(ids["heading_eId"])
            self.text(node, "heading", el.title, ids["heading_eId"], el)
        self.trace(el, tag, "container_shell" if shell else "content", **ids)
        if el.type in CONTAINERS:
            for c in self.children(el):
                if c.type in HIERARCHY and (c.type in CONTAINERS or c.type == T.PARAGRAPH):
                    self.container(c, node, eid, shell=False)
                elif c.type in (T.FOOTNOTE_HEADING, T.FOOTNOTE):
                    self._note_kid(c, eid)
                else:
                    self.skip(c, f"unsupported child of {el.type.value}")
        else:  # PARAGRAPH (German §) -> article, ANLAGE -> hcontainer
            self.units(el, node, eid)

    def _num(self, node, el: Element, eid: str) -> str | None:
        if not el.marker:
            return None
        nid = eid + "__num"
        self.eids.add(nid)
        self.text(node, "num", el.marker, nid, el)
        return nid

    def units(self, el: Element, node, eid: str) -> None:
        """Children of an article/paragraph/point: sub-units, texts, tables, footnotes."""
        kids = self.children(el)
        sub = [c for c in kids if c.type in SUBUNITS]
        for k in kids:
            if k.type in (T.FOOTNOTE_HEADING, T.FOOTNOTE):
                self._note_kid(k, eid)
        blocks = [c for c in kids if c.type in (T.TEXT, T.TABLE, T.UNMARKED_LIST_ITEM)]
        other = [c for c in kids if c not in sub and c not in blocks and c.type not in (T.FOOTNOTE_HEADING, T.FOOTNOTE)]  # fmt: skip
        for c in other:
            self.skip(c, f"no mapping for {c.type.value} inside {el.type.value}")

        own = el.content_text if el.type not in (T.PARAGRAPH, T.ANLAGE) else ""
        order = [c for c in kids if c in sub or c in blocks]
        if not sub:
            # plain text: <content> with one <p> per text, tables as <table>
            if own or blocks:
                content = etree.SubElement(node, A + "content", eId=self._reg(eid + "__content"))
                self._own_p(content, el, eid + "__content", own)
                for b in blocks:
                    self.block(content, b, eid + "__content")
            return

        # runs of numbered sub-units, separated by text blocks
        lead: list[Element] = []  # text blocks before the first sub-unit (e.g. "Es bezeichnen die Begriffe:")
        runs: list[list[Element]] = []
        trailing: list[list[Element]] = []  # texts after each run
        for c in order:
            if c in sub:
                if not runs or trailing[-1]:
                    runs.append([])
                    trailing.append([])
                runs[-1].append(c)
            else:
                if not runs:
                    lead.append(c)
                    continue
                trailing[-1].append(c)

        if len(runs) == 1:
            self._list_body(node, eid, el, own, runs[0], trailing[0], lead)
        else:
            self.warnings.append({"code": "MULTI_RUN_LIST", "model_id": el.id, "detail": f"{len(runs)} numbered runs interrupted by text; text between runs is placed in wrapUp of the preceding list"})  # fmt: skip
            for i, (run, tail) in enumerate(zip(runs, trailing), start=1):
                lid = self.eid(eid, "list", str(i))
                lst = etree.SubElement(node, A + "list", eId=lid)
                self._list_body(lst, lid, el if i == 1 else None, own if i == 1 else "", run, tail, lead if i == 1 else [])

    def _note_kid(self, k: Element, anchor: str) -> None:
        (self.footnotes if k.type == T.FOOTNOTE_HEADING else self.loose_notes).append((k, anchor))

    def _reg(self, eid: str) -> str:
        out, n = eid, 2
        while out in self.eids:
            out = f"{eid}-{n}"
            n += 1
        self.eids.add(out)
        return out

    def _own_p(self, parent, el: Element | None, base: str, value: str) -> None:
        if not value or el is None:
            return
        pid = self._reg(base + "__p_1")
        self.text(parent, "p", value, pid, el)
        self.entries_text(el, pid)

    def entries_text(self, el: Element, pid: str) -> None:
        self.entries[el.id].text_eId = pid  # trace() always runs before the element's text is written

    def _list_body(self, parent, eid: str, owner: Element | None, own: str, run, tail, lead=()) -> None:
        if (own and owner is not None) or lead:
            intro = etree.SubElement(parent, A + "intro", eId=self._reg(eid + "__intro"))
            self._own_p(intro, owner, eid + "__intro", own)
            for b in lead:
                self.block(intro, b, eid + "__intro")
        for u in run:
            self.unit_point(u, parent, eid)
        if tail:
            wrap = etree.SubElement(parent, A + "wrapUp", eId=self._reg(eid + "__wrapup"))
            for b in tail:
                self.block(wrap, b, eid + "__wrapup")

    def unit_point(self, el: Element, parent, parent_eid: str) -> None:
        """Absatz -> paragraph, Nummer/Buchstabe -> point."""
        tag, prefix = HIERARCHY[el.type]
        eid = self.eid(parent_eid, prefix, el.number)
        node = etree.SubElement(parent, A + tag, eId=eid)
        self._mark(node, el)
        num_id = self._num(node, el, eid)
        self.trace(el, tag, eId=eid, num_eId=num_id)
        self.units(el, node, eid)

    def block(self, parent, b: Element, base: str) -> None:
        if b.type == T.TABLE:
            self.table(parent, b, base)
            return
        pid = self._reg(f"{base}__p_{len(parent.findall(A + 'p')) + 1}")
        self.text(parent, "p", b.content_text or b.original_text, pid, b)
        if b.type == T.UNMARKED_LIST_ITEM:
            self.warnings.append({"code": "UNMARKED_LIST_ITEM_AS_P", "model_id": b.id})
        self.trace(b, "p", eId=pid, text_eId=pid)

    def table(self, parent, b: Element, base: str) -> None:
        tid = self._reg(f"{base}__table_{len(parent.findall(A + 'table')) + 1}")
        t = etree.SubElement(parent, A + "table", eId=tid)
        self._mark(t, b)
        cells = []
        for r, row in enumerate(b.table.rows if b.table else [], start=1):
            tr = etree.SubElement(t, A + "tr", eId=self._reg(f"{tid}__tr_{r}"))
            for c, cell in enumerate(row, start=1):
                td = etree.SubElement(tr, A + "td", eId=self._reg(f"{tid}__tr_{r}__td_{c}"))
                if cell:
                    self.text(td, "p", cell, self._reg(f"{tid}__tr_{r}__td_{c}__p_1"), b)
                cells.append(cell)
        self.trace(b, "table", eId=tid)


def _date(dmy: str) -> str:
    d, m, y = (int(x) for x in dmy.split("."))
    return date(y, m, d).isoformat()


def generate_excerpt(
    model: DocumentModel, paragraph_numbers: list[str], retrieval_date: str, country: str = "de",
    undated_policy: str = "refuse",
) -> GenerationResult:
    """Build an Akoma Ntoso <act> containing only the listed § (plus the Teil/Kapitel/Abschnitt
    shells that contain them, with their num/heading)."""
    g = AknWriter(model)
    paragraphs = [e for e in model.of_type(T.PARAGRAPH) if e.number in set(paragraph_numbers)]
    missing = set(paragraph_numbers) - {p.number for p in paragraphs}
    if missing:
        raise ValueError(f"§ not found in model: {sorted(missing)}")
    paragraphs.sort(key=lambda e: model.elements.index(e))

    root = etree.Element(A + "akomaNtoso", nsmap=NSMAP)
    short = model.metadata.short_title or model.metadata.title or "unknown"
    full = len(paragraphs) == len(model.of_type(T.PARAGRAPH))
    if full:
        note = (f" PROTOTYPE CONVERSION: generated by ODOS from Docling output; contains all {len(paragraphs)} § of the body of "
                f"{short}. Front matter and table of contents are not converted. Not an authoritative text. ")  # fmt: skip
    else:
        note = (" EXCERPT: generated by ODOS from Docling output; contains only "
                + ", ".join(f"§ {p.number}" for p in paragraphs)
                + f" of the {short}, NOT the complete law. Not an authoritative text. ")  # fmt: skip
    root.addprevious(etree.Comment(note))
    meta = model.metadata
    slug = re.sub(r"[^a-z0-9]+", "-", short.lower()).strip("-") or "unknown"
    if meta.ausfertigungsdatum:
        work_date, work_date_name, uri_date, legal_date = _date(meta.ausfertigungsdatum), "Ausfertigung", None, True
        uri_date = work_date
    elif undated_policy == "processing_date":
        # No enactment date in the source and AKN requires a full xsd:date. Use the real processing date and
        # say so in the date's own name; the stated version (e.g. "Fassung November 2002") goes into FRBRalias.
        work_date, work_date_name, legal_date = retrieval_date, "ODOS-Verarbeitungsdatum (kein Rechtsdatum)", False
        uri_date = meta.version_year_month or retrieval_date[:4]
        g.warnings.append({"code": "WORK_DATE_NOT_LEGAL", "message": "The source states no Ausfertigungsdatum; FRBRWork/FRBRdate holds the processing date, labelled as such. No legal date was invented."})  # fmt: skip
    else:
        raise ValueError("model has no Ausfertigungsdatum; refusing to invent a Work date")
    slug = re.sub(r"[^a-z0-9]+", "-", short.lower()).strip("-") or "unknown"
    work_uri = f"/akn/{country}/act/{uri_date}/{slug}"
    act = etree.SubElement(root, A + "act", name=slug, contains="singleVersion")

    # ---- meta --------------------------------------------------------------
    m = etree.SubElement(act, A + "meta")
    ident = etree.SubElement(m, A + "identification", source="#odos")
    w = etree.SubElement(ident, A + "FRBRWork")
    etree.SubElement(w, A + "FRBRthis", value=work_uri + "/!main")
    etree.SubElement(w, A + "FRBRuri", value=work_uri)
    etree.SubElement(w, A + "FRBRalias", value=(short if full else f"{short} (excerpt: " + ", ".join(f"§ {p.number}" for p in paragraphs) + ")"), name="odos-excerpt")  # fmt: skip
    if meta.stated_version_text:
        etree.SubElement(w, A + "FRBRalias", value=meta.stated_version_text, name="stated-version")
    etree.SubElement(w, A + "FRBRdate", date=work_date, name=work_date_name)
    etree.SubElement(w, A + "FRBRauthor", href="#unspecified")
    etree.SubElement(w, A + "FRBRcountry", value=country)
    etree.SubElement(w, A + "FRBRname", value=short)
    ex = etree.SubElement(ident, A + "FRBRExpression")
    etree.SubElement(ex, A + "FRBRthis", value=f"{work_uri}/deu@/!main")
    etree.SubElement(ex, A + "FRBRuri", value=f"{work_uri}/deu@")
    etree.SubElement(ex, A + "FRBRdate", date=retrieval_date, name="Abruf")
    etree.SubElement(ex, A + "FRBRauthor", href="#unspecified")
    etree.SubElement(ex, A + "FRBRlanguage", language="deu")
    mf = etree.SubElement(ident, A + "FRBRManifestation")
    etree.SubElement(mf, A + "FRBRthis", value=f"{work_uri}/deu@/!main.xml")
    etree.SubElement(mf, A + "FRBRuri", value=f"{work_uri}/deu@.akn")
    etree.SubElement(mf, A + "FRBRdate", date=retrieval_date, name="Konvertierung")
    etree.SubElement(mf, A + "FRBRauthor", href="#odos")
    refs = etree.SubElement(m, A + "references", source="#odos")
    etree.SubElement(refs, A + "TLCOrganization", eId="odos", href="/ontology/organization/odos", showAs="ODOS prototype converter (AMOS 2026)")  # fmt: skip
    etree.SubElement(refs, A + "TLCOrganization", eId="unspecified", href="/ontology/organization/unspecified", showAs="Not determined from the source")  # fmt: skip
    notes_parent = etree.SubElement(m, A + "notes", source="#odos")  # filled below, removed if empty
    prop = etree.SubElement(m, A + "proprietary", source="#odos")
    ex_el = etree.SubElement(prop, O + "excerpt", complete="false")
    ex_el.set("scope", "all-paragraphs-of-body" if full else "selected-paragraphs")
    ex_el.set("included-paragraphs", " ".join(p.number for p in paragraphs))
    ex_el.set("paragraphs-in-model", str(len(model.of_type(T.PARAGRAPH))))
    if not legal_date:
        etree.SubElement(prop, O + "undated", **{"work-date-kind": "processing-date", "legal-date": "false",
                                                 "stated-version-year-month": meta.version_year_month or ""})  # fmt: skip
    etree.SubElement(prop, O + "source", file=model.source.filename or "", **{"docling-json-sha256": model.source.docling_json_sha256})  # fmt: skip

    # ---- preface (document title as found in the source) ------------------------------
    title_el = next((e for e in model.elements if e.region == "front" and e.original_text == meta.title), None)
    if title_el is not None:
        pre = etree.SubElement(act, A + "preface")
        p = etree.SubElement(pre, A + "p", eId="preface__p_1")
        g.eids.add("preface__p_1")
        dt = g.text(p, "docTitle", title_el.content_text, "preface__p_1__doctitle", title_el)
        g.eids.add("preface__p_1__doctitle")
        e = g.trace(title_el, "docTitle", "preface", eId="preface__p_1__doctitle", text_eId="preface__p_1__doctitle")  # fmt: skip
        e.content_text = title_el.content_text

    # ---- body ----------------------------------------------------------------------
    body = etree.SubElement(act, A + "body")
    index = model.by_id()
    open_nodes: dict[str, tuple[etree._Element, str]] = {}  # model id of shell -> (xml node, eId)
    for par in paragraphs:
        chain = [a for a in model.path(par.id) if a.type in CONTAINERS]
        parent_xml, parent_eid = body, None
        for anc in chain:
            if anc.id not in open_nodes:
                open_nodes[anc.id] = g.shell(anc, parent_xml, parent_eid)
            parent_xml, parent_eid = open_nodes[anc.id]
        g.container(par, parent_xml, parent_eid, shell=False)
    if full:  # annexes come after the last §; an excerpt of selected § never includes them
        for anlage in model.of_type(T.ANLAGE):
            g.container(anlage, body, None, shell=False)

    # ---- footnotes (meta/notes) -----------------------------------------------------
    for i, (head, anchor) in enumerate(g.footnotes, start=1):
        nid = g._reg(f"fn_{i}")
        note = etree.SubElement(notes_parent, A + "note", eId=nid)
        note.set(O + "anchor", anchor)
        g._mark(note, head)
        g.text(note, "heading", head.title or head.content_text, nid + "__heading", head)
        g.eids.add(nid + "__heading")
        g.trace(head, "note", eId=nid, heading_eId=nid + "__heading")
        for j, f in enumerate(g.children(head), start=1):
            pid = g._reg(f"{nid}__p_{j}")
            g.text(note, "p", f.content_text, pid, f)
            g.trace(f, "p", eId=pid, text_eId=pid)
    for f, anchor in g.loose_notes:
        nid = g._reg(f"fn_{len(notes_parent) + 1}")
        note = etree.SubElement(notes_parent, A + "note", eId=nid)
        note.set(O + "anchor", anchor)
        pid = g._reg(f"{nid}__p_1")
        g.text(note, "p", f.content_text, pid, f)
        g.trace(f, "p", eId=pid, text_eId=pid)
    if len(notes_parent) == 0:
        m.remove(notes_parent)

    # ---- accounting -----------------------------------------------------------------
    included = list(g.order)
    inc = set(included)
    excluded: dict[str, list[str]] = {"document_root": [], "front_matter": [], "table_of_contents": [], "page_furniture": [], "body_outside_excerpt": []}  # fmt: skip
    for e in model.elements:
        if e.id in inc:
            continue
        if e.type == T.DOCUMENT:
            excluded["document_root"].append(e.id)
        elif e.region == "front":
            excluded["front_matter"].append(e.id)
        elif e.region == "toc":
            excluded["table_of_contents"].append(e.id)
        else:
            excluded["body_outside_excerpt"].append(e.id)
    excluded["page_furniture"] = [e.id for e in model.furniture]
    for u in g.unmapped:
        excluded.setdefault("unmapped_inside_excerpt", []).append(u["model_id"])
    for mw in model.warnings:
        if mw.element_id in inc:
            g.warnings.append({"code": "MODEL_WARNING", "model_id": mw.element_id, "model_code": mw.code, "message": mw.message})  # fmt: skip

    if not legal_date:
        root.getprevious().text += "NOTE: the Work date is the ODOS processing date, not a legal date. "
    xml = etree.tostring(root.getroottree(), pretty_print=True, encoding="UTF-8", xml_declaration=True)
    return GenerationResult(
        xml=xml, entries=[g.entries[i] for i in included], included_ids=included,
        excluded=excluded, unmapped=g.unmapped, warnings=g.warnings,
        excerpt={
            "complete": False,
            "scope": "all-paragraphs-of-body" if full else "selected-paragraphs",
            "included_paragraphs": [f"§ {p.number}" for p in paragraphs],
            "paragraphs_in_model": len(model.of_type(T.PARAGRAPH)),
            "retrieval_date": retrieval_date,
        },
    )  # fmt: skip
