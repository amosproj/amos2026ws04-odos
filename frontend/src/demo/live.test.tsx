import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { highlightsOf } from "../structure";
import { box, el, modelOf } from "../testing";
import DemoApp, { Artifacts, ResultView } from "./DemoApp";
import { ProcessingError, STAGE_LABELS, deleteStoredDocument, listDocuments, openStoredDocument, nodeJson, pdfProblem, processPdf, releaseJob, stageLabel, type Job } from "./live";

vi.mock("../components/PdfViewer", () => ({
  PdfViewer: (p: { url: string; page: number; highlights: unknown[] }) => (
    <div className="pdf-stub" data-url={p.url} data-page={p.page} data-highlights={p.highlights.length} />
  ),
}));

// An invented German law as the backend returns it: document model, Legal JSON 2.0, Docling JSON, validation report.
const ABS = "doc/par-1/abs-1";
const model = {
  ...modelOf([
    el("doc", "document", null, ["doc/par-1"], { region: "document" }),
    el("doc/par-1", "paragraph", "doc", [ABS], { marker: "§ 1", title: "Geltung", pages: [1], source_refs: ["#/texts/0"], provenance: [box(1, 60, 700, 300, 688)] }),
    el(ABS, "absatz", "doc/par-1", [], { marker: "(1)", original_text: "(1) Dieses Gesetz gilt.", pages: [1], source_refs: ["#/texts/1"], provenance: [box(1, 60, 680, 500, 668)] }),
  ]),
  metadata: { title: "Beispielgesetz" },
};
const legal = {
  schemaVersion: "2.0", id: "beispielgesetz", title: "Beispielgesetz", frontMatter: [], tableOfContents: [], footnotes: [],
  structure: [{ id: "doc/par-1", type: "section", nativeType: "Paragraph", number: "1", marker: "§ 1", title: "Geltung", pages: [1],
    children: [{ id: ABS, type: "subsection", nativeType: "Absatz", number: "1", marker: "(1)", text: "Dieses Gesetz gilt.", pages: [1] }] }],
};
const job = (status: Job["status"], extra: Partial<Job> = {}): Job => ({
  id: "j1", filename: "Gesetz.pdf", status, stage: null, message: null, ...extra,
});
const done = job("completed");

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

/** A fake backend: answers like odos.api with the given job states (one per poll) and result files. */
function backend(states: Job[], files: Record<string, unknown>) {
  const calls: string[] = [];
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? "GET"} ${url}`);
    if (init?.method === "POST") return json(states.shift(), 202);
    if (init?.method === "DELETE") return new Response(null, { status: 204 });
    const file = /\/files\/([^?]+)$/.exec(url)?.[1];
    return file ? json(files[file]) : json(states.shift());
  });
  vi.stubGlobal("fetch", fetch);
  return calls;
}

async function run(states: Job[], files: Record<string, unknown> = { "document_model.json": model, "document.json": legal }) {
  vi.useFakeTimers();
  const calls = backend(states, files);
  const stages: string[] = [];
  const p = processPdf(new File(["%PDF-1.7"], "Gesetz.pdf"), (s) => stages.push(s));
  p.catch(() => undefined);
  await vi.runAllTimersAsync();
  return { result: p, calls, stages };
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("live processing through the backend", () => {
  it("uploads the PDF, polls the job through its stages and loads the document model and Legal JSON", async () => {
    const { result, calls, stages } = await run([job("queued"), job("processing", { stage: "extracting" }), job("processing", { stage: "normalizing" }), done]);
    const r = await result;
    expect(stages).toEqual(["uploading", "queued", "extracting", "normalizing", "completed"]);
    expect(calls).toEqual([
      "POST /api/jobs", "GET /api/jobs/j1", "GET /api/jobs/j1", "GET /api/jobs/j1",
      "GET /api/jobs/j1/files/document_model.json", "GET /api/jobs/j1/files/document.json",
    ]);
    expect(r.title).toBe("Beispielgesetz");
    expect(r.download).toEqual({ href: "/api/jobs/j1/files/document.json?download=true", name: "Gesetz.legal.json" });
    expect(r.live?.legal).toEqual(legal); // kept unchanged: the download is the complete canonical document.json
    expect(r.json).toContain('"germanType": "Paragraph"');
    expect(r.json).not.toContain("nativeType");
  });

  it("reports an unsupported structure with the backend's message and removes the job", async () => {
    const { result, calls } = await run([job("unsupported", { message: "The document type could not be recognized." })]);
    await expect(result).rejects.toThrow("The document type could not be recognized.");
    await expect(result).rejects.toMatchObject({ name: "ProcessingError", kind: "unsupported" });
    expect(calls).toContain("DELETE /api/jobs/j1");
  });

  it("never reports completion or loads results before the backend confirms it", async () => {
    for (const status of ["failed", "unsupported"] as const) {
      const { result, calls, stages } = await run([job("queued"), job("processing", { stage: "extracting" }), job(status, { message: "No result." })]);
      await expect(result).rejects.toBeInstanceOf(ProcessingError);
      await expect(result).rejects.toMatchObject({ kind: status, message: "No result." });
      expect(stages).not.toContain("completed");
      expect(calls.some((c) => c.includes("/files/"))).toBe(false);
    }
    const { result, calls, stages } = await run([job("queued"), job("processing", { stage: "normalizing" }), done]);
    await result;
    expect(stages.at(-1)).toBe("completed");
    expect(calls.findIndex((c) => c.includes("/files/"))).toBeGreaterThan(calls.lastIndexOf("GET /api/jobs/j1")); // results only after the last poll
  });

  it("leaves jobs the backend keeps in its database", async () => {
    const { result, calls } = await run([job("unsupported", { message: "Not recognized.", persistent: true })]);
    await expect(result).rejects.toThrow("Not recognized.");
    expect(calls).not.toContain("DELETE /api/jobs/j1");
    expect((await (await run([job("completed", { persistent: true })])).result).live?.persistent).toBe(true);
    expect((await (await run([done])).result).live?.persistent).toBe(false); // older backends send no flag
  });

  it("deletes a job it is done with only when the backend does not keep it", () => {
    const calls = backend([], {});
    releaseJob("kept", true);
    releaseJob("temporary");
    expect(calls).toEqual(["DELETE /api/jobs/temporary"]);
  });

  it("reports a failed job and a refused upload with the backend's explanation", async () => {
    await expect((await run([job("failed", { message: "The PDF could not be processed." })])).result).rejects.toThrow("The PDF could not be processed.");
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: "The PDF is larger than 50 MB." }, 413)));
    await expect(processPdf(new File(["x"], "big.pdf"), () => {})).rejects.toThrow("The PDF is larger than 50 MB.");
    await expect(processPdf(new File(["x"], "big.pdf"), () => {})).rejects.not.toBeInstanceOf(ProcessingError); // refused before any job existed
  });

  it("says when the backend is not running", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    await expect(processPdf(new File(["x"], "a.pdf"), () => {})).rejects.toThrow("The ODOS backend is not reachable");
    vi.stubGlobal("fetch", vi.fn(async () => new Response("", { status: 502 }))); // the dev server's proxy without a backend
    await expect(processPdf(new File(["x"], "a.pdf"), () => {})).rejects.toThrow("The ODOS backend is not reachable");
  });
});

describe("processing stage wording", () => {
  it("describes the stages the backend reports in user-facing words", () => {
    expect(stageLabel("uploading")).toBe("Uploading document…");
    expect(stageLabel("extracting")).toBe("Analyzing document structure…");
    expect(stageLabel("normalizing")).toBe("Preparing structured legal data…");
    expect(stageLabel("completed")).toContain("Document processing complete.");
    expect(stageLabel("something-new")).toBe("Processing document…"); // an unknown stage still gets neutral wording
  });

  it("names no implementation detail and invents no progress", () => {
    for (const label of Object.values(STAGE_LABELS)) expect(label).not.toMatch(/docling|\d+\s*%/i);
  });
});

describe("PDF selection", () => {
  it("accepts PDFs by type or by name", () => {
    expect(pdfProblem(new File(["%PDF-1.7"], "a.pdf", { type: "application/pdf" }))).toBeNull();
    expect(pdfProblem(new File(["%PDF-1.7"], "B.PDF"))).toBeNull(); // the browser reported no type
  });

  it("rejects other files and empty files", () => {
    expect(pdfProblem(new File(["hello"], "notes.txt", { type: "text/plain" }))).toContain("Only PDF files");
    expect(pdfProblem(new File(["x"], "image.png", { type: "image/png" }))).toContain("Only PDF files");
    expect(pdfProblem(new File([], "empty.pdf", { type: "application/pdf" }))).toContain("empty");
  });
});

describe("stored documents", () => {
  const stored = [{ id: "j2", filename: "Zwei.pdf", status: "completed", created_at: "2026-11-11T10:00:00Z" }];

  it("lists the documents from GET /api/documents", async () => {
    const fetch = vi.fn(async () => json(stored));
    vi.stubGlobal("fetch", fetch);
    expect(await listDocuments()).toEqual(stored);
    expect(fetch).toHaveBeenCalledWith("/api/documents", undefined);
  });

  /** A fake backend for stored documents: the job, its result files and the PDF; every request is recorded. */
  function backendWith(jobState: Job, extra: Record<string, () => Response> = {}) {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${url}`);
      const route = Object.keys(extra).find((k) => url.endsWith(k));
      if (route) return extra[route]();
      if (url.endsWith("/files/document_model.json")) return json(model);
      if (url.endsWith("/files/document.json")) return json(legal);
      if (url.endsWith("/pdf")) return new Response("%PDF-1.7");
      return json(jobState);
    }));
    return calls;
  }

  it("opens a stored document from its job, results and PDF, without uploading or polling", async () => {
    const calls = backendWith(job("completed", { persistent: true }));
    const { result, pdf } = await openStoredDocument("j1");
    expect(calls.filter((c) => c.startsWith("POST"))).toEqual([]); // no new job
    expect(calls[0]).toBe("GET /api/jobs/j1");
    expect(calls.slice(1).sort()).toEqual(["GET /api/jobs/j1/files/document.json", "GET /api/jobs/j1/files/document_model.json", "GET /api/jobs/j1/pdf"]);
    expect(result.title).toBe("Beispielgesetz");
    expect(result.live).toMatchObject({ jobId: "j1", persistent: true, legal });
    expect(result.download.href).toBe("/api/jobs/j1/files/document.json?download=true");
    expect(await pdf.text()).toBe("%PDF-1.7");
  });

  it("does not open a document that has no completed result", async () => {
    for (const [status, message] of [["queued", /still being processed/], ["processing", /still being processed/], ["failed", /no result/], ["unsupported", /no result/]] as const) {
      const calls = backendWith(job(status));
      await expect(openStoredDocument("j1")).rejects.toThrow(message);
      expect(calls).toEqual(["GET /api/jobs/j1"]); // and neither results nor PDF are requested
    }
    backendWith(job("failed", { message: "The PDF could not be processed." }));
    await expect(openStoredDocument("j1")).rejects.toThrow("The PDF could not be processed.");
  });

  it("explains what is missing instead of opening a half-empty result", async () => {
    backendWith(job("completed"), { "/pdf": () => json({ detail: "The original PDF is no longer available." }, 404) });
    await expect(openStoredDocument("j1")).rejects.toThrow("The original PDF is no longer available.");
    backendWith(job("completed"), { "/files/document.json": () => json({ detail: "The result file is no longer available." }, 404) });
    await expect(openStoredDocument("j1")).rejects.toThrow("The result file is no longer available.");
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: "Unknown job." }, 404)));
    await expect(openStoredDocument("gone")).rejects.toThrow("Unknown job.");
  });

  it("deletes one stored document and resolves only when the backend confirms", async () => {
    const calls = backendWith(job("completed"), { "/jobs/j1": () => new Response(null, { status: 204 }) });
    await expect(deleteStoredDocument("j1")).resolves.toBeUndefined();
    expect(calls).toEqual(["DELETE /api/jobs/j1"]);
  });

  it("reports a refused or failed deletion instead of pretending it worked", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: "Cannot delete a running job." }, 409)));
    await expect(deleteStoredDocument("j1")).rejects.toThrow("Cannot delete a running job.");
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: "Unknown job." }, 404)));
    await expect(deleteStoredDocument("j1")).rejects.toThrow("Unknown job.");
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: "The ODOS database is not available." }, 503)));
    await expect(deleteStoredDocument("j1")).rejects.toThrow("The ODOS database is not available.");
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    await expect(deleteStoredDocument("j1")).rejects.toThrow("not reachable");
  });

  it("reports the backend's explanation when the database is down, and an unreachable backend", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ detail: "The ODOS database is not available." }, 503)));
    await expect(listDocuments()).rejects.toThrow("The ODOS database is not available.");
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    await expect(listDocuments()).rejects.toThrow("The ODOS backend is not reachable");
  });
});

describe("live result view", async () => {
  const { result } = await run([done]);
  const r = await result;
  vi.useRealTimers();
  const abs = r.model.elements.find((e) => e.id === ABS)!;

  it("keeps the layout and shows no status badges", () => {
    const html = renderToStaticMarkup(<ResultView result={r} pdfUrl="blob:pdf" onReset={() => {}} />);
    for (const s of ['aria-label="Original PDF"', 'data-url="blob:pdf"', 'aria-label="Recognized legal structure"', "Legal structure", "Artifacts", "Back to documents"]) {
      expect(html).toContain(s);
    }
    expect(html).not.toMatch(/Processing details|processed as|schema-valid|parser warning|precomputed result|class="chip/);
    expect(html.match(/role="tab"/g)).toHaveLength(2);
  });

  it("previews the selected element with germanType and downloads the complete document.json", () => {
    const html = renderToStaticMarkup(<Artifacts result={r} element={abs} />);
    expect(html).toContain('href="/api/jobs/j1/files/document.json?download=true" download="Gesetz.legal.json"');
    const pre = /<pre[^>]*>([\s\S]*?)<\/pre>/.exec(html)![1].replace(/&quot;/g, '"');
    expect(JSON.parse(pre)).toEqual({ ...legal.structure[0].children[0], nativeType: undefined, germanType: "Absatz" });
    expect(html).not.toMatch(/Preview:|shown as/); // no explanatory text above the JSON
  });

  it("offers a switch between the selected element and the full document", () => {
    const pressed = (html: string) => [...html.matchAll(/aria-pressed="(\w+)">([^<]+)</g)].map((m) => [m[2], m[1]]);
    const selected = renderToStaticMarkup(<Artifacts result={r} element={abs} full={false} onFull={() => {}} />);
    expect(pressed(selected)).toEqual([["Selected element", "true"], ["Full document", "false"]]);
    expect(selected).toContain("&quot;id&quot;: &quot;doc/par-1/abs-1&quot;"); // the element's node only
    expect(selected).not.toContain("schemaVersion");
    const full = renderToStaticMarkup(<Artifacts result={r} element={abs} full onFull={() => {}} />);
    expect(pressed(full)).toEqual([["Selected element", "false"], ["Full document", "true"]]);
    const text = /<pre[^>]*>([\s\S]*?)<\/pre>/.exec(full)![1].replace(/&quot;/g, '"');
    expect(JSON.parse(text)).toEqual({ ...legal, structure: [{ ...legal.structure[0], nativeType: undefined, germanType: "Paragraph", children: [{ ...legal.structure[0].children[0], nativeType: undefined, germanType: "Absatz" }] }] });
    expect(full).toContain('href="/api/jobs/j1/files/document.json?download=true"'); // the download is the same either way
    expect(selected).toContain('href="/api/jobs/j1/files/document.json?download=true"');
  });

  it("offers no switch for the prepared examples", () => {
    expect(renderToStaticMarkup(<Artifacts result={{ ...r, live: undefined }} />)).not.toContain("aria-pressed");
  });

  it("shows the whole document in presentation form when nothing is selected", () => {
    const html = renderToStaticMarkup(<Artifacts result={r} />);
    expect(html).toContain("&quot;schemaVersion&quot;: &quot;2.0&quot;");
  });

  it("highlights the selected element's source in the PDF", () => {
    expect(highlightsOf(abs).boxes).toHaveLength(1);
  });
});

describe("upload screen", () => {
  it("has no document type choice: the backend recognizes the type", () => {
    const html = renderToStaticMarkup(<DemoApp />);
    expect(html).not.toMatch(/Document type|<select|<option/);
  });

  it("starts idle: no processing status, no error, nothing to submit yet", () => {
    const html = renderToStaticMarkup(<DemoApp />);
    expect(html).not.toMatch(/role="progressbar"|role="alert"|Docling/);
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Process document<\/button>/);
  });
});

// The real pipeline outputs of `npm run demo:setup` (gitignored, full text of the partner documents): the live path
// on them, with the backend replaced by the files. Skipped when they were not generated.
const WORK = resolve(__dirname, "../../.demo-work");
const REAL = [
  { dir: "mbo", id: "doc/teil-2/par-6/abs-1", pages: [9, 10] },
  { dir: "eu", id: "doc/chp-2/art-10/para-1", pages: null },
] as const;

describe.each(REAL)("live path on the real $dir pipeline output", ({ dir, id, pages }) => {
  const read = (f: string) => JSON.parse(readFileSync(resolve(WORK, dir, f), "utf8")) as unknown;
  it.skipIf(!existsSync(resolve(WORK, dir, "document.json")))("previews and highlights the provision", async () => {
    const files = Object.fromEntries(["document_model.json", "document.json"].map((f) => [f, read(f)]));
    const r = await (await run([job("completed")], files)).result;
    const element = r.model.elements.find((e) => e.id === id)!;
    const node = JSON.parse(nodeJson(r.live!, element)!) as { id: string; germanType: string; pages: number[] };
    expect([node.id, node.germanType]).toEqual([id, "Absatz"]);
    if (pages) expect(node.pages).toEqual(pages);
    expect(new Set(highlightsOf(element).boxes.map((b) => b.page_no))).toEqual(new Set(node.pages));
  });
});
