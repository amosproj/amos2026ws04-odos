// @vitest-environment jsdom
// Real clicks on the whole dashboard (the other tests render static markup): the app runs against a fake backend that
// answers like odos.api and records every request.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { el, modelOf } from "../testing";
import DemoApp from "./DemoApp";
import type { Job, StoredDocument } from "./live";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("../components/PdfViewer", () => ({
  PdfViewer: (p: { url: string }) => <div className="pdf-stub" data-url={p.url} />,
}));

const model = { ...modelOf([el("doc", "document", null, [], { region: "document" })]), metadata: { title: "Beispielgesetz" } };
const legal = { schemaVersion: "2.0", title: "Beispielgesetz", frontMatter: [], tableOfContents: [], structure: [] };
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
const stored = (id: string, filename: string, status: StoredDocument["status"] = "completed"): StoredDocument => ({ id, filename, status, created_at: "2026-11-11T10:00:00Z" });
const jobOf = (id: string, status: Job["status"], extra: Partial<Job> = {}): Job => ({ id, filename: "Neu.pdf", status, stage: null, message: null, persistent: true, ...extra });
const deferred = <T,>() => { let resolve!: (v: T) => void; const promise = new Promise<T>((r) => { resolve = r; }); return { promise, resolve }; };

/** Answers like odos.api. `polls` are the states a newly uploaded job goes through (the last one repeats). */
function fakeBackend(docs: StoredDocument[], polls: Job[] = []) {
  const backend = {
    docs,
    calls: [] as string[],
    deleteAnswer: (_id: string): Promise<Response> | Response => new Response(null, { status: 204 }),
    pdfAnswer: (): Response => new Response("%PDF-1.7"),
    count: (prefix: string) => backend.calls.filter((c) => c.startsWith(prefix)).length,
  };
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    backend.calls.push(`${method} ${url}`);
    if (url === "/api/documents") return json(backend.docs);
    if (method === "POST" && url === "/api/jobs") return json(jobOf("new1", "queued"), 202);
    if (method === "DELETE") {
      const id = url.split("/").pop()!;
      const answer = await backend.deleteAnswer(id);
      if (answer.ok) backend.docs = backend.docs.filter((d) => d.id !== id);
      return answer;
    }
    if (url.endsWith("/pdf")) return backend.pdfAnswer();
    if (url.endsWith("/files/document_model.json")) return json(model);
    if (url.endsWith("/files/document.json")) return json(legal);
    const id = /\/api\/jobs\/([^/]+)$/.exec(url)?.[1];
    if (id === "new1") return json(polls.length > 1 ? polls.shift() : polls[0]);
    const doc = backend.docs.find((d) => d.id === id);
    return doc ? json(jobOf(doc.id, doc.status, { filename: doc.filename })) : json({ detail: "Unknown job." }, 404);
  }));
  return backend;
}

let host: HTMLElement;
let root: Root;

const settle = async () => { for (let i = 0; i < 12; i++) await act(async () => { await Promise.resolve(); }); };
const mount = async () => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => { root.render(<DemoApp />); });
  await settle();
};
const text = () => host.textContent ?? "";
const button = (name: string) => [...host.querySelectorAll("button")].find((b) => (b.getAttribute("aria-label") ?? b.textContent ?? "").trim() === name);
const must = (name: string) => { const b = button(name); if (!b) throw new Error(`no button "${name}" in: ${text()}`); return b; };
const click = async (name: string) => { const b = must(name); await act(async () => { b.click(); }); await settle(); };
const choose = async (file: File) => {
  const input = host.querySelector<HTMLInputElement>('input[type="file"]')!;
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  await act(async () => { input.dispatchEvent(new Event("change", { bubbles: true })); });
};
const pdf = (name = "Neu.pdf") => new File(["%PDF-1.7"], name, { type: "application/pdf" });
const tick = async (ms = 1000) => { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); await settle(); };

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => "blob:test");
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("processing an upload", () => {
  it("creates exactly one job however often Process is pressed, shows no result before the backend confirms, and a list refresh does not interrupt it", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const backend = fakeBackend([stored("old", "Alt.pdf")], [jobOf("new1", "processing", { stage: "extracting" }), jobOf("new1", "processing", { stage: "normalizing" }), jobOf("new1", "completed")]);
    await mount();
    await choose(pdf());

    const process = must("Process document");
    await act(async () => { process.click(); process.click(); process.click(); });
    await settle();
    expect(backend.count("POST")).toBe(1);
    expect(must("Processing…").disabled).toBe(true);
    expect(host.querySelector('[role="progressbar"]')).not.toBeNull();

    await tick(); // the first poll: extracting
    expect(text()).toContain("Analyzing document structure…");
    expect(text()).not.toContain("Back to documents"); // not complete: no result yet
    expect(host.querySelector(".pdf-stub")).toBeNull();

    await click("Refresh"); // reloads the list ...
    expect(backend.count("GET /api/documents")).toBe(2);
    expect(text()).toContain("Analyzing document structure…"); // ... while the job runs on
    expect(host.querySelector('[role="progressbar"]')).not.toBeNull();
    expect(button("Open Alt.pdf")?.disabled).toBe(true); // nothing else can be opened meanwhile

    await tick(); // normalizing
    expect(text()).toContain("Preparing structured legal data…");
    expect(text()).not.toContain("Back to documents");
    await tick(); // completed
    expect(text()).toContain("Back to documents");
    expect(host.querySelector(".pdf-stub")?.getAttribute("data-url")).toBe("blob:test");
    expect(backend.count("POST")).toBe(1);
    expect(backend.calls.findIndex((c) => c.includes("/files/"))).toBeGreaterThan(backend.calls.lastIndexOf("GET /api/jobs/new1")); // results only after the last poll
  });

  it("refuses a file that is not a PDF without creating a job", async () => {
    const backend = fakeBackend([]);
    await mount();
    await choose(new File(["hello"], "notes.txt", { type: "text/plain" }));
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("Only PDF files");
    expect(must("Process document").disabled).toBe(true);
    expect(backend.count("POST")).toBe(0);
  });

  it("shows a failed job with a retry that starts a new job only when pressed", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const backend = fakeBackend([], [jobOf("new1", "failed", { message: "The PDF could not be processed." })]);
    await mount();
    await choose(pdf());
    await click("Process document");
    await tick();
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("Processing failed");
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("The PDF could not be processed.");
    expect(text()).not.toContain("Back to documents");
    expect(backend.count("POST")).toBe(1); // nothing retried by itself
    await click("Try again");
    expect(backend.count("POST")).toBe(2);
  });
});

describe("reopening a stored document", () => {
  it("opens it without a new job or processing, and Back returns to the refreshed list", async () => {
    const backend = fakeBackend([stored("a", "Alt.pdf"), stored("b", "Anders.pdf")]);
    await mount();
    expect(text()).toContain("Alt.pdf");
    await click("Open Alt.pdf");
    expect(text()).toContain("Back to documents");
    expect(host.querySelector(".pdf-stub")?.getAttribute("data-url")).toBe("blob:test"); // the stored PDF
    expect(backend.count("POST")).toBe(0);
    expect(backend.calls).toContain("GET /api/jobs/a/pdf");
    expect(backend.calls).toContain("GET /api/jobs/a/files/document.json");

    await click("Back to documents");
    expect(text()).toContain("Document library");
    expect(text()).toContain("Anders.pdf");
    expect(backend.count("GET /api/documents")).toBe(2); // the list is read again
    expect(backend.count("POST")).toBe(0);
    expect(backend.count("DELETE")).toBe(0); // and Back never deletes a stored document
    expect(backend.docs).toHaveLength(2);
  });

  it("stays on the dashboard and says what is missing when the stored PDF is gone", async () => {
    const backend = fakeBackend([stored("a", "Alt.pdf")]);
    backend.pdfAnswer = () => json({ detail: "The original PDF is no longer available." }, 404);
    await mount();
    await click("Open Alt.pdf");
    expect(text()).not.toContain("Back to documents");
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("Alt.pdf could not be opened. The original PDF is no longer available.");
    expect(button("Open Alt.pdf")?.disabled).toBe(false); // and the user can try again or delete it
  });

  it("offers no way to open a document that is not completed", async () => {
    fakeBackend([stored("a", "Fertig.pdf"), stored("f", "Kaputt.pdf", "failed"), stored("p", "Laeuft.pdf", "processing")]);
    await mount();
    expect([...host.querySelectorAll("button")].map((b) => b.getAttribute("aria-label")).filter((l) => l?.startsWith("Open "))).toEqual(["Open Fertig.pdf"]);
  });
});

describe("deleting a stored document", () => {
  const docs = () => [stored("a", "Erste.pdf"), stored("b", "Zweite.pdf", "failed"), stored("c", "Dritte.pdf")];

  it("asks for confirmation naming the document, and Cancel deletes nothing", async () => {
    const backend = fakeBackend(docs());
    await mount();
    await click("Delete Zweite.pdf");
    expect(host.querySelector(".demo-confirm")?.textContent).toContain("Delete Zweite.pdf?");
    expect(backend.count("DELETE")).toBe(0); // nothing is deleted by the first click
    expect(document.activeElement?.textContent).toBe("Cancel"); // the safe choice has the focus
    await click("Cancel");
    expect(host.querySelector(".demo-confirm")).toBeNull();
    expect(text()).toContain("Zweite.pdf");
    expect(backend.count("DELETE")).toBe(0);
    expect(document.activeElement).toBe(button("Delete Zweite.pdf")); // the keyboard user keeps their place
  });

  it("Escape cancels the confirmation", async () => {
    const backend = fakeBackend(docs());
    await mount();
    await click("Delete Erste.pdf");
    await act(async () => { host.querySelector(".demo-confirm")!.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); });
    await settle();
    expect(host.querySelector(".demo-confirm")).toBeNull();
    expect(document.activeElement).toBe(button("Delete Erste.pdf"));
    expect(backend.count("DELETE")).toBe(0);
  });

  it("deletes once, keeps the document listed until the backend confirms, then removes only that one", async () => {
    const backend = fakeBackend(docs());
    const answer = deferred<Response>();
    backend.deleteAnswer = () => answer.promise;
    await mount();
    await click("Delete Zweite.pdf");
    const confirm = must("Delete document");
    await act(async () => { confirm.click(); confirm.click(); });
    await settle();
    expect(backend.count("DELETE")).toBe(1); // a second click does not delete twice
    expect(backend.calls).toContain("DELETE /api/jobs/b");
    expect(text()).toContain("Deleting…");
    expect(text()).toContain("Zweite.pdf"); // still listed: the backend has not answered
    expect(button("Cancel")?.disabled).toBe(true);

    await act(async () => { answer.resolve(new Response(null, { status: 204 })); });
    await settle();
    expect(text()).not.toContain("Zweite.pdf");
    expect(text()).toContain("Erste.pdf");
    expect(text()).toContain("Dritte.pdf");
    expect(backend.count("DELETE")).toBe(1);
    expect(backend.count("GET /api/documents")).toBe(2); // the list was read again afterwards
    expect(document.activeElement?.id).toBe("recent-heading"); // focus did not fall off the page
  });

  it("keeps the document and shows the reason when the backend refuses", async () => {
    const backend = fakeBackend(docs());
    backend.deleteAnswer = () => json({ detail: "The ODOS database is not available." }, 503);
    await mount();
    await click("Delete Erste.pdf");
    await click("Delete document");
    expect(host.querySelector(".demo-confirm [role=\"alert\"]")?.textContent).toContain("The ODOS database is not available.");
    expect(text()).toContain("Erste.pdf");
    expect(backend.docs).toHaveLength(3);
    backend.deleteAnswer = () => new Response(null, { status: 204 }); // the user can try again
    await click("Delete document");
    expect(text()).not.toContain("Erste.pdf");
    expect(backend.count("DELETE")).toBe(2);
  });

  it("offers no deletion for a document that is still being processed", async () => {
    fakeBackend([stored("p", "Laeuft.pdf", "processing"), stored("q", "Wartet.pdf", "queued")]);
    await mount();
    expect(button("Delete Laeuft.pdf")).toBeUndefined();
    expect(button("Delete Wartet.pdf")).toBeUndefined();
  });
});

describe("searching the library", () => {
  const type = async (value: string) => {
    const input = host.querySelector<HTMLInputElement>('input[type="search"]')!;
    const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!; // React tracks the value property
    await act(async () => { set.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); });
    await settle();
  };
  const names = () => [...host.querySelectorAll(".demo-docitem .demo-docname")].map((n) => n.textContent);

  it("filters the real list as the user types, never touches the backend, and leaves a running upload alone", async () => {
    const backend = fakeBackend([stored("a", "Bauordnung.pdf"), stored("b", "Maschinen.pdf"), stored("c", "Baugesetz.pdf")]);
    await mount();
    expect(names()).toHaveLength(3);
    await type("bau");
    expect(names()).toEqual(["Bauordnung.pdf", "Baugesetz.pdf"]);
    await type("zzz");
    expect(text()).toContain("No documents match");
    await type("");
    expect(names()).toHaveLength(3);
    expect(backend.count("GET /api/documents")).toBe(1); // filtering happens in the browser
    expect(backend.count("POST")).toBe(0);
  });

  it("keeps the search text when the list is refreshed", async () => {
    fakeBackend([stored("a", "Bauordnung.pdf"), stored("b", "Maschinen.pdf")]);
    await mount();
    await type("masch");
    await click("Refresh");
    expect(host.querySelector<HTMLInputElement>('input[type="search"]')?.value).toBe("masch");
    expect(names()).toEqual(["Maschinen.pdf"]);
  });
});

describe("uploads with identical file names", () => {
  const upload = (id: string, filename: string, created_at: string, status: StoredDocument["status"] = "completed"): StoredDocument => ({ id, filename, status, created_at });
  /** [file name, label] of every listed document, in the order shown. */
  const shown = () => [...host.querySelectorAll(".demo-docitem")].map((li) => [li.querySelector(".demo-docname")!.textContent, li.querySelector(".demo-dup")?.textContent ?? null]);
  const byLabel = (prefix: string) => [...host.querySelectorAll("button")].find((b) => b.getAttribute("aria-label")?.startsWith(prefix));
  const press = async (b: Element | undefined) => { if (!b) throw new Error("button not found"); await act(async () => { (b as HTMLElement).click(); }); await settle(); };
  const three = () => [
    upload("c", "Gesetz.pdf", "2026-11-12T15:32:00Z"), upload("b", "Gesetz.pdf", "2026-11-12T09:00:00Z"),
    upload("a", "Gesetz.pdf", "2026-11-11T08:00:00Z"), upload("z", "Einzeln.pdf", "2026-11-10T08:00:00Z"),
  ];

  it("labels the repeated uploads and leaves the unique file name alone", async () => {
    fakeBackend(three());
    await mount();
    expect(shown()).toEqual([["Gesetz.pdf", "Latest upload"], ["Gesetz.pdf", "Earlier upload"], ["Gesetz.pdf", "Earlier upload"], ["Einzeln.pdf", null]]);
  });

  it("opens the upload that was clicked, by its own id", async () => {
    const backend = fakeBackend(three());
    await mount();
    await press(byLabel("Open Gesetz.pdf (earlier upload")); // the first earlier one in the list: id b
    expect(text()).toContain("Back to documents");
    expect(backend.calls).toContain("GET /api/jobs/b/pdf");
    expect(backend.calls.filter((c) => c.includes("/pdf"))).toHaveLength(1);
    expect(backend.count("POST")).toBe(0);
  });

  it("deletes the upload that was confirmed, by its own id, and names it in the confirmation", async () => {
    const backend = fakeBackend(three());
    await mount();
    await press(byLabel("Delete Gesetz.pdf (earlier upload")); // id b
    expect(host.querySelector(".demo-confirm")?.textContent).toMatch(/Delete Gesetz\.pdf \(earlier upload, [^)]+\)\?/);
    await press(button("Delete document"));
    expect(backend.calls.filter((c) => c.startsWith("DELETE"))).toEqual(["DELETE /api/jobs/b"]);
    expect(backend.docs.map((d) => d.id)).toEqual(["c", "a", "z"]); // nothing else was touched
    expect(shown()).toEqual([["Gesetz.pdf", "Latest upload"], ["Gesetz.pdf", "Earlier upload"], ["Einzeln.pdf", null]]);
  });

  it("promotes the next newest upload when the latest one is deleted", async () => {
    const backend = fakeBackend(three());
    await mount();
    await press(byLabel("Delete Gesetz.pdf (latest upload"));
    expect(host.querySelector(".demo-confirm")?.textContent).toMatch(/\(latest upload, [^)]+\)\?/);
    await press(button("Delete document"));
    expect(backend.calls).toContain("DELETE /api/jobs/c");
    expect(shown()).toEqual([["Gesetz.pdf", "Latest upload"], ["Gesetz.pdf", "Earlier upload"], ["Einzeln.pdf", null]]); // b is now the latest
    expect(byLabel("Open Gesetz.pdf (latest upload")).toBeDefined();
  });

  it("drops the labels when only one upload of a file name is left", async () => {
    fakeBackend([upload("n", "Gesetz.pdf", "2026-11-12T15:32:00Z"), upload("o", "Gesetz.pdf", "2026-11-12T00:02:00Z")]);
    await mount();
    expect(shown().map((r) => r[1])).toEqual(["Latest upload", "Earlier upload"]);
    await press(byLabel("Delete Gesetz.pdf (latest upload"));
    await press(button("Delete document"));
    expect(shown()).toEqual([["Gesetz.pdf", null]]);
    expect(button("Open Gesetz.pdf")).toBeDefined(); // and the plain accessible name is back
  });

  it("keeps the labels correct while the search narrows the list", async () => {
    fakeBackend(three());
    await mount();
    const search = async (value: string) => {
      const input = host.querySelector<HTMLInputElement>('input[type="search"]')!;
      const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
      await act(async () => { set.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); });
      await settle();
    };
    await search("gesetz");
    expect(shown().map((r) => r[1])).toEqual(["Latest upload", "Earlier upload", "Earlier upload"]);
    await search("einzeln");
    expect(shown()).toEqual([["Einzeln.pdf", null]]);
    await search("");
    expect(shown()).toHaveLength(4);
  });

  it("moves the labels when a refresh brings a newer upload", async () => {
    const backend = fakeBackend([upload("a", "Gesetz.pdf", "2026-11-11T08:00:00Z")]);
    await mount();
    expect(shown()).toEqual([["Gesetz.pdf", null]]); // alone: no label
    backend.docs = [upload("n", "Gesetz.pdf", "2026-11-12T10:00:00Z"), ...backend.docs];
    await click("Refresh");
    expect(shown()).toEqual([["Gesetz.pdf", "Latest upload"], ["Gesetz.pdf", "Earlier upload"]]);
  });

  it("keeps an earlier upload that is still being processed or failed deletable only where the backend allows it", async () => {
    fakeBackend([upload("n", "Gesetz.pdf", "2026-11-12T10:00:00Z", "processing"), upload("o", "Gesetz.pdf", "2026-11-11T10:00:00Z", "failed")]);
    await mount();
    expect(shown()).toEqual([["Gesetz.pdf", "Latest upload"], ["Gesetz.pdf", "Earlier upload"]]);
    expect(byLabel("Delete Gesetz.pdf (latest upload")).toBeUndefined(); // still processing: no Delete, as before
    expect(byLabel("Delete Gesetz.pdf (earlier upload")).toBeDefined();
  });
});

describe("recent documents states on the dashboard", () => {
  it("shows the empty state, and the backend's error with a retry", async () => {
    const backend = fakeBackend([]);
    await mount();
    expect(text()).toContain("No documents yet");
    const down = vi.fn(async () => json({ detail: "The ODOS database is not available." }, 503));
    vi.stubGlobal("fetch", down);
    await click("Refresh");
    expect(host.querySelector(".demo-recent [role=\"alert\"]")?.textContent).toContain("The ODOS database is not available.");
    expect(backend.count("POST")).toBe(0);
    vi.stubGlobal("fetch", vi.fn(async () => json([stored("a", "Zurueck.pdf")])));
    await click("Try again");
    expect(text()).toContain("Zurueck.pdf");
  });
});
