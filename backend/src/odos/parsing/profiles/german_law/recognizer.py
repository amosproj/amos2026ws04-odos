"""Deterministic German legal structure parser.

Rebuilds Teil > Kapitel > Abschnitt > § > (n) > n. > a) from textual markers
and document order. Docling heading levels are not used. Nothing is merged,
dropped or invented: every Docling item becomes exactly one element, and
anything the rules cannot place is kept and flagged.
"""

from __future__ import annotations

import re
from typing import NamedTuple

from odos.parsing.builder import ROOT_ID, StructureBuilder, furniture_element
from odos.normalization.docling_reader import SourceItem
from odos.normalization.lang_de import MONTHS_UPPER, ORDINAL_STEMS
from odos.document_model import DocumentMetadata, DocumentModel, Element, ElementType as T
from odos.parsing.profiles.german_law.rules import ORDINAL_KINDS, LegalStructureRules, number_key

CONTENT_LABELS = {"text", "list_item", "code"}
SLUG = {
    T.TEIL: "teil", T.KAPITEL: "kapitel", T.ABSCHNITT: "abschnitt",
    T.UNTERABSCHNITT: "unterabschnitt", T.PARAGRAPH: "par", T.ABSATZ: "abs",
    T.NUMMER: "nr", T.BUCHSTABE: "lit", T.DOPPELBUCHSTABE: "lit2", T.ANLAGE: "anlage",
}  # fmt: skip


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


class _Builder(StructureBuilder):
    """The shared builder plus German list state: Nummer runs restarted by an interlaced sentence."""

    def __init__(self, rules: LegalStructureRules):
        super().__init__(rules.levels)
        self.rules = rules
        self.list_open = False  # the previous body item was (part of) an enumerated list
        self._nr_run: dict[str, int] = {}  # parent_id → current Nummer run (1 = first, 2+ = restarted)

    def run_local(self, parent: Element, type_: T, number: str, *, new_run: bool = False) -> str:
        """Assign a run-prefixed local id for a restarted numbered list: run2-nr-1, run3-nr-2, etc."""
        slug = SLUG.get(type_, type_.value)
        key = (parent.id, f"run_{slug}")
        if new_run:
            run = self.counters.get(key, 1) + 1
            self.counters[key] = run
        else:
            run = self.counters.get(key, 1)
        return f"run{run}-{slug}-{number}"


class HeadingMatch(NamedTuple):
    type: T
    number: str
    title: str
    marker: str


def _match_heading(text: str, rules: LegalStructureRules) -> HeadingMatch | None:
    om = rules.ordinal_heading.match(text)
    if om:
        number = str(ORDINAL_STEMS[om.group("ord")])
        return HeadingMatch(ORDINAL_KINDS[om.group("kind")], number, re.sub(r"\s+", " ", om.group("title")).strip(),
                            text[: om.start("title")].strip())  # fmt: skip
    for t, pat in rules.headings.items():
        m = pat.match(text)
        if m:
            title = re.sub(r"\s+", " ", m.group(2)).strip()
            return HeadingMatch(t, m.group(1), title, text[: m.start(2)].strip() if title else text.strip())
    return None


def _structural_line(text: str, rules: LegalStructureRules) -> bool:
    """True if the line is a heading / numbered line of its own, i.e. cannot be a heading title."""
    t = text.strip()
    return bool(
        _match_heading(t, rules) or rules.absatz.match(t) or rules.nummer_text.match(t)
        or rules.buchstabe_text.match(t) or rules.numeric_heading.match(t)
        or _norm(t) in rules.footnote_titles + rules.toc_titles
    )  # fmt: skip


def _next_index(items: list[SourceItem], i: int) -> int:
    """Index of the next non-furniture item after i."""
    j = i + 1
    while j < len(items) and items[j].is_furniture:
        j += 1
    return j


def _title_continuation(items: list[SourceItem], i: int, rules: LegalStructureRules) -> int | None:
    """A heading without a title ("§ 3", "Erster Teil") followed by a plain section_header that carries the title."""
    j = _next_index(items, i)
    if j < len(items) and items[j].label == "section_header" and items[j].orig.strip() and not _structural_line(items[j].orig, rules):  # fmt: skip
        return j
    return None


def _find_toc_range(items: list[SourceItem], rules: LegalStructureRules):
    """Returns (toc_start, body_start) item indices; None where not found.

    The body starts at the first single "§ n [Title]" section header (title possibly on the next
    header line) that is followed by real content, not by another table-of-contents-like entry."""
    toc_start = next(
        (i for i, it in enumerate(items)
         if it.label == "section_header" and _norm(it.text) in rules.toc_titles),
        None,
    )  # fmt: skip
    if toc_start is None:
        return None, None

    def content_follows(i: int) -> bool:
        j = _next_index(items, i)
        t = _title_continuation(items, i, rules)
        if t is not None and rules.paragraph_heading_strict.match(items[i].orig.strip()) is None:
            j = _next_index(items, t)  # skip the title line
        if j >= len(items):
            return False
        nxt = items[j]
        first = nxt.orig.strip()
        return (nxt.label in {"text", "code", "list_item"} and not first.startswith("§")
                and _match_heading(first, rules) is None)  # fmt: skip

    body_start = None
    for i in range(toc_start + 1, len(items)):
        it = items[i]
        text = it.orig.strip()
        if (it.label == "section_header" and not it.is_furniture
                and rules.paragraph_heading_any.match(text) and text.count("§") == 1
                and content_follows(i)):  # fmt: skip
            body_start = i
            break
    if body_start is None:
        return toc_start, None
    # Teil/Kapitel/Abschnitt headings (and their title lines) directly above the first § belong to the body
    j = body_start
    k = body_start - 1
    while k > toc_start:
        it = items[k]
        if it.is_furniture:
            k -= 1
            continue
        text = it.orig.strip()
        hm = _match_heading(text, rules) if it.label == "section_header" else None
        if hm is not None and hm.type not in (T.PARAGRAPH,):
            j = k
            k -= 1
            continue
        if it.label == "section_header" and not _structural_line(text, rules):
            p = k - 1  # a title line: keep it only if the heading above it has no title
            while p > toc_start and items[p].is_furniture:
                p -= 1
            above = _match_heading(items[p].orig.strip(), rules) if items[p].label == "section_header" else None
            if above is not None and not above.title:
                j = k
                k -= 1
                continue
        break
    return toc_start, j


def parse_items(info, items: list[SourceItem], rules: LegalStructureRules) -> DocumentModel:
    b = _Builder(rules)
    root = b.root
    meta = DocumentMetadata()

    toc_start, body_start = _find_toc_range(items, rules)
    if toc_start is None:
        b.warn("NO_TOC_FOUND", "No table-of-contents heading found; whole document parsed as body.", severity="info")  # fmt: skip
        body_start = 0
    elif body_start is None:
        b.warn("BODY_START_NOT_FOUND", "Table of contents found but no body start (first '§ n Title' heading); remaining items are kept as TOC entries.")  # fmt: skip
        body_start = len(items)

    toc: Element | None = None
    footnote_head: Element | None = None
    expect_vollzitat = False
    first_headers: list[str] = []
    front_items: list[SourceItem] = []
    consumed: set[int] = set()  # items merged into the previous heading as its title

    for i, item in enumerate(items):
        if i in consumed:
            continue
        # -- page furniture: kept outside the tree --------------------------------
        if item.is_furniture:
            ptype = T.PAGE_HEADER if item.label == "page_header" else T.PAGE_FOOTER
            page = item.pages[0] if item.pages else 0
            eid = f"furniture/p{page}-{'header' if ptype == T.PAGE_HEADER else 'footer'}"
            b.furniture.append(furniture_element(item, eid, ptype))
            continue

        in_front = toc_start is not None and i < toc_start
        in_toc = toc_start is not None and toc_start <= i < body_start

        # -- front matter ----------------------------------------------------
        if in_front:
            fm = b.add(item, T.FRONT_MATTER, root, "front", local=b.seq_local(root, "front"))
            front_items.append(item)
            if item.label == "section_header" and len(first_headers) < 2 and _norm(item.text) not in rules.footnote_titles:  # fmt: skip
                first_headers.append(item.text)
            _front_metadata(meta, item, expect_vollzitat)
            expect_vollzitat = item.orig.strip().lower().startswith("vollzitat")
            if _norm(item.text) in rules.footnote_titles:
                fm.type = T.FOOTNOTE_HEADING
            continue

        # -- table of contents (kept apart from the body) --------------------------
        if in_toc:
            if i == toc_start:
                toc = b.add(item, T.TOC, root, "toc", local="toc", title=item.text)
            else:
                assert toc is not None
                t = T.TABLE if item.table else T.TOC_ENTRY
                b.add(item, t, toc, "toc", local=b.seq_local(toc, "entry"))
            continue

        # -- body -----------------------------------------------------------------
        text = item.orig.strip()
        container = b.stack[-1] if b.stack else root

        if item.label == "footnote":  # Docling's page-footnote label
            anchor = _footnote_anchor(b)
            b.add(item, T.FOOTNOTE, anchor, "body", local=b.seq_local(anchor, "fn"),
                  reasons=["page_footnote_anchor_unknown"])  # fmt: skip
            continue

        if item.label == "section_header":
            if _norm(item.text) in rules.footnote_titles:
                anchor = _footnote_anchor(b)
                footnote_head = b.add(item, T.FOOTNOTE_HEADING, anchor, "body",
                                      local=b.seq_local(anchor, "fn"), title=item.text)  # fmt: skip
                continue
            footnote_head = None
            hm = _match_heading(text, rules)
            reasons: list[str] = []
            if hm is None:
                hm = _numeric_paragraph(b, text)
                if hm is not None:
                    reasons = ["paragraph_symbol_missing_in_source"]
                    b.warn("PARAGRAPH_MARKER_MISSING", f"'{hm.marker} {hm.title[:40]}' continues the § sequence but the source has no '§' sign; kept verbatim as § {hm.number}, not corrected.", item=item)  # fmt: skip
            if hm is not None:
                absorbed = None
                if not hm.title and (j := _title_continuation(items, i, rules)) is not None:
                    absorbed = items[j]
                    consumed.add(j)
                _open_heading(b, item, hm, absorbed, reasons)
                b.list_open = False
                continue
            if _numbered_line(b, item, text):
                continue
            b.warn("UNRECOGNIZED_HEADING", f"Section header matches no structural rule: {text[:70]!r}", item=item)  # fmt: skip
            b.add(item, T.UNRECOGNIZED, container, "body", local=b.seq_local(container, "unrec"),  # fmt: skip
                  reasons=["unrecognized_section_header"])
            continue

        if item.table is not None or item.label == "table":
            b.add(item, T.TABLE, container, "body", local=b.seq_local(container, "table"))
            continue

        # footnote body: content directly after a "Fußnote" heading
        if footnote_head is not None and item.label in CONTENT_LABELS and not rules.absatz.match(text):  # fmt: skip
            b.add(item, T.FOOTNOTE, footnote_head, "body", local=b.seq_local(footnote_head, "text"))  # fmt: skip
            continue
        footnote_head = None

        if item.label == "text":
            if _numbered_line(b, item, text):
                continue
            hm = _match_heading(text, rules)
            reasons = []
            if hm is not None:
                reasons.append("heading_pattern_in_text_label_not_promoted")
                b.warn("HEADING_PATTERN_IN_TEXT", f"Text item starts like a {hm.type.value} heading but Docling did not label it a header; kept as text: {text[:70]!r}", item=item, severity="info")  # fmt: skip
            _add_text(b, item, T.TEXT, reasons, b.list_open)
            continue

        if item.label == "list_item":
            marker = item.marker or ""
            if m := rules.absatz.match(text):  # Docling often labels "(1) ..." as a list item
                _open_absatz(b, item, m, text, [] if marker else ["absatz_marker_in_text_of_list_item"])
                b.list_open = False
                continue
            if item.enumerated and (m := rules.nummer_marker.match(marker)):
                _open_numbered(b, item, T.NUMMER, m.group(1), marker, item.text, [])
            elif item.enumerated and (m := rules.buchstabe_marker.match(marker)):
                _open_numbered(b, item, T.BUCHSTABE, m.group(1), marker, item.text, [])
            elif item.enumerated and (m := rules.doppelbuchstabe_marker.match(marker)):
                _open_numbered(b, item, T.DOPPELBUCHSTABE, m.group(1), marker, item.text, [])
            elif (m := rules.nummer_text.match(text)) and any(e.type in (T.PARAGRAPH, T.ANLAGE) for e in b.stack):
                _open_numbered(b, item, T.NUMMER, m.group(1), text[: m.start(2)].strip(), m.group(2), ["numbered_item_marker_only_in_text_of_list_item"])  # fmt: skip
            else:
                b.warn("LIST_ITEM_WITHOUT_RECOGNIZED_MARKER", f"List item with marker {marker!r} kept unnumbered: {text[:60]!r}", item=item)  # fmt: skip
                reasons_li: list[str] = ["list_item_without_recognized_marker"]
                confirmed_li: list[str] = []
                if re.match(r"[2-9]\d?\s", item.orig.lstrip()) and b.list_open:
                    confirmed_li.append("unmarked_list_item_satz_n_confirmed")
                    reasons_li = []
                _add_text(b, item, T.UNMARKED_LIST_ITEM, reasons_li, b.list_open)
                if confirmed_li:
                    b.elements[-1].hygiene_flags.extend(confirmed_li)
                    b.elements[-1].uncertain = bool(b.elements[-1].uncertainty_reasons)
                continue
            b.list_open = True
            continue

        # code or any other label in the body
        b.warn("UNRECOGNIZED_ITEM", f"Item with Docling label {item.label!r} kept as unrecognized: {text[:60]!r}", item=item)  # fmt: skip
        b.add(item, T.UNRECOGNIZED, container, "body", local=b.seq_local(container, "unrec"), reasons=[f"unhandled_label_{item.label}"])  # fmt: skip

    _sanity_checks(b)
    model = DocumentModel(
        source=info, metadata=_finish_meta(meta, first_headers, front_items), root_id=ROOT_ID,
        elements=b.elements, furniture=b.furniture, warnings=b.warnings,
    )  # fmt: skip
    return model  # page furniture is detached by the engine (stage finalize_structure)


# -- extraction-hygiene fields (derived; never change original_text) -------------------
# -- rule application ---------------------------------------------------------------
def _footnote_anchor(b: _Builder) -> Element:
    return next((e for e in reversed(b.stack) if b.level(e) <= b.rules.levels[T.PARAGRAPH]), b.index[ROOT_ID])


def _numeric_paragraph(b: _Builder, text: str) -> HeadingMatch | None:
    """"23 Zertifizierung": a header that continues the § sequence exactly but has lost its "§" sign."""
    m = b.rules.numeric_heading.match(text)
    prev = next((e for e in reversed(b.elements) if e.type == T.PARAGRAPH), None)
    if not m or prev is None:
        return None
    new, old = number_key(m.group(1)), number_key(prev.number)
    nxt = new[0] == old[0] + 1 and new[1] == "" or (new[0] == old[0] and new[1] > old[1])
    if not nxt:
        return None
    title = re.sub(r"\s+", " ", m.group(2)).strip()
    return HeadingMatch(T.PARAGRAPH, m.group(1), title, m.group(1))


def _numbered_line(b: _Builder, item: SourceItem, text: str) -> bool:
    """Absatz / Nummer / Buchstabe recognised from the text, whatever Docling labelled the line."""
    rules = b.rules
    how = f"labelled_{item.label}_by_docling"
    mislabel = item.label != "text"
    if m := rules.absatz.match(text):
        _open_absatz(b, item, m, text, [],
                     confirmed_flags=[f"absatz_{how}_confirmed"] if mislabel else [])
        b.list_open = False
        return True
    if (m := rules.nummer_text.match(text)) and any(e.type in (T.PARAGRAPH, T.ANLAGE) for e in b.stack):
        _open_numbered(b, item, T.NUMMER, m.group(1), text[: m.start(2)].strip(), m.group(2), [],
                       confirmed_flags=[f"numbered_item_{how}_confirmed"] if mislabel else [])
        b.list_open = True
        return True
    if (m := rules.buchstabe_text.match(text)) and any(e.type == T.NUMMER for e in b.stack):
        _open_numbered(b, item, T.BUCHSTABE, m.group(1), text[: m.start(2)].strip(), m.group(2), [],
                       confirmed_flags=[f"lettered_item_{how}_confirmed"] if mislabel else [])
        b.list_open = True
        return True
    return False


def _open_heading(b: _Builder, item, hm: HeadingMatch, absorbed: SourceItem | None, reasons: list[str]) -> None:
    htype, number, marker = hm.type, hm.number, hm.marker
    title = hm.title
    reasons = list(reasons)
    absorbed_flag = False
    if absorbed is not None:
        title = re.sub(r"\s+", " ", absorbed.orig).strip()
        absorbed_flag = True
    b.pop_to_below(b.rules.levels[htype])
    parent = b.stack[-1] if b.stack else b.index[ROOT_ID]
    if not title:
        reasons.append("heading_without_title_on_same_line")
        b.warn("HEADING_WITHOUT_TITLE", f"{marker!r} has no title in the same item; title not invented.", item=item, severity="info")  # fmt: skip
    el = b.add(item, htype, parent, "body", local=f"{SLUG[htype]}-{number}", number=number,
               marker=marker, title=title or None, content=title, reasons=reasons,
               merge=[absorbed] if absorbed is not None else None)  # fmt: skip
    if absorbed_flag:
        el.hygiene_flags.append("title_taken_from_next_header_line")
    _check_heading_sequence(b, el, parent)
    b.stack.append(el)


def _check_heading_sequence(b: _Builder, el: Element, parent: Element) -> None:
    if el.type == T.PARAGRAPH:
        prev = next((e for e in reversed(b.elements[:-1]) if e.type == T.PARAGRAPH), None)
        if prev and number_key(el.number) <= number_key(prev.number):
            b.warn("PARAGRAPH_ORDER", f"§ {el.number} follows § {prev.number} (not increasing).", el)  # fmt: skip
        elif prev and number_key(el.number)[0] > number_key(prev.number)[0] + 1:
            b.warn("PARAGRAPH_GAP", f"§ {el.number} follows § {prev.number} (gap).", el, severity="info")  # fmt: skip
        return
    if el.type == T.ANLAGE:
        return
    sibs = [b.index[c] for c in parent.children_ids[:-1] if b.index[c].type == el.type]
    exp = (number_key(sibs[-1].number)[0] + 1) if sibs else 1
    if number_key(el.number)[0] != exp and not (sibs and number_key(el.number)[0] == exp - 1):
        b.warn("HEADING_SEQUENCE", f"{el.marker} under {parent.id}: expected number {exp}.", el)


def _open_absatz(b: _Builder, item, m, text: str, reasons: list[str] | None = None,
                 confirmed_flags: list[str] | None = None) -> None:
    number = m.group(1)
    if not any(e.type == T.PARAGRAPH for e in b.stack):
        b.warn("ABSATZ_OUTSIDE_PARAGRAPH", f"'({number})' found outside any §; kept as text.", item=item)  # fmt: skip
        _add_text(b, item, T.TEXT, ["absatz_marker_outside_paragraph", *(reasons or [])], False)
        return
    b.pop_to_below(b.rules.levels[T.ABSATZ])
    parent = b.stack[-1]
    prev = [b.index[c] for c in parent.children_ids if b.index[c].type == T.ABSATZ]
    el = b.add(item, T.ABSATZ, parent, "body", local=f"abs-{number}", number=number,
               marker=f"({number})", content=m.group(2).strip(), reasons=list(reasons or []))  # fmt: skip
    el.hygiene_flags.extend(confirmed_flags or [])
    exp = number_key(prev[-1].number)[0] + 1 if prev else 1
    k = number_key(number)
    if k[0] != exp and not (prev and k[0] == exp - 1 and k[1]):
        b.warn("ABSATZ_SEQUENCE", f"{parent.marker}: Absatz ({number}) where ({exp}) was expected.", el)  # fmt: skip
        el.uncertain = True
        el.uncertainty_reasons.append("absatz_sequence_break")
    b.stack.append(el)


_TEXT_LIKE = (T.TEXT, T.UNMARKED_LIST_ITEM)


def _is_restart(b: _Builder, parent: Element, type_: T, number: str) -> bool:
    """True if this numbered item restarts a list under the same parent: a '1.' that appears after the
    parent already has numbered children. Covers both sentence-interlaced restarts (text between the runs)
    and direct restarts (no text between, just a new '1.' after an unrelated sub-list)."""
    if type_ != T.NUMMER or number_key(number)[0] != 1:
        return False
    kids = parent.children_ids
    prev_nr = [b.index[c] for c in kids if b.index[c].type == type_]
    if not prev_nr:
        return False
    return True


def _open_numbered(b: _Builder, item, type_: T, number: str, marker: str, content: str, reasons,
                   confirmed_flags: list[str] | None = None) -> None:  # fmt: skip
    b.pop_to_below(b.rules.levels[type_])
    parent = b.stack[-1] if b.stack else b.index[ROOT_ID]
    expected_parent = {T.NUMMER: (T.ABSATZ, T.PARAGRAPH, T.ANLAGE), T.BUCHSTABE: (T.NUMMER,),
                       T.DOPPELBUCHSTABE: (T.BUCHSTABE,)}[type_]  # fmt: skip
    reasons = list(reasons)
    if parent.type not in expected_parent:
        reasons.append(f"{type_.value}_under_{parent.type.value}")
        b.warn("UNEXPECTED_PARENT", f"{type_.value} {marker!r} attached under {parent.type.value} ({parent.id}).", item=item)  # fmt: skip
    restart = _is_restart(b, parent, type_, number)
    in_run = b._nr_run.get(parent.id, 1) > 1 if type_ == T.NUMMER else False
    if restart:
        local = b.run_local(parent, type_, number, new_run=True)
        b._nr_run[parent.id] = b.counters.get((parent.id, f"run_{SLUG[type_]}"), 1)
    elif in_run:
        local = b.run_local(parent, type_, number)
    else:
        local = f"{SLUG[type_]}-{number}"
    el = b.add(item, type_, parent, "body", local=local, number=number,
               marker=marker, content=content.strip(), reasons=reasons)  # fmt: skip
    el.hygiene_flags.extend(confirmed_flags or [])
    if restart:
        el.hygiene_flags.append("sentence_interlaced_list_restart")
    elif in_run:
        el.hygiene_flags.append("sentence_interlaced_list_continuation")
    prev = [b.index[c] for c in parent.children_ids[:-1] if b.index[c].type == type_]
    if type_ == T.NUMMER:
        exp = number_key(prev[-1].number)[0] + 1 if prev else 1
        k = number_key(number)[0]
        if k != exp and not restart:
            b.warn("NUMMER_SEQUENCE", f"{parent.id}: Nummer {marker} where {exp}. was expected (list restart or break).", el, severity="info")  # fmt: skip
            el.uncertain = True
            el.uncertainty_reasons.append("nummer_sequence_break")
    b.stack.append(el)


UNIT_TYPES = (T.ABSATZ, T.NUMMER, T.BUCHSTABE, T.DOPPELBUCHSTABE)


def _last_body_element(b: _Builder) -> Element | None:
    return next((e for e in reversed(b.elements) if e.region == "body" and e.type not in (T.FOOTNOTE, T.FOOTNOTE_HEADING)), None)  # fmt: skip


def _add_text(b: _Builder, item, type_: T, reasons: list[str], after_list: bool) -> None:
    """Attach an unnumbered text item. Where it belongs is a judgement, so it is always flagged."""
    reasons = list(reasons)
    confirmed: list[str] = []
    first = item.orig.lstrip()[:1]
    prev = _last_body_element(b)
    page_break = (prev is not None and prev.type in UNIT_TYPES and b.stack and b.stack[-1] is prev
                  and prev.pages and item.pages and item.pages[0] > prev.pages[-1]
                  and not prev.original_text.rstrip().endswith((".", ":", ";", "!", "?")))  # fmt: skip
    if page_break:
        reasons.append("continuation_across_page_break_attached_to_previous_element")
    elif after_list and b.stack and b.stack[-1].type == T.NUMMER and not b.stack[-1].children_ids \
            and b.stack[-1].original_text.rstrip().endswith(":"):  # fmt: skip
        confirmed.append("text_after_colon_ending_nummer_confirmed")
        b.list_open = True
    elif after_list:
        top = b.stack[-1] if b.stack else None
        if first.islower() and top is not None and top.type in (T.BUCHSTABE, T.DOPPELBUCHSTABE):
            b.pop_to_below(b.rules.levels[T.BUCHSTABE])
            prev_unit = _last_body_element(b)
            if (first.islower() and prev_unit is not None
                    and not prev_unit.original_text.rstrip().endswith((".", ":", ";", "!", "?"))):
                confirmed.append("enumeration_closing_clause_confirmed")
            else:
                reasons.append("text_after_sub_list_attached_to_enclosing_nummer")
        else:
            b.pop_to_below(b.rules.levels[T.NUMMER])
            if re.match(r"[2-9]\d?\s", item.orig.lstrip()):
                confirmed.append("text_after_list_satz_n_confirmed")
            else:
                prev_unit = _last_body_element(b)
                if (first.islower() and prev_unit is not None
                        and not prev_unit.original_text.rstrip().endswith((".", ":", ";", "!", "?"))):
                    confirmed.append("enumeration_closing_clause_confirmed")
                else:
                    reasons.append("text_after_list_attached_to_enclosing_container")
        b.list_open = False
    else:
        b.list_open = False
    container = b.stack[-1] if b.stack else b.index[ROOT_ID]
    if container.type in (T.TEIL, T.KAPITEL, T.ABSCHNITT, T.UNTERABSCHNITT, T.DOCUMENT):
        reasons.append("text_outside_paragraph")
        b.warn("TEXT_OUTSIDE_PARAGRAPH", f"Unnumbered text directly under {container.id}: {item.orig[:60]!r}", item=item)  # fmt: skip
    el = b.add(item, type_, container, "body", local=b.seq_local(container, "txt"), reasons=reasons)  # fmt: skip
    el.hygiene_flags.extend(confirmed)
    _continuation_check(b, el, item)


_SPECIFIC_PLACEMENT_REASONS = frozenset({
    "continuation_across_page_break_attached_to_previous_element",
    "text_after_list_attached_to_enclosing_container",
    "text_after_sub_list_attached_to_enclosing_nummer",
    "enumeration_closing_clause_confirmed",
})


def _continuation_check(b: _Builder, el: Element, item: SourceItem) -> None:
    """Flag (never merge) text that looks like the middle of a sentence."""
    if el.uncertainty_reasons and _SPECIFIC_PLACEMENT_REASONS & set(el.uncertainty_reasons):
        return
    if el.hygiene_flags and "enumeration_closing_clause_confirmed" in el.hygiene_flags:
        return
    first = item.orig.lstrip()[:1]
    prev = next((e for e in reversed(b.elements[:-1]) if e.region == "body"), None)
    if first.islower() and prev and prev.original_text.rstrip()[-1:] not in ".:;!?\""")":
        el.uncertain = True
        el.uncertainty_reasons.append("possible_continuation_of_previous_element")
        b.warn("POSSIBLE_CONTINUATION", f"Starts lowercase after an element without sentence end: {item.orig[:50]!r}", el, severity="info")  # fmt: skip


def _sanity_checks(b: _Builder) -> None:
    for e in b.elements:
        if e.type == T.PARAGRAPH and not e.children_ids:
            b.warn("EMPTY_PARAGRAPH", f"{e.marker} has no content elements.", e)


def _front_metadata(meta: DocumentMetadata, item: SourceItem, after_vollzitat: bool) -> None:
    t = item.orig.strip()
    if after_vollzitat and meta.vollzitat is None:
        meta.vollzitat = t.strip('"„""')
    elif t.startswith("Ausfertigungsdatum:"):
        meta.ausfertigungsdatum = t.split(":", 1)[1].strip()
    elif t.startswith("Stand:"):
        meta.stand = t.split(":", 1)[1].strip()


SHORT_TITLE = re.compile(r"^[A-ZÄÖÜ][\wÄÖÜäöüß\-]{1,14}$")
BULLET_SHORT = re.compile(r"^[-–]\s*([A-ZÄÖÜ][\wÄÖÜäöüß]{1,14})\s*[-–]$")


def _finish_meta(meta: DocumentMetadata, headers: list[str], front: list[SourceItem]) -> DocumentMetadata:
    if headers:
        meta.title = headers[0]
    # the short title is a short second header ("BDSG") or a "- MBO -" line; never a sentence
    if len(headers) > 1 and SHORT_TITLE.match(headers[1].strip()):
        meta.short_title = headers[1].strip()
    else:
        for it in front:
            if (m := BULLET_SHORT.match(it.orig.strip())):
                meta.short_title = m.group(1)
                break
    # version statements ("FASSUNG NOVEMBER 2002 ZULETZT GEÄNDERT ... VOM 26./27.9.2024"), verbatim
    lines = [it.orig.strip() for it in front if it.label == "section_header" and re.search(r"FASSUNG|ZULETZT GE|^VOM\s", it.orig.strip(), re.I)]  # fmt: skip
    if lines:
        meta.stated_version_text = " ".join(lines)
        m = re.search(r"FASSUNG\s+(\w+)\s+(\d{4})", meta.stated_version_text, re.I)
        if m and m.group(1).upper() in MONTHS_UPPER:
            meta.version_year_month = f"{m.group(2)}-{MONTHS_UPPER[m.group(1).upper()]:02d}"
    return meta
