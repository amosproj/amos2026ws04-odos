import type { DocElement, EditableField, ReviewView } from "./types";

// Human review: status badge, editable fields, navigation between unresolved elements.

export const REVIEW_STATE_LABELS: Record<string, string> = {
  pending_review: "Unreviewed",
  in_review: "In review",
  changes_requested: "Changes requested",
  approved: "Approved",
};

/** Short status for the document bar: unreviewed / edited / approved. */
export function reviewBadge(r: ReviewView): { label: string; tone: "muted" | "warn" | "ok" } {
  if (r.state === "approved") return { label: `Approved (model revision ${r.approval?.model_revision ?? r.model_revision})`, tone: "ok" };
  if (r.state === "changes_requested") return { label: "Changes requested", tone: "warn" };
  if (r.corrections.length) return { label: `Edited, not approved (${r.corrections.length} correction${r.corrections.length > 1 ? "s" : ""})`, tone: "warn" };
  if (r.state === "in_review") return { label: "In review", tone: "warn" };
  return { label: "Unreviewed", tone: "muted" };
}

const NOT_EDITABLE = new Set(["document", "preamble", "conclusions", "table", "signature", "page_header", "page_footer", "picture"]);

/** Fields the backend accepts for this element (structural editing is not supported). */
export function editableFields(e: DocElement): EditableField[] {
  if (NOT_EDITABLE.has(e.type)) return [];
  const out: EditableField[] = [];
  if (e.marker != null) out.push("marker");
  if (e.title != null) out.push("title");
  if (!(e.title != null && e.content_text === e.title)) out.push("content_text");
  return out;
}

export const FIELD_LABELS: Record<EditableField, string> = { content_text: "Text", title: "Heading / title", marker: "Numbering marker" };

/** The next unresolved uncertain element after `current` (wrapping around), in document order. */
export function nextUnresolved(r: ReviewView, current: string | null): string | null {
  const list = r.unresolved_uncertain_ids;
  if (!list.length) return null;
  if (!current) return list[0];
  const order = r.uncertain_element_ids;
  const pos = order.indexOf(current);
  const after = list.find((id) => order.indexOf(id) > pos);
  return after ?? list[0];
}
