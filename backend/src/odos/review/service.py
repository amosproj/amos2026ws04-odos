"""Review workflow: corrections as versioned patches over an untouched original model.

* The original PDF, Docling output and document_model.json are never written to.
* Each text correction creates a new immutable model revision (effective model + regenerated Akoma Ntoso +
  official XSD validation + traceability + text report).
* Every write checks `base_revision` against the stored review revision (optimistic locking).
* Approval references one model revision and is refused while blocking errors or unchecked uncertain
  elements remain.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from odos.akn.generator import XML_ILLEGAL
from odos.artifact_names import AKN_REPORT, AKN_TEXT_REPORT, AKN_TRACEABILITY, AKN_XML, DOCLING_RAW, DOCUMENT_MODEL, LEGAL_JSON, LEGAL_JSON_REPORT
from odos.legal_json.artifacts import build_legal_json_artifacts
from odos.document_model import DocumentModel, Element, ElementType as T
from odos.parsing.profiles import for_model
from odos.review.model import (
    Approval, Confirmation, ConfirmRequest, Correction, CorrectionRequest, DecisionRequest, Export, HistoryEvent,
    ReviewRecord, ReviewState, ReviewView, RevisionValidation,
)
from odos.review.store import FileReviewStore, StaleRevision

EDITABLE_FIELDS = ("content_text", "title", "marker")
STRUCTURAL_FIELDS = {"parent_id", "children_ids", "type", "number", "id", "region", "source_refs", "provenance",
                     "source_spans", "pages", "docling_label", "table", "uncertain", "uncertainty_reasons"}  # fmt: skip
NOT_EDITABLE_TYPES = {T.DOCUMENT, T.PREAMBLE, T.CONCLUSIONS, T.TABLE, T.SIGNATURE, T.PAGE_HEADER, T.PAGE_FOOTER, T.PICTURE}
MAX_TEXT, MAX_MARKER = 20000, 40


class ReviewError(Exception):
    def __init__(self, status: int, code: str, message: str, **extra):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def build_effective_model(original: DocumentModel, corrections: list[Correction], model_revision: int) -> DocumentModel:
    """Original model + corrections up to `model_revision`. Never touches original_text or structure."""
    m = original.model_copy(deep=True)
    by_id = m.by_id()
    applied: list[str] = []
    for c in sorted(corrections, key=lambda c: c.model_revision):
        if c.model_revision > model_revision:
            continue
        el = by_id[c.element_id]
        orig_el = original.by_id()[c.element_id]
        mirror = c.field == "title" and orig_el.content_text == orig_el.title  # headings keep content == title
        setattr(el, c.field, c.corrected_value)
        if mirror:
            el.content_text = c.corrected_value
        fields = dict((el.reviewed or {}).get("fields", {}))
        ids = list((el.reviewed or {}).get("corrections", []))
        if c.corrected_value == getattr(orig_el, c.field):  # reverted to the original value
            fields.pop(c.field, None)
        else:
            fields[c.field] = {"original": getattr(orig_el, c.field), "corrected": c.corrected_value}
        ids.append(c.id)
        el.reviewed = {"fields": fields, "corrections": ids, "verbatim_from_source": False} if fields else None
        applied.append(c.id)
    corrected = {c.element_id for c in corrections if c.model_revision <= model_revision}
    if corrected:
        _revalidate_annotations(m, corrected)
    m.review = {"model_revision": model_revision, "corrections": applied,
                "note": "Corrected fields are reviewer text, not verbatim from the PDF; original_text stays the Docling text."}  # fmt: skip
    return m


def _revalidate_annotations(m: DocumentModel, corrected: set[str]) -> None:
    """Annotations computed on the source text are invalidated where the reviewer changed that text:
    * sentences with a range on a corrected element are rebuilt from the reviewed text (text rules only, status
      ``regenerated_from_reviewed_text``) or dropped; numbered sentence ids ``<unit>/satz-<n>`` stay the same;
    * TOC entries built from a corrected raw TOC element are rebuilt from the reviewed text (derived, never edited)."""
    from odos.parsing.sentences import regenerate_after_corrections
    from odos.parsing.toc import regenerate_after_corrections as regenerate_toc

    regenerate_after_corrections(m, corrected)
    regenerate_toc(m, corrected)


class ReviewService:
    def __init__(self, docs, store: FileReviewStore | None = None):
        self.docs = docs  # odos.api.storage.Store
        self.store = store or FileReviewStore(docs.doc_dir)

    # ---- helpers ---------------------------------------------------------------------------------------------
    def _original_path(self, doc_id: str) -> Path:
        p = self.docs.output_dir(doc_id) / DOCUMENT_MODEL
        if not p.is_file():
            raise ReviewError(409, "no_structure", "This document has no extracted legal structure to review (process it in a structured mode first).")  # fmt: skip
        return p

    def _original(self, doc_id: str) -> tuple[DocumentModel, str]:
        raw = self._original_path(doc_id).read_bytes()
        return DocumentModel.model_validate_json(raw), _sha(raw)

    def _validation(self, doc_id: str, model_revision: int) -> RevisionValidation | None:
        p = self.store.revision_dir(doc_id, model_revision) / "review_validation.json"
        return RevisionValidation.model_validate_json(p.read_text(encoding="utf-8")) if p.is_file() else None

    def effective_model(self, doc_id: str, model_revision: int | None = None) -> DocumentModel:
        rec = self.ensure(doc_id)
        n = rec.model_revision if model_revision is None else model_revision
        p = self.store.revision_dir(doc_id, n) / "effective_model.json"
        if not p.is_file():
            raise ReviewError(404, "revision_not_found", f"Model revision {n} does not exist.")
        return DocumentModel.model_validate_json(p.read_text(encoding="utf-8"))

    def revision_file(self, doc_id: str, model_revision: int, kind: str) -> Path:
        names = {"xml": AKN_XML, "validation": AKN_REPORT, "traceability": AKN_TRACEABILITY,
                 "text_report": AKN_TEXT_REPORT, "review_validation": "review_validation.json", "model": "effective_model.json",
                 "json": LEGAL_JSON, "json_validation": LEGAL_JSON_REPORT}  # fmt: skip
        if kind not in names:
            raise ReviewError(404, "unknown_revision_file", f"Unknown file '{kind}'. Known: {', '.join(names)}.")
        p = self.store.revision_dir(doc_id, model_revision) / names[kind]
        if not p.is_file():
            raise ReviewError(404, "revision_file_not_found", f"No {kind} for model revision {model_revision}.")
        return p

    def _generate(self, doc_id: str, model: DocumentModel, model_revision: int, corrected_ids: set[str], retrieval_date: str) -> RevisionValidation:  # fmt: skip
        """Write the revision (model + XML + reports) to staging, validate, then publish it write-once."""
        orphan = self.store.revision_dir(doc_id, model_revision)
        if orphan.exists():  # left by an interrupted write: it was never referenced by review.json
            shutil.rmtree(orphan)
        st = self.store.staging_dir(doc_id)
        model_bytes = model.model_dump_json(indent=2).encode("utf-8")
        (st / "effective_model.json").write_bytes(model_bytes)
        v = RevisionValidation(model_revision=model_revision, generated=False, model_sha256=_sha(model_bytes), generated_at=_now(),
                               corrected_elements=sorted(corrected_ids))  # fmt: skip
        json_blockers: list[str] = []
        try:  # document.json from the same effective model object as the XML below
            js = build_legal_json_artifacts(model, self.docs.output_dir(doc_id) / DOCLING_RAW, st)["report"]
            v.json_valid, v.json_sha256 = js["valid"], js["json_sha256"]
            v.json_errors = (js["schema_errors"] + js["structure_errors"])[:20]
            if not js["text_preservation"]["identical_to_model"]:
                v.json_errors.append("document.json text does not match the reviewed model")
            if not v.json_valid:
                json_blockers.append(f"document.json is not valid ({len(v.json_errors)} problem(s)).")
        except Exception as exc:  # noqa: BLE001 - recorded and blocks approval
            v.json_valid = False
            json_blockers.append(f"document.json could not be generated: {type(exc).__name__}: {exc}"[:500])
        try:
            art = for_model(model).build_akn(model, retrieval_date, st)  # the profile's whole-document Akoma Ntoso
            # every revision has its text report (the EU generator already wrote these same bytes)
            (st / AKN_TEXT_REPORT).write_text(json.dumps(art["text"], indent=2, ensure_ascii=False), encoding="utf-8")  # fmt: skip
            order = art["text"].get("document_order_preserved")  # None: this generator does not check the order
            val, text, res = art["validation"], art["text"], art["result"]
            diffs = [d["model_id"] for d in text["original_text_reconstruction_diffs"]]
            v.generated = True
            v.xsd_valid = val.valid
            v.xsd_errors = [f"line {e.line}: {e.message}" for e in val.errors[:20]]
            v.text_identical_to_reviewed_model = text["same_order_and_text"]
            v.document_order_preserved = order
            v.unmapped = len(res.unmapped)
            v.uncorrected_text_differences = [d for d in diffs if d not in corrected_ids]
            v.xml_sha256 = val.xml_sha256
        except Exception as exc:  # noqa: BLE001 - a failed generation is recorded and blocks approval
            v.error = f"{type(exc).__name__}: {exc}"[:500]
        b = []
        if not v.generated:
            b.append(f"Akoma Ntoso XML could not be generated: {v.error}")
        else:
            if not v.xsd_valid:
                b.append(f"XML is not valid against the official OASIS XSD ({len(v.xsd_errors)} error(s)).")
            if not v.text_identical_to_reviewed_model:
                b.append("XML text does not match the reviewed model.")
            if v.document_order_preserved is False:
                b.append("XML does not preserve the document order.")
            if v.unmapped:
                b.append(f"{v.unmapped} element(s) could not be mapped to XML.")
            if v.uncorrected_text_differences:
                b.append(f"{len(v.uncorrected_text_differences)} uncorrected element(s) no longer match their source text.")
        v.blocking_errors = b + json_blockers
        (st / "review_validation.json").write_text(v.model_dump_json(indent=2), encoding="utf-8")
        self.store.publish_revision(doc_id, model_revision, st)
        return v

    # ---- lifecycle ------------------------------------------------------------------------------------------------
    def ensure(self, doc_id: str) -> ReviewRecord:
        """Create the review (with revision 0 regenerated from the untouched model) on first access."""
        with self.store.lock(doc_id):
            rec = self.store.load(doc_id)
            original, sha = self._original(doc_id)
            if rec is not None and rec.base_model_sha256 != sha:  # the document was reprocessed underneath
                self.store.archive(doc_id, "original document model changed (document reprocessed)")
                rec = None
            if rec is not None:
                return rec
            st = self.docs.read(doc_id)
            retrieval = st.uploaded_at.date().isoformat()
            v = self._generate(doc_id, build_effective_model(original, [], 0), 0, set(), retrieval)
            rec = ReviewRecord(base_model_sha256=sha, profile=original.profile, retrieval_date=retrieval,
                               exports=[Export(model_revision=0, xml_sha256=v.xml_sha256, xsd_valid=v.xsd_valid, status="current", created_at=_now())],  # fmt: skip
                               history=[HistoryEvent(at=_now(), event="review_created", review_revision=0,
                                                     detail="Revision 0 regenerated from the original document model")])  # fmt: skip
            self.store.save(doc_id, rec, expected_revision=None)
            return rec

    def _check(self, rec: ReviewRecord, base_revision: int) -> None:
        if base_revision != rec.review_revision:
            raise ReviewError(409, "stale_revision",
                              f"Your view is based on review revision {base_revision}, but the current revision is {rec.review_revision}. Reload and try again.",  # fmt: skip
                              current_revision=rec.review_revision)

    def _save(self, doc_id: str, rec: ReviewRecord, expected: int) -> None:
        try:
            self.store.save(doc_id, rec, expected_revision=expected)
        except StaleRevision as exc:
            raise ReviewError(409, "stale_revision", str(exc), current_revision=exc.actual) from None

    def correct(self, doc_id: str, req: CorrectionRequest) -> ReviewView:
        self.ensure(doc_id)
        with self.store.lock(doc_id):
            rec = self.store.load(doc_id)
            self._check(rec, req.base_revision)
            if rec.state == ReviewState.APPROVED:
                raise ReviewError(409, "approved_locked", "The document is approved. Reopen the review before editing.")
            original, _ = self._original(doc_id)
            corrections = self.store.corrections(doc_id)
            current = build_effective_model(original, corrections, rec.model_revision)
            el = current.by_id().get(req.element_id)
            value = self._validate_edit(el, req)
            prev = getattr(el, req.field)
            c = Correction(id=f"c{len(corrections) + 1}", element_id=el.id, field=req.field,
                           original_value=getattr(original.by_id()[el.id], req.field), previous_value=prev,
                           corrected_value=value, timestamp=_now(), review_revision=rec.review_revision + 1,
                           model_revision=rec.model_revision + 1, note=req.note, reviewer=req.reviewer)  # fmt: skip
            all_c = [*corrections, c]
            eff = build_effective_model(original, all_c, c.model_revision)
            corrected_ids = {e.id for e in eff.elements if e.reviewed}
            v = self._generate(doc_id, eff, c.model_revision, corrected_ids, rec.retrieval_date)
            self.store.append_correction(doc_id, c)
            expected = rec.review_revision
            for ex in rec.exports:
                if ex.status == "current":
                    ex.status = "superseded"
            rec.exports.append(Export(model_revision=c.model_revision, xml_sha256=v.xml_sha256, xsd_valid=v.xsd_valid, status="current", created_at=_now()))  # fmt: skip
            rec.review_revision, rec.model_revision = c.review_revision, c.model_revision
            rec.state = ReviewState.IN_REVIEW
            rec.history.append(HistoryEvent(at=_now(), event="correction", review_revision=rec.review_revision,
                                            detail=f"{c.id} {el.id}.{req.field}" + (" (blocking validation errors)" if v.blocking_errors else "")))  # fmt: skip
            self._save(doc_id, rec, expected)
        return self.view(doc_id)

    def _validate_edit(self, el: Element | None, req: CorrectionRequest) -> str:
        if el is None:
            raise ReviewError(404, "element_not_found", f"No element '{req.element_id}' in this document.")
        f = req.field
        if f == "original_text":
            raise ReviewError(422, "original_text_immutable", "original_text is the verbatim text extracted from the PDF and cannot be changed. Correct 'content_text' instead.")  # fmt: skip
        if f in STRUCTURAL_FIELDS:
            raise ReviewError(422, "unsupported_structural_edit",
                              f"Structural editing ('{f}') is not supported yet. Only text ('content_text'), headings ('title') and numbering markers ('marker') can be corrected.")  # fmt: skip
        if f not in EDITABLE_FIELDS:
            raise ReviewError(422, "invalid_field", f"Unknown field '{f}'. Editable: {', '.join(EDITABLE_FIELDS)}.")
        if el.type in NOT_EDITABLE_TYPES:
            raise ReviewError(422, "element_not_editable", f"Elements of type '{el.type.value}' cannot be edited (containers, tables and page furniture).")  # fmt: skip
        if f == "title" and el.title is None:
            raise ReviewError(422, "field_not_applicable", "This element has no heading/title.")
        if f == "marker" and el.marker is None:
            raise ReviewError(422, "field_not_applicable", "This element has no numbering marker; adding numbering is a structural change and not supported yet.")  # fmt: skip
        if f == "content_text" and el.title is not None and el.content_text == el.title:
            raise ReviewError(422, "edit_title_instead", "For headings the text is the title: correct 'title' instead.")
        value = req.value
        if XML_ILLEGAL.search(value):
            raise ReviewError(422, "invalid_characters", "The value contains control characters that are not allowed in XML.")
        if len(value) > MAX_TEXT:
            raise ReviewError(422, "value_too_long", f"The value exceeds {MAX_TEXT} characters.")
        if f in ("title", "marker") and not value.strip():
            raise ReviewError(422, "empty_value", f"'{f}' cannot be empty.")
        if f == "marker" and ("\n" in value or len(value) > MAX_MARKER):
            raise ReviewError(422, "invalid_marker", f"A marker must be a single line of at most {MAX_MARKER} characters.")
        if f == "content_text" and not value.strip() and getattr(el, f).strip():
            raise ReviewError(422, "empty_value", "Text cannot be emptied (deleting content is a structural change and not supported).")  # fmt: skip
        if value == getattr(el, f):
            raise ReviewError(422, "no_change", "The value is identical to the current value.")
        return value

    def confirm(self, doc_id: str, req: ConfirmRequest) -> ReviewView:
        self.ensure(doc_id)
        with self.store.lock(doc_id):
            rec = self.store.load(doc_id)
            self._check(rec, req.base_revision)
            if rec.state == ReviewState.APPROVED:
                raise ReviewError(409, "approved_locked", "The document is approved. Reopen the review before changing it.")
            eff = self.effective_model(doc_id, rec.model_revision)
            el = eff.by_id().get(req.element_id)
            if el is None:
                raise ReviewError(404, "element_not_found", f"No element '{req.element_id}' in this document.")
            if not el.uncertain:
                raise ReviewError(422, "not_uncertain", "Only elements the parser marked as uncertain need a confirmation.")
            if any(c.element_id == el.id for c in self.store.confirmations(doc_id)):
                raise ReviewError(409, "already_confirmed", "This element has already been confirmed.")
            expected = rec.review_revision
            rec.review_revision += 1
            self.store.append_confirmation(doc_id, Confirmation(element_id=el.id, reasons=el.uncertainty_reasons, timestamp=_now(),
                                                                review_revision=rec.review_revision, note=req.note, reviewer=req.reviewer))  # fmt: skip
            if rec.state == ReviewState.PENDING_REVIEW:
                rec.state = ReviewState.IN_REVIEW
            rec.history.append(HistoryEvent(at=_now(), event="confirmation", review_revision=rec.review_revision, detail=el.id))
            self._save(doc_id, rec, expected)
        return self.view(doc_id)

    def approve(self, doc_id: str, req: DecisionRequest) -> ReviewView:
        self.ensure(doc_id)
        with self.store.lock(doc_id):
            rec = self.store.load(doc_id)
            self._check(rec, req.base_revision)
            if rec.state == ReviewState.APPROVED:
                raise ReviewError(409, "already_approved", "This revision is already approved.")
            blockers = self._blockers(doc_id, rec)
            if blockers:
                raise ReviewError(409, "approval_blocked", "Approval is blocked: " + " ".join(blockers), blockers=blockers)
            v = self._validation(doc_id, rec.model_revision)
            model_sha = _sha(self.revision_file(doc_id, rec.model_revision, "model").read_bytes())
            expected = rec.review_revision
            rec.review_revision += 1
            rec.approval = Approval(review_revision=rec.review_revision, model_revision=rec.model_revision, model_sha256=model_sha,
                                    xml_sha256=v.xml_sha256, json_sha256=v.json_sha256, approved_at=_now(), note=req.note, reviewer=req.reviewer,
                                    confirmed_uncertain=len(self.store.confirmations(doc_id)), corrections=len(self.store.corrections(doc_id)))  # fmt: skip
            for ex in rec.exports:
                if ex.model_revision == rec.model_revision:
                    ex.status = "approved"
            rec.state = ReviewState.APPROVED
            rec.history.append(HistoryEvent(at=_now(), event="approved", review_revision=rec.review_revision, detail=f"model revision {rec.model_revision}"))  # fmt: skip
            self._save(doc_id, rec, expected)
        return self.view(doc_id)

    def request_changes(self, doc_id: str, req: DecisionRequest) -> ReviewView:
        self.ensure(doc_id)
        with self.store.lock(doc_id):
            rec = self.store.load(doc_id)
            self._check(rec, req.base_revision)
            if rec.state == ReviewState.APPROVED:
                raise ReviewError(409, "approved_locked", "The document is approved. Reopen the review first.")
            expected = rec.review_revision
            rec.review_revision += 1
            rec.state = ReviewState.CHANGES_REQUESTED
            rec.history.append(HistoryEvent(at=_now(), event="changes_requested", review_revision=rec.review_revision, detail=req.note))
            self._save(doc_id, rec, expected)
        return self.view(doc_id)

    def reopen(self, doc_id: str, req: DecisionRequest) -> ReviewView:
        self.ensure(doc_id)
        with self.store.lock(doc_id):
            rec = self.store.load(doc_id)
            self._check(rec, req.base_revision)
            if rec.state != ReviewState.APPROVED:
                raise ReviewError(409, "not_approved", "Only an approved review can be reopened.")
            expected = rec.review_revision
            rec.review_revision += 1
            rec.previous_approvals.append(rec.approval)
            rec.approval = None
            rec.state = ReviewState.IN_REVIEW
            rec.history.append(HistoryEvent(at=_now(), event="reopened", review_revision=rec.review_revision, detail=req.note))
            self._save(doc_id, rec, expected)
        return self.view(doc_id)

    # ---- read model -----------------------------------------------------------------------------------------------
    def _blockers(self, doc_id: str, rec: ReviewRecord) -> list[str]:
        out = []
        v = self._validation(doc_id, rec.model_revision)
        if v is None:
            out.append("The current revision has not been validated.")
        else:
            out += v.blocking_errors
        unresolved = self._unresolved(doc_id, rec)
        if unresolved:
            out.append(f"{len(unresolved)} uncertain element(s) have not been checked and confirmed.")
        return out

    def _unresolved(self, doc_id: str, rec: ReviewRecord) -> list[str]:
        eff = self.effective_model(doc_id, rec.model_revision)
        confirmed = {c.element_id for c in self.store.confirmations(doc_id)}
        return [e.id for e in eff.elements if e.uncertain and e.id not in confirmed]

    def view(self, doc_id: str) -> ReviewView:
        rec = self.ensure(doc_id)
        eff = self.effective_model(doc_id, rec.model_revision)
        unresolved = self._unresolved(doc_id, rec)
        blockers = [] if rec.state == ReviewState.APPROVED else self._blockers(doc_id, rec)
        return ReviewView(
            document_id=doc_id, state=rec.state, review_revision=rec.review_revision, model_revision=rec.model_revision,
            profile=rec.profile, corrections=self.store.corrections(doc_id), confirmations=self.store.confirmations(doc_id),
            corrected_element_ids=[e.id for e in eff.elements if e.reviewed],
            uncertain_element_ids=[e.id for e in eff.elements if e.uncertain], unresolved_uncertain_ids=unresolved,
            validation=self._validation(doc_id, rec.model_revision),
            can_approve=rec.state != ReviewState.APPROVED and not blockers, approval_blockers=blockers,
            approval=rec.approval, previous_approvals=rec.previous_approvals, exports=rec.exports,
            original_export_superseded=rec.model_revision > 0, history=rec.history,
        )  # fmt: skip

    def archive(self, doc_id: str, reason: str) -> None:
        with self.store.lock(doc_id):
            self.store.archive(doc_id, reason)
