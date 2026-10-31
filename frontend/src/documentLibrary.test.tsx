import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { DeleteDialog } from "./components/DeleteDialog";
import { DocumentTable, RowMenu } from "./components/DocumentTable";
import { Toasts } from "./components/Toasts";
import {
  DeletionController, DEFAULT_SORT, docTypeLabel, filterDocuments, libraryMetrics, reviewLabel, routeFromHash, sortDocuments, statusLabel,
  type DeleteState,
} from "./documentLibrary";
import { fmtDateTime } from "./format";
import type { DeleteResult, DeletionPreview, DocumentStatus } from "./types";

const ID = "9fd773e3-12ff-4538-a7c3-59b10faef7f2";
const doc = (over: Partial<DocumentStatus> & { id: string }): DocumentStatus => ({
  filename: "doc.pdf", size_bytes: 2048, uploaded_at: "2026-10-27T10:00:00Z", status: "completed", stage: null, mode: null, outcome: "completed",
  message: null, error: null, started_at: null, finished_at: null, summary: {}, artifacts: [], ...over,
});
const DOCS: DocumentStatus[] = [
  doc({ id: "a", filename: "BDSG.pdf", uploaded_at: "2026-10-27T09:00:00Z", status: "completed", document_type: "german_law" }),
  doc({ id: "b", filename: "EuMaschinenbauverordnung.pdf", uploaded_at: "2026-10-29T12:00:00Z", status: "completed", document_type: "eu_regulation", review_state: "in_review" }),
  doc({ id: "c", filename: "MusterBauVerordnung.pdf", uploaded_at: "2026-10-28T08:00:00Z", status: "processing", stage: "extracting", outcome: null }),
  doc({ id: "d", filename: "notes.pdf", uploaded_at: "2026-10-26T08:00:00Z", status: "uploaded", outcome: null }),
  doc({ id: "e", filename: "broken.pdf", uploaded_at: "2026-10-25T08:00:00Z", status: "failed", outcome: null }),
  doc({ id: "f", filename: "Einkaufsliste.pdf", uploaded_at: "2026-10-24T08:00:00Z", status: "completed", outcome: "unsupported", document_type: "unknown" }),
];

describe("routes", () => {
  it("maps hashes to views and documents", () => {
    expect(routeFromHash("")).toEqual({ kind: "view", view: "documents" });
    expect(routeFromHash("#/")).toEqual({ kind: "view", view: "documents" });
    expect(routeFromHash("#/processing")).toEqual({ kind: "view", view: "processing" });
    expect(routeFromHash("#/reviews")).toEqual({ kind: "view", view: "reviews" });
    expect(routeFromHash(`#/doc/${ID}`)).toEqual({ kind: "doc", id: ID });
    expect(routeFromHash("#/doc/../../etc")).toEqual({ kind: "view", view: "documents" });
    expect(routeFromHash("#/nonsense")).toEqual({ kind: "view", view: "documents" });
  });
});

describe("filtering, sorting and metrics", () => {
  const f = (over = {}) => filterDocuments(DOCS, { query: "", status: "all", view: "documents", ...over }).map((d) => d.id);
  it("searches by document name, case-insensitively and trimmed", () => {
    expect(f({ query: "  verordnung " })).toEqual(["b", "c"]);
    expect(f({ query: "BDSG" })).toEqual(["a"]);
    expect(f({ query: "xyz" })).toEqual([]);
  });
  it("filters by status and combines with the search", () => {
    expect(f({ status: "completed" })).toEqual(["a", "b", "f"]);
    expect(f({ status: "failed" })).toEqual(["e"]);
    expect(f({ status: "completed", query: "eu" })).toEqual(["b"]);
    expect(f({ status: "queued" })).toEqual([]);
  });
  it("offers real Processing and Reviews views", () => {
    expect(f({ view: "processing" })).toEqual(["c", "e"]);
    expect(f({ view: "reviews" })).toEqual(["b"]);
  });
  it("sorts by most recently uploaded first by default", () => {
    expect(sortDocuments(DOCS, DEFAULT_SORT.key, DEFAULT_SORT.dir).map((d) => d.id)).toEqual(["b", "c", "a", "d", "e", "f"]);
    expect(sortDocuments(DOCS, "uploaded", "asc").map((d) => d.id)[0]).toBe("f");
    expect(sortDocuments(DOCS, "name", "asc").map((d) => d.filename)[0]).toBe("BDSG.pdf");
    expect(DOCS.map((d) => d.id)).toEqual(["a", "b", "c", "d", "e", "f"]); // input untouched
  });
  it("counts the metrics from the data", () => {
    expect(libraryMetrics(DOCS)).toEqual({ total: 6, completed: 3, active: 2, failed: 1 });
    expect(libraryMetrics([])).toEqual({ total: 0, completed: 0, active: 0, failed: 0 });
    expect(libraryMetrics([doc({ id: "x", status: "queued" }), doc({ id: "y", status: "queued" })]).active).toBe(2);
  });
});

describe("labels and dates", () => {
  it("shows recognised types and review state only where known", () => {
    expect(docTypeLabel(DOCS[1])).toBe("EU regulation");
    expect(docTypeLabel(DOCS[2])).toBeNull();
    expect(reviewLabel(DOCS[1])).toBe("In review");
    expect(reviewLabel(DOCS[0])).toBeNull();
    expect(statusLabel(DOCS[5])).toBe("Unsupported");
    expect(statusLabel(DOCS[4])).toBe("Failed");
  });
  it("formats dates in one consistent style", () => {
    expect(fmtDateTime("2026-10-29T13:32:00Z")).toMatch(/^\d{2} Oct 2026, \d{2}:\d{2}$/);
    expect(fmtDateTime("not a date")).toBe("—");
  });
});

describe("document table", () => {
  const render = (over = {}) =>
    renderToStaticMarkup(<DocumentTable docs={DOCS} view="documents" sort={DEFAULT_SORT} onSort={() => {}} menu={null} onMenu={() => {}} onOpen={() => {}} onDelete={() => {}} {...over} />);
  it("has the specified columns and one row per document linking to the workspace", () => {
    const html = render();
    for (const h of ["Document Name", "Document Type", "Uploaded", "Status"]) expect(html).toContain(h);
    expect(html).toContain('aria-sort="descending"'); // uploaded, newest first
    expect(html.match(/<tr data-doc-id=/g)).toHaveLength(6);
    expect(html).toContain('href="#/doc/b"');
    expect(html).toContain("EU regulation");
    expect(html).toContain("Not classified");
    expect(html).toContain("Processing · extracting");
    expect(html).toContain('aria-label="Actions for BDSG.pdf"');
    expect(html).not.toContain('scope="col">Review');
  });
  it("adds the review column in the Reviews view", () => {
    const html = render({ view: "reviews", docs: [DOCS[1]] });
    expect(html).toContain("Review</th>");
    expect(html).toContain("In review");
  });
  it("renders the action menu with Open and Delete", () => {
    const html = renderToStaticMarkup(<RowMenu menu={{ doc: DOCS[0], top: 100, right: 20 }} onClose={() => {}} onOpen={() => {}} onDelete={() => {}} />);
    expect(html).toContain('role="menu"');
    expect(html).toContain("Open Document");
    expect(html).toContain("Delete Document");
    expect(html).toContain("top:100px");
    const open = render({ menu: { doc: DOCS[0], top: 100, right: 20 } });
    expect(open).toContain('aria-expanded="true"');
    expect(open).toContain('class="menu-open"');
  });
});

// ---- deletion -----------------------------------------------------------------------------------------------------
const preview = (over: Partial<DeletionPreview> = {}): DeletionPreview => ({
  id: "a", filename: "BDSG.pdf", can_delete: true, blocked_reason: null, total_files: 12, total_bytes: 2_400_000,
  items: [
    { category: "original_pdf", label: "Uploaded PDF", files: 1, size_bytes: 267512, details: [] },
    { category: "generated_artifacts", label: "Generated artifacts (extraction, structure, Akoma Ntoso and AKN4EU exports, reports)", files: 7, size_bytes: 2_000_000, details: ["document_akn.xml", "document_model.json"] },
    { category: "review", label: "Human review (corrections, confirmations, approval and all review revisions)", files: 3, size_bytes: 9000, details: ["2 review revision(s)", "1 correction(s)"] },
    { category: "metadata", label: "Document record (status and processing summary)", files: 1, size_bytes: 900, details: [] },
  ],
  ...over,
});
const result = (): DeleteResult => ({ id: "a", filename: "BDSG.pdf", deleted: true, removed: preview() });

function harness(api: Partial<{ p: () => Promise<DeletionPreview>; d: () => Promise<DeleteResult> }> = {}) {
  const deletionPreview = vi.fn(api.p ?? (() => Promise.resolve(preview())));
  const deleteDocument = vi.fn(api.d ?? (() => Promise.resolve(result())));
  const states: DeleteState[] = [];
  const onDeleted = vi.fn();
  const c = new DeletionController({ deletionPreview, deleteDocument }, (s) => states.push(s), onDeleted);
  return { c, deletionPreview, deleteDocument, states, onDeleted };
}

describe("delete confirmation flow", () => {
  it("opening the dialog only reads the preview; cancelling changes nothing", async () => {
    const h = harness();
    await h.c.open(DOCS[0]);
    expect(h.states.map((s) => s.phase)).toEqual(["loading", "confirm"]);
    expect(h.deletionPreview).toHaveBeenCalledWith("a");
    h.c.cancel();
    expect(h.c.state.phase).toBe("idle");
    expect(h.deleteDocument).not.toHaveBeenCalled(); // no change on cancellation
    expect(h.onDeleted).not.toHaveBeenCalled();
  });
  it("confirming deletes exactly the selected document once, with a loading phase", async () => {
    const h = harness();
    await h.c.open(DOCS[0]);
    const done = h.c.confirm();
    expect(h.c.state.phase).toBe("deleting"); // loading indicator while the request runs
    expect(await done).toBe(true);
    expect(h.deleteDocument).toHaveBeenCalledTimes(1);
    expect(h.deleteDocument).toHaveBeenCalledWith("a");
    expect(h.onDeleted).toHaveBeenCalledWith(expect.objectContaining({ filename: "BDSG.pdf", deleted: true }));
    expect(h.c.state.phase).toBe("idle");
  });
  it("a failed deletion keeps the dialog open with the real error and reports no success", async () => {
    const h = harness({ d: () => Promise.reject(new Error("The document could not be fully deleted. It is still listed; try again.")) });
    await h.c.open(DOCS[0]);
    expect(await h.c.confirm()).toBe(false);
    expect(h.onDeleted).not.toHaveBeenCalled();
    expect(h.c.state).toMatchObject({ phase: "confirm", error: expect.stringContaining("still listed") });
    expect(h.c.canConfirm).toBe(true); // can be retried
  });
  it("cannot confirm before the preview has loaded, when blocked, or when the preview failed", async () => {
    const blocked = harness({ p: () => Promise.resolve(preview({ can_delete: false, blocked_reason: "This document is queued or being processed." })) });
    await blocked.c.open(DOCS[0]);
    expect(blocked.c.canConfirm).toBe(false);
    expect(await blocked.c.confirm()).toBe(false);
    expect(blocked.deleteDocument).not.toHaveBeenCalled();
    const failed = harness({ p: () => Promise.reject(new Error("No document with this id.")) });
    await failed.c.open(DOCS[0]);
    expect(failed.c.state).toMatchObject({ phase: "confirm", preview: null, error: "No document with this id." });
    expect(await failed.c.confirm()).toBe(false);
    expect(failed.deleteDocument).not.toHaveBeenCalled();
    const idle = harness();
    expect(await idle.c.confirm()).toBe(false);
    expect(idle.deleteDocument).not.toHaveBeenCalled();
  });
  it("ignores cancel while deleting and a second open while a dialog is showing", async () => {
    let finish!: (r: DeleteResult) => void;
    const h = harness({ d: () => new Promise<DeleteResult>((r) => { finish = r; }) });
    await h.c.open(DOCS[0]);
    const done = h.c.confirm();
    h.c.cancel();
    expect(h.c.state.phase).toBe("deleting");
    await h.c.open(DOCS[1]);
    expect(h.deletionPreview).toHaveBeenCalledTimes(1);
    finish(result());
    await done;
    expect(h.deleteDocument).toHaveBeenCalledTimes(1);
  });
});

describe("delete dialog", () => {
  const dlg = (state: DeleteState) => renderToStaticMarkup(<DeleteDialog state={state} onCancel={() => {}} onConfirm={() => {}} />);
  it("renders nothing when idle", () => expect(dlg({ phase: "idle" })).toBe(""));
  it("names the file, says it is permanent and lists what is removed", () => {
    const html = dlg({ phase: "confirm", doc: DOCS[0], preview: preview(), error: null });
    expect(html).toContain('role="dialog"');
    expect(html).toContain('aria-modal="true"');
    expect(html).toContain("BDSG.pdf");
    expect(html).toContain("permanently delete");
    expect(html).toContain("This cannot be undone");
    for (const s of ["Uploaded PDF", "Generated artifacts", "Human review", "2 review revision(s)", "document_akn.xml", "Document record"]) expect(html).toContain(s);
    expect(html).toContain("Total: 12 files, 2.3 MB");
    expect(html).toContain("Other documents, source code, schemas and shared settings are not affected.");
    expect(html).toContain("Cancel");
    expect(html).toContain("Delete permanently");
    expect(html).not.toMatch(/data-testid="delete-confirm"[^>]*disabled/);
  });
  it("shows a loading state while the preview loads and disables the delete button", () => {
    const html = dlg({ phase: "loading", doc: DOCS[0] });
    expect(html).toContain("Checking what is stored");
    expect(html).toMatch(/disabled=""[^>]*data-testid="delete-confirm"|data-testid="delete-confirm"[^>]*disabled=""/);
  });
  it("shows a spinner and disables both buttons during deletion", () => {
    const html = dlg({ phase: "deleting", doc: DOCS[0], preview: preview() });
    expect(html).toContain("Deleting…");
    expect(html.match(/disabled=""/g)?.length).toBeGreaterThanOrEqual(2);
  });
  it("shows the blocking reason and API errors", () => {
    const blocked = dlg({ phase: "confirm", doc: DOCS[2], preview: preview({ can_delete: false, blocked_reason: "This document is queued or being processed. Wait until processing has finished." }), error: null });
    expect(blocked).toContain("queued or being processed");
    expect(blocked).toMatch(/data-testid="delete-confirm"[^>]*disabled=""|disabled=""[^>]*data-testid="delete-confirm"/);
    expect(dlg({ phase: "confirm", doc: DOCS[0], preview: preview(), error: "Cannot reach the ODOS API." })).toContain("Cannot reach the ODOS API.");
  });
});

describe("toasts", () => {
  it("renders success as status and errors as alerts", () => {
    const html = renderToStaticMarkup(<Toasts toasts={[{ id: 1, kind: "success", text: "“a.pdf” was permanently deleted" }, { id: 2, kind: "error", text: "failed" }]} onDismiss={() => {}} />);
    expect(html).toContain('role="status"');
    expect(html).toContain('role="alert"');
    expect(html).toContain("permanently deleted");
    expect(renderToStaticMarkup(<Toasts toasts={[]} onDismiss={() => {}} />)).toBe("");
  });
});
