import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ElementDetail } from "./components/ElementDetail";
import { ReviewEditor } from "./components/ReviewEditor";
import { ReviewPanel } from "./components/ReviewPanel";
import { editableFields, nextUnresolved, reviewBadge } from "./review";
import type { DocElement, ReviewView } from "./types";

const el = (extra: Partial<DocElement> = {}): DocElement => ({
  id: "doc/teil-1/kapitel-1/par-1/abs-2", type: "absatz", region: "body", parent_id: "p", children_ids: [], number: "2", marker: "(2)",
  title: null, original_text: "(2) Andere Rechtsvorschriften", content_text: "Andere Rechtsvorschriften", table: null, source_refs: ["#/texts/97"],
  docling_label: "text", pages: [6], provenance: [], uncertain: false, uncertainty_reasons: [], ...extra,
});

const review = (extra: Partial<ReviewView> = {}): ReviewView => ({
  document_id: "d", state: "pending_review", review_revision: 0, model_revision: 0, corrections: [], confirmations: [],
  corrected_element_ids: [], uncertain_element_ids: ["u1", "u2", "u3"], unresolved_uncertain_ids: ["u1", "u2", "u3"],
  validation: { model_revision: 0, generated: true, xsd_valid: true, xsd_errors: [], text_identical_to_reviewed_model: true,
    uncorrected_text_differences: [], corrected_elements: [], blocking_errors: [], xml_sha256: "abc" },
  can_approve: false, approval_blockers: ["3 uncertain element(s) have not been checked and confirmed."], approval: null,
  exports: [], original_export_superseded: false, structural_editing_supported: false, history: [], ...extra,
});

const noop = () => Promise.resolve(true);

describe("review helpers", () => {
  it("labels unreviewed, edited and approved documents", () => {
    expect(reviewBadge(review()).label).toBe("Unreviewed");
    const edited = review({ state: "in_review", corrections: [{ id: "c1" } as never] });
    expect(reviewBadge(edited)).toEqual({ label: "Edited, not approved (1 correction)", tone: "warn" });
    const ok = review({ state: "approved", approval: { model_revision: 3 } as never });
    expect(reviewBadge(ok)).toEqual({ label: "Approved (model revision 3)", tone: "ok" });
    expect(reviewBadge(review({ state: "changes_requested" })).label).toBe("Changes requested");
  });
  it("offers only the supported fields", () => {
    expect(editableFields(el())).toEqual(["marker", "content_text"]);
    expect(editableFields(el({ type: "paragraph", marker: "§ 1", title: "Zweck", content_text: "Zweck" }))).toEqual(["marker", "title"]);
    expect(editableFields(el({ type: "table" }))).toEqual([]);
    expect(editableFields(el({ marker: null }))).toEqual(["content_text"]);
  });
  it("walks the unchecked uncertain elements in document order", () => {
    const r = review({ unresolved_uncertain_ids: ["u1", "u3"] });
    expect(nextUnresolved(r, null)).toBe("u1");
    expect(nextUnresolved(r, "u1")).toBe("u3");
    expect(nextUnresolved(r, "u3")).toBe("u1"); // wraps around
    expect(nextUnresolved(review({ unresolved_uncertain_ids: [] }), "u1")).toBeNull();
  });
});

describe("ReviewEditor", () => {
  it("shows the original text, the editable fields and the save action", () => {
    const html = renderToStaticMarkup(<ElementDetail element={el()} warnings={[]} eId={null} onGoToPage={() => {}} review={review()} onSave={noop} onConfirm={noop} />);
    expect(html).toContain("Original text from the PDF (Docling, unchanged)");
    expect(html).toContain("Save correction");
    expect(html).toContain("Numbering marker");
    expect(html).not.toContain("Confirm as checked"); // not uncertain
  });
  it("marks corrected values as not verbatim and shows original → corrected", () => {
    const e = el({ content_text: "korrigiert", reviewed: { fields: { content_text: { original: "Andere Rechtsvorschriften", corrected: "korrigiert" } }, corrections: ["c1"], verbatim_from_source: false } });
    const html = renderToStaticMarkup(<ElementDetail element={e} warnings={[]} eId={null} onGoToPage={() => {}} review={review({ state: "in_review" })} onSave={noop} onConfirm={noop} />);
    expect(html).toContain("not verbatim from the PDF");
    expect(html).toContain("<del>Andere Rechtsvorschriften</del>");
    expect(html).toContain("<ins>korrigiert</ins>");
    expect(html).toContain("Reviewed text:");
  });
  it("asks for an explicit check of uncertain elements", () => {
    const e = el({ id: "u1", uncertain: true, uncertainty_reasons: ["text_after_list"] });
    const html = renderToStaticMarkup(<ReviewEditor element={e} review={review()} busy={false} onSave={noop} onConfirm={noop} onNext={() => {}} />);
    expect(html).toContain("Confirm as checked");
  });
  it("locks editing when approved and explains unsupported structural edits", () => {
    const approved = renderToStaticMarkup(<ReviewEditor element={el()} review={review({ state: "approved" })} busy={false} onSave={noop} onConfirm={noop} onNext={() => {}} />);
    expect(approved).toContain("Reopen the review to make changes");
    expect(approved).toMatch(/<input(?=[^>]*aria-label="Corrected marker")(?=[^>]*disabled="")[^>]*>/);
    expect(approved).toMatch(/<button[^>]*disabled=""[^>]*>Save correction/);
    const table = renderToStaticMarkup(<ReviewEditor element={el({ type: "table" })} review={review()} busy={false} onSave={noop} onConfirm={noop} onNext={() => {}} />);
    expect(table).toContain("Structural editing (moving, adding or deleting elements) is not supported yet");
  });
});

describe("ReviewPanel", () => {
  it("disables approval while blockers remain and lists them", () => {
    const html = renderToStaticMarkup(<ReviewPanel docId="d" review={review()} busy={false} selectedId={null} onSelect={() => {}} onDecide={() => {}} />);
    expect(html).toContain("Approval blocked");
    expect(html).toContain("3 uncertain element(s) have not been checked");
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Approve revision 0<\/button>/);
    expect(html).toContain("Go to next unchecked");
  });
  it("allows approval when nothing blocks and shows XSD status and downloads", () => {
    const r = review({ state: "in_review", can_approve: true, approval_blockers: [], unresolved_uncertain_ids: [], model_revision: 2 });
    const html = renderToStaticMarkup(<ReviewPanel docId="d" review={r} busy={false} selectedId={null} onSelect={() => {}} onDecide={() => {}} />);
    expect(html).not.toMatch(/<button[^>]*disabled=""[^>]*>Approve revision/);
    expect(html).toContain("Official OASIS XSD: valid");
    expect(html).toContain("/review/revisions/2/xml");
  });
  it("shows the approved revision and offers reopening", () => {
    const r = review({ state: "approved", approval: { review_revision: 9, model_revision: 2, model_sha256: "m", xml_sha256: "x", approved_at: "2026-10-27T12:00:00Z", note: null, confirmed_uncertain: 3, corrections: 1 } });
    const html = renderToStaticMarkup(<ReviewPanel docId="d" review={r} busy={false} selectedId={null} onSelect={() => {}} onDecide={() => {}} />);
    expect(html).toContain("Approved model revision 2");
    expect(html).toContain("Reopen review");
  });
});
