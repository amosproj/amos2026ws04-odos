import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import type { StoredDocument } from "../demo/live";
import { ProcessingStatus } from "./ProcessingStatus";
import { RecentDocumentsView, canDelete, canOpen, uploadRanks, type DocumentsState } from "./RecentDocuments";

type View = Parameters<typeof RecentDocumentsView>[0];
const noop = () => {};
const render = (state: DocumentsState, extra: Partial<View> = {}) =>
  renderToStaticMarkup(<RecentDocumentsView state={state} onRefresh={noop} onOpen={noop} onAskDelete={noop} onCancelDelete={noop} onConfirmDelete={noop} {...extra} />);
const doc = (id: string, filename: string, status: StoredDocument["status"], created_at = "2026-11-11T10:30:00Z"): StoredDocument => ({ id, filename, status, created_at });
const ready = (...documents: StoredDocument[]): DocumentsState => ({ kind: "ready", documents });
const rows = (html: string) => html.split('<li class="demo-docitem">').slice(1);
const STATUSES = ["completed", "failed", "unsupported", "processing", "queued"] as const;
/** The opening tag of the button with this accessible name. */
const tag = (html: string, label: string) => new RegExp(`<button[^>]*aria-label="${label}"[^>]*>`).exec(html)![0];

describe("recent documents: states", () => {
  it("shows a loading state and disables Refresh meanwhile", () => {
    const html = render({ kind: "loading" });
    expect(html).toContain("Loading documents…");
    expect(html).toContain('aria-busy="true"');
    expect(tag(html, "Refresh")).toContain('disabled=""');
    expect(html).not.toContain("<ul");
  });

  it("shows an empty state without any invented records", () => {
    const html = render(ready());
    expect(html).toContain("No documents yet");
    expect(html).not.toMatch(/<ul|<li|\.pdf/);
  });

  it("shows the backend's error with a way to try again", () => {
    const html = render({ kind: "error", message: "The ODOS database is not available. Check that PostgreSQL is running and try again." });
    expect(html).toContain('role="alert"');
    expect(html).toContain("The ODOS database is not available.");
    expect(html).toMatch(/<button[^>]*>Try again<\/button>/);
    expect(html).not.toContain("<ul");
  });
});

describe("recent documents: list", () => {
  const all = ready(
    doc("a", "Bauordnung.pdf", "completed"),
    doc("b", "Scan.pdf", "failed", "2026-11-10T08:00:00Z"),
    doc("c", "Notiz.pdf", "unsupported"),
    doc("d", "Laufend.pdf", "processing"),
    doc("e", "Wartend.pdf", "queued"),
  );

  it("lists filename, status and upload date in the order given", () => {
    const items = rows(render(all));
    expect(items).toHaveLength(5);
    expect(items.map((i) => /class="demo-docname[^"]*"[^>]*>([^<]+)</.exec(i)![1])).toEqual(["Bauordnung.pdf", "Scan.pdf", "Notiz.pdf", "Laufend.pdf", "Wartend.pdf"]);
    expect(items.map((i) => />([^<]+)<\/span><time/.exec(i)![1])).toEqual(["Completed", "Failed", "Not recognized", "Processing", "Queued"]);
    expect(items.map((i) => /class="demo-status (\w+)"/.exec(i)![1])).toEqual(["ok", "danger", "warn", "busy", "busy"]);
    expect(items[1]).toContain('dateTime="2026-11-10T08:00:00Z"');
  });

  it("offers Open only for completed documents", () => {
    expect(STATUSES.map((s) => canOpen(doc("x", "x.pdf", s)))).toEqual([true, false, false, false, false]);
    const items = rows(render(all));
    expect(items.map((i) => i.includes('aria-label="Open '))).toEqual([true, false, false, false, false]);
    expect(items[0]).toContain('aria-label="Open Bauordnung.pdf"');
  });

  it("offers Delete for finished documents only: the backend refuses to delete a running job", () => {
    expect(STATUSES.map((s) => canDelete(doc("x", "x.pdf", s)))).toEqual([true, true, true, false, false]);
    const items = rows(render(all));
    expect(items.map((i) => i.includes('aria-label="Delete '))).toEqual([true, true, true, false, false]);
    expect(items[1]).toContain('aria-label="Delete Scan.pdf"');
  });

  it("has one Open control per document: the name, with a decorative icon (the row is made clickable by CSS)", () => {
    const html = render(ready(doc("a", "A.pdf", "completed"), doc("b", "B.pdf", "failed")));
    expect(html.match(/aria-label="Open /g)).toHaveLength(1);
    const [first, second] = rows(html);
    expect(first).toMatch(/class="demo-openicon" aria-hidden="true"/); // an icon, not a second button
    expect(first.match(/<button/g)).toHaveLength(2); // Open and Delete
    expect(second).not.toContain("demo-openicon");
    expect(second.match(/<button/g)).toHaveLength(1); // Delete only
  });

  it("offers no actions where the callbacks are missing", () => {
    expect(renderToStaticMarkup(<RecentDocumentsView state={all} onRefresh={noop} />)).not.toMatch(/aria-label="(Open|Delete) /);
  });

  it("disables Open while a PDF is being processed", () => {
    const one = ready(doc("a", "A.pdf", "completed"));
    expect(tag(render(one), "Open A.pdf")).not.toContain("disabled");
    expect(tag(render(one, { openDisabled: true }), "Open A.pdf")).toContain('disabled=""');
  });

  it("locks every action while a document opens", () => {
    const html = render(ready(doc("a", "A.pdf", "completed"), doc("b", "B.pdf", "completed")), { openingId: "a" });
    expect(html).toContain("Opening…");
    for (const label of ["Open A.pdf", "Open B.pdf", "Delete A.pdf", "Delete B.pdf"]) expect(tag(html, label)).toContain('disabled=""');
  });

  it("shows why a document could not be opened, at that document", () => {
    const items = rows(render(ready(doc("a", "A.pdf", "completed"), doc("b", "B.pdf", "completed")), { openError: { id: "b", message: "B.pdf could not be opened. The original PDF is no longer available." } }));
    expect(items[0]).not.toContain('role="alert"');
    expect(items[1]).toContain("The original PDF is no longer available.");
  });

  it("shows file names as text, escaped", () => {
    const html = render(ready(doc("a", '<img src=x onerror="alert(1)">.pdf', "failed")));
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;img");
  });

  it("shows a Type column only when the API provides document types", () => {
    const without = render(ready(doc("a", "A.pdf", "completed")));
    expect(without).not.toMatch(/demo-type|>Type</);
    const typed: StoredDocument[] = [
      { ...doc("a", "Gesetz.pdf", "completed"), document_type: "de_legislation" },
      { ...doc("b", "Verordnung.pdf", "completed"), document_type: "eu_regulation" },
      { ...doc("c", "Scan.pdf", "failed"), document_type: null },
    ];
    const html = render(ready(...typed));
    expect(html).toContain(">Type<");
    expect(rows(html).map((i) => /class="demo-type">([^<]+)</.exec(i)![1])).toEqual(["German law", "EU regulation", "—"]);
    expect(rows(html).map((i) => />([^<]+)<\/span><time/.exec(i)![1])).toEqual(["Completed", "Completed", "Failed"]); // the other columns are unaffected
  });

  it("labels the column heads for the sighted and hides them from screen readers (every row says what it is)", () => {
    const html = render(ready(doc("a", "A.pdf", "completed")));
    const head = /<div class="demo-listhead[^"]*" aria-hidden="true">([\s\S]*?)<\/div>/.exec(html)![1];
    expect(head.replace(/<[^>]+>/g, "|").split("|").filter(Boolean)).toEqual(["Name", "Status", "Uploaded"]);
  });

  it("shows nothing but what the list API provides: no id, no storage key", () => {
    const html = render(ready(doc("0f3a9c1d2b4e", "Bauordnung.pdf", "completed")));
    expect(html).not.toMatch(/0f3a9c1d2b4e|source\.pdf|postgres|password/i);
  });
});

describe("duplicate file names: ranking uploads", () => {
  const at = (id: string, filename: string, created_at: string) => doc(id, filename, "completed", created_at);
  const ranks = (documents: StoredDocument[]) => Object.fromEntries(uploadRanks(documents));

  it("gives a unique file name no label", () => {
    expect(ranks([at("a", "Solo.pdf", "2026-11-12T10:00:00Z"), at("b", "Other.pdf", "2026-11-12T11:00:00Z")])).toEqual({});
    expect(ranks([])).toEqual({});
  });

  it("marks the newest of two identical file names as latest and the other as earlier", () => {
    const list = [at("old", "Gesetz.pdf", "2026-11-12T00:02:00Z"), at("new", "Gesetz.pdf", "2026-11-12T15:32:00Z")];
    expect(ranks(list)).toEqual({ new: "latest", old: "earlier" });
    expect(ranks([...list].reverse())).toEqual({ new: "latest", old: "earlier" }); // whatever the order of the list
  });

  it("marks exactly one latest upload and all others earlier among three or more", () => {
    const list = [
      at("c", "Gesetz.pdf", "2026-11-12T09:00:00Z"), at("a", "Gesetz.pdf", "2026-11-10T09:00:00Z"),
      at("d", "Gesetz.pdf", "2026-11-13T09:00:00Z"), at("b", "Gesetz.pdf", "2026-11-11T09:00:00Z"),
    ];
    expect(ranks(list)).toEqual({ d: "latest", c: "earlier", b: "earlier", a: "earlier" });
  });

  it("orders identical timestamps by id: the same answer for every list order", () => {
    const t = "2026-11-12T10:00:00.123456Z";
    const list = [at("b", "Gesetz.pdf", t), at("a", "Gesetz.pdf", t), at("c", "Gesetz.pdf", t)];
    const expected = { c: "latest", b: "earlier", a: "earlier" }; // the greater id counts as newer
    for (const order of [[0, 1, 2], [2, 1, 0], [1, 2, 0], [1, 0, 2]]) expect(ranks(order.map((i) => list[i]))).toEqual(expected);
  });

  it("tells uploads apart that differ by less than a millisecond", () => {
    const list = [at("x", "Gesetz.pdf", "2026-11-12T10:00:00.000002Z"), at("y", "Gesetz.pdf", "2026-11-12T10:00:00.000001Z")];
    expect(ranks(list)).toEqual({ x: "latest", y: "earlier" });
  });

  it("ranks each file name on its own and groups only identical names", () => {
    const list = [
      at("a1", "A.pdf", "2026-11-10T10:00:00Z"), at("b1", "B.pdf", "2026-11-14T10:00:00Z"), at("a2", "A.pdf", "2026-11-11T10:00:00Z"),
      at("b2", "B.pdf", "2026-11-09T10:00:00Z"), at("c", "C.pdf", "2026-11-12T10:00:00Z"), at("lower", "a.pdf", "2026-11-15T10:00:00Z"),
    ];
    expect(ranks(list)).toEqual({ a2: "latest", a1: "earlier", b1: "latest", b2: "earlier" }); // "a.pdf" is another name than "A.pdf"
  });

  it("ranks by upload time, not by status", () => {
    const list = [doc("old", "Gesetz.pdf", "completed", "2026-11-10T10:00:00Z"), doc("new", "Gesetz.pdf", "failed", "2026-11-12T10:00:00Z")];
    expect(ranks(list)).toEqual({ new: "latest", old: "earlier" });
  });
});

describe("duplicate file names: in the list", () => {
  const dup = (html: string) => rows(html).map((i) => /class="demo-dup (\w+)">([^<]+)</.exec(i)?.slice(1, 3) ?? null);
  const docs = [
    doc("n", "Gesetz.pdf", "completed", "2026-11-12T15:32:00Z"),
    doc("o", "Gesetz.pdf", "failed", "2026-11-12T00:02:00Z"),
    doc("s", "Einzeln.pdf", "completed", "2026-11-11T10:00:00Z"),
  ];
  const list = ready(...docs);

  it("shows a small label under each duplicate and none under a unique file name", () => {
    expect(dup(render(list))).toEqual([["latest", "Latest upload"], ["earlier", "Earlier upload"], null]);
  });

  it("keeps the file name, status and upload date as they were, and does not repeat the date in the label", () => {
    const items = rows(render(list));
    expect(items.map((i) => /class="demo-docname[^"]*"[^>]*>([^<]+)</.exec(i)![1])).toEqual(["Gesetz.pdf", "Gesetz.pdf", "Einzeln.pdf"]);
    expect(items.map((i) => />([^<]+)<\/span><time/.exec(i)![1])).toEqual(["Completed", "Failed", "Completed"]);
    expect(items[0]).toContain('dateTime="2026-11-12T15:32:00Z"');
    expect(/class="demo-dup[^"]*">([^<]+)</.exec(items[0])![1]).toBe("Latest upload"); // only the words; the date has its column
    expect(items[0].match(/<time/g)).toHaveLength(1);
  });

  it("puts the label under the name, inside the same cell, so the row structure is unchanged", () => {
    const [first, , third] = rows(render(list));
    expect(first).toMatch(/<span class="demo-doctext"><span class="demo-docname">Gesetz\.pdf<\/span><span class="demo-dup latest">Latest upload<\/span><\/span>/);
    expect(third).toMatch(/<span class="demo-doctext"><span class="demo-docname">Einzeln\.pdf<\/span><\/span>/);
    expect(first.match(/<button/g)).toHaveLength(2); // still Open and Delete only
  });

  it("names the upload in the accessible names, so identical file names can be told apart; unique names stay as before", () => {
    const html = render(list);
    expect(html).toMatch(/aria-label="Open Gesetz\.pdf \(latest upload, [^"]+\)"/);
    expect(html).toMatch(/aria-label="Delete Gesetz\.pdf \(latest upload, [^"]+\)"/);
    expect(html).toMatch(/aria-label="Delete Gesetz\.pdf \(earlier upload, [^"]+\)"/);
    expect(html).toContain('aria-label="Open Einzeln.pdf"');
    expect(html).toContain('aria-label="Delete Einzeln.pdf"');
    expect(html).not.toMatch(/aria-label="Open Gesetz\.pdf"/);
  });

  it("says which upload is about to be deleted", () => {
    const [first, second] = rows(render(list, { confirmId: "o" }));
    expect(first).not.toContain("demo-confirm");
    expect(second).toMatch(/Delete <strong[^>]*>Gesetz\.pdf<\/strong> \(earlier upload, [^)]+\)\?/);
    const unique = rows(render(list, { confirmId: "s" }))[2];
    expect(unique).toMatch(/Delete <strong[^>]*>Einzeln\.pdf<\/strong>\? The stored PDF/); // no suffix for a unique name
  });

  it("labels the documents that a search leaves in the list the same way", () => {
    const withOther = ready(...docs, doc("m", "Maschinen.pdf", "completed", "2026-11-09T10:00:00Z"));
    expect(dup(render(withOther, { query: "gesetz", onQueryChange: noop }))).toEqual([["latest", "Latest upload"], ["earlier", "Earlier upload"]]);
    expect(dup(render(withOther, { query: "maschinen", onQueryChange: noop }))).toEqual([null]);
    expect(dup(render(withOther, { query: "", onQueryChange: noop }))).toEqual([["latest", "Latest upload"], ["earlier", "Earlier upload"], null, null]);
  });

  it("does not treat names that differ in case as duplicates", () => {
    const html = render(ready(doc("a", "Gesetz.pdf", "completed", "2026-11-12T10:00:00Z"), doc("b", "gesetz.pdf", "completed", "2026-11-11T10:00:00Z")), { query: "gesetz", onQueryChange: noop });
    expect(dup(html)).toEqual([null, null]);
  });
});

describe("recent documents: search", () => {
  const list = ready(doc("a", "Bauordnung.pdf", "completed"), doc("b", "Maschinen.pdf", "failed"), doc("c", "BAUGESETZ.pdf", "completed"));
  const names = (html: string) => rows(html).map((i) => /class="demo-docname[^"]*"[^>]*>([^<]+)</.exec(i)![1]);

  it("offers a search field once there are documents to search", () => {
    const input = /<input type="search"[^>]*>/.exec(render(list, { query: "", onQueryChange: noop }))![0];
    expect(input).toContain('aria-label="Search documents"');
    expect(input).toContain('placeholder="Search documents…"');
    expect(render(ready(), { onQueryChange: noop })).not.toContain('type="search"'); // nothing to search
    expect(render({ kind: "loading" }, { onQueryChange: noop })).not.toContain('type="search"');
    expect(render(list)).not.toContain('type="search"'); // and none where nothing handles it
  });

  it("filters by file name, ignoring case and surrounding spaces", () => {
    expect(names(render(list, { query: "bau", onQueryChange: noop }))).toEqual(["Bauordnung.pdf", "BAUGESETZ.pdf"]);
    expect(names(render(list, { query: "  MASCH ", onQueryChange: noop }))).toEqual(["Maschinen.pdf"]);
    expect(names(render(list, { query: "", onQueryChange: noop }))).toHaveLength(3);
  });

  it("says when nothing matches, without claiming the library is empty", () => {
    const html = render(list, { query: "zzz", onQueryChange: noop });
    expect(html).toContain("No documents match “zzz”.");
    expect(html).not.toMatch(/No documents yet|<ul/);
  });
});

describe("recent documents: delete confirmation", () => {
  const two = ready(doc("a", "Erste.pdf", "completed"), doc("b", "Zweite.pdf", "failed"));

  it("asks nothing until Delete is pressed", () => {
    expect(render(two)).not.toMatch(/Delete document|Cancel|demo-confirm/);
  });

  it("names the document, warns that it is permanent and offers Cancel and a clearly labelled confirmation", () => {
    const items = rows(render(two, { confirmId: "b" }));
    expect(items[0]).not.toContain("demo-confirm"); // only the selected document
    expect(items[1]).toContain(">Zweite.pdf</strong>");
    expect(items[1]).toMatch(/permanently[\s\S]*cannot be undone/);
    expect(items[1]).toMatch(/<button[^>]*>Delete document<\/button>/);
    expect(items[1]).toMatch(/<button[^>]*>Cancel<\/button>/);
  });

  it("shows progress while deleting and blocks every action, so nothing can be deleted twice", () => {
    const html = render(two, { confirmId: "b", deletingId: "b" });
    const [first, second] = rows(html);
    expect(second).toContain("Deleting…");
    expect(second).toMatch(/<button[^>]*aria-busy="true"[^>]*>/);
    for (const button of second.match(/<button[^>]*>/g)!) expect(button).toContain('disabled=""'); // Delete (trash), Delete document, Cancel
    expect(tag(first, "Open Erste.pdf")).toContain('disabled=""');
    expect(tag(first, "Delete Erste.pdf")).toContain('disabled=""');
    expect(tag(html, "Refresh")).toContain('disabled=""');
  });

  it("shows a failed deletion with the backend's reason and keeps the document listed", () => {
    const html = render(two, { confirmId: "b", deleteError: { id: "b", message: "Cannot delete a running job." } });
    expect(rows(html)[1]).toContain("Cannot delete a running job.");
    expect(html).toContain("Zweite.pdf");
  });
});

describe("processing status", () => {
  it("states the stage in words with an indeterminate progress bar", () => {
    const html = renderToStaticMarkup(<ProcessingStatus stage="extracting" />);
    expect(html).toContain("Analyzing document structure…");
    expect(html).toContain('role="status"');
    expect(html).toMatch(/role="progressbar"/);
    expect(html).not.toMatch(/aria-valuenow|aria-valuemax|\d+\s*%|Docling/); // no invented progress
  });

  it("follows the backend's stage", () => {
    expect(renderToStaticMarkup(<ProcessingStatus stage="uploading" />)).toContain("Uploading document…");
    expect(renderToStaticMarkup(<ProcessingStatus stage="normalizing" />)).toContain("Preparing structured legal data…");
    expect(renderToStaticMarkup(<ProcessingStatus stage="completed" />)).toContain("Document processing complete.");
  });
});
