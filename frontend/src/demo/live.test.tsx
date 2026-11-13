import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { highlightsOf } from "../structure";
import { box, el, modelOf } from "../testing";
import DemoApp, { ArtifactSwitch, Artifacts, ResultView, RuleJsonPreview } from "./DemoApp";
import { nodeJson, processPdf, releaseJob, ruleEntries, rulesForElement, type Job } from "./live";

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
    if (file) return Object.prototype.hasOwnProperty.call(files, file) ? json(files[file]) : new Response(null, { status: 404 });
    return json(states.shift());
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

const ruleSet = [
  { schemaVersion: "1.0", id: "rule-a", type: "obligation", source: [{ elementId: ABS }], summary: "First fixture rule." },
  { schemaVersion: "1.0", id: "rule-b", type: "prohibition", source: [{ elementId: ABS }, { elementId: "doc/par-1" }], summary: "Second fixture rule." },
  { schemaVersion: "1.0", id: "rule-c", type: "permission", source: [{ elementId: "doc/par-1" }], summary: "Other element rule." },
];

describe("Rule JSON source mapping", () => {
  it("switches the selected artifact to Rule JSON", () => {
    let selected: "legal" | "rule" = "legal";
    const selector = ArtifactSwitch({ selected, onChange: (next) => { selected = next; } });
    const ruleButton = selector.props.children[1];
    ruleButton.props.onClick();
    expect(selected).toBe("rule");
  });

  it("maps every rule to its stable source element ID and returns multiple matches", () => {
    expect(rulesForElement(ruleSet, ABS).map((rule) => rule.id)).toEqual(["rule-a", "rule-b"]);
    expect(rulesForElement(ruleSet, "doc/par-1").map((rule) => rule.id)).toEqual(["rule-b", "rule-c"]);
  });

  it("accepts a collection wrapper and returns no entries for a missing artifact or unmatched element", () => {
    expect(ruleEntries({ rules: ruleSet })).toEqual(ruleSet);
    expect(rulesForElement(null, ABS)).toEqual([]);
    expect(rulesForElement(ruleSet, "doc/missing")).toEqual([]);
  });
});

describe("live processing through the backend", () => {
  it("uploads the PDF, polls the job through its stages and loads the document model and Legal JSON", async () => {
    const { result, calls, stages } = await run([job("queued"), job("processing", { stage: "extracting" }), job("processing", { stage: "normalizing" }), done]);
    const r = await result;
    expect(stages).toEqual(["uploading", "queued", "extracting", "normalizing"]);
    expect(calls).toEqual([
      "POST /api/jobs", "GET /api/jobs/j1", "GET /api/jobs/j1", "GET /api/jobs/j1",
      "GET /api/jobs/j1/files/document_model.json", "GET /api/jobs/j1/files/document.json", "GET /api/jobs/j1/files/rules.json",
    ]);
    expect(r.title).toBe("Beispielgesetz");
    expect(r.download).toEqual({ href: "/api/jobs/j1/files/document.json?download=true", name: "Gesetz.legal.json" });
    expect(r.live?.legal).toEqual(legal); // kept unchanged: the download is the complete canonical document.json
    expect(r.live?.ruleJson).toBeNull(); // optional artifact missing means no extracted rules
    expect(r.json).toContain('"germanType": "Paragraph"');
    expect(r.json).not.toContain("nativeType");
  });

  it("reports an unsupported structure with the backend's message and removes the job", async () => {
    const { result, calls } = await run([job("unsupported", { message: "The document type could not be recognized." })]);
    await expect(result).rejects.toThrow("The document type could not be recognized.");
    expect(calls).toContain("DELETE /api/jobs/j1");
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
  });

  it("says when the backend is not running", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    await expect(processPdf(new File(["x"], "a.pdf"), () => {})).rejects.toThrow("The ODOS backend is not reachable");
    vi.stubGlobal("fetch", vi.fn(async () => new Response("", { status: 502 }))); // the dev server's proxy without a backend
    await expect(processPdf(new File(["x"], "a.pdf"), () => {})).rejects.toThrow("The ODOS backend is not reachable");
  });
});

describe("live result view", async () => {
  const { result } = await run([done]);
  const r = await result;
  vi.useRealTimers();
  const abs = r.model.elements.find((e) => e.id === ABS)!;

  it("keeps the layout and shows no status badges", () => {
    const html = renderToStaticMarkup(<ResultView result={r} pdfUrl="blob:pdf" onReset={() => {}} />);
    for (const s of ['aria-label="Original PDF"', 'data-url="blob:pdf"', 'aria-label="Recognized legal structure"', "Legal structure", "Artifacts", "Choose another PDF"]) {
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

  it("loads persisted Rule JSON for this job and prepares its collection download", async () => {
    const { result: loaded } = await run([done], { "document_model.json": model, "document.json": legal, "rules.json": ruleSet });
    const withRules = await loaded;
    expect(withRules.live?.ruleJson).toEqual(ruleSet);
    expect(withRules.live?.ruleDownload).toEqual({ href: "/api/jobs/j1/files/rules.json?download=true", name: "Gesetz.rules.json" });
    const html = renderToStaticMarkup(<Artifacts result={withRules} element={withRules.model.elements.find((e) => e.id === ABS)} full={false} onFull={() => {}} />);
    expect(html).toContain("Custom Legal JSON");
    expect(html).toContain("Rule JSON");
    expect(html).toContain('aria-label="Artifact type"');
  });

  it("shows all rules mapped to the selected element and keeps their source references", () => {
    const html = renderToStaticMarkup(<RuleJsonPreview result={{ ...r, live: { ...r.live!, ruleJson: ruleSet } }} element={abs} full={false} />);
    const shown = JSON.parse(/<pre[^>]*>([\s\S]*?)<\/pre>/.exec(html)![1].replace(/&quot;/g, '"'));
    expect(shown.map((rule: { id: string }) => rule.id)).toEqual(["rule-a", "rule-b"]);
    expect(shown[1].source).toEqual(ruleSet[1].source);
  });

  it("shows element and document empty states when rules are absent", () => {
    const withRules = { ...r, live: { ...r.live!, ruleJson: ruleSet } };
    expect(renderToStaticMarkup(<RuleJsonPreview result={withRules} element={el("doc/no-rules", "paragraph", "doc", [])} full={false} />)).toContain("No Rule JSON available for this element.");
    expect(renderToStaticMarkup(<RuleJsonPreview result={r} element={abs} full={false} />)).toContain("No Rule JSON available for this document.");
  });

  it("shows all available rules in full-document mode", () => {
    const html = renderToStaticMarkup(<RuleJsonPreview result={{ ...r, live: { ...r.live!, ruleJson: { rules: ruleSet } } }} element={abs} full />);
    const shown = JSON.parse(/<pre[^>]*>([\s\S]*?)<\/pre>/.exec(html)![1].replace(/&quot;/g, '"'));
    expect(shown.map((rule: { id: string }) => rule.id)).toEqual(["rule-a", "rule-b", "rule-c"]);
    expect(shown[0].source).toEqual(ruleSet[0].source);
  });

  it("offers the Rule JSON download only when real rule entries are available", () => {
    const withRules = { ...r, live: { ...r.live!, ruleJson: ruleSet } };
    const available = renderToStaticMarkup(<Artifacts result={withRules} element={abs} full={false} onFull={() => {}} artifactView="rule" />);
    expect(available).toContain('href="/api/jobs/j1/files/rules.json?download=true" download="Gesetz.rules.json"');
    expect(available).toContain("rule-a");
    const missing = renderToStaticMarkup(<Artifacts result={r} element={abs} full={false} onFull={() => {}} artifactView="rule" />);
    expect(missing).not.toContain("rules.json?download=true");
    expect(missing).toContain("No Rule JSON available for this document.");
  });

  it("offers a switch between the selected element and the full document", () => {
    const pressed = (html: string) => [...html.matchAll(/aria-pressed="(\w+)">([^<]+)</g)].map((m) => [m[2], m[1]]);
    const selected = renderToStaticMarkup(<Artifacts result={r} element={abs} full={false} onFull={() => {}} />);
    expect(pressed(selected).filter(([label]) => label === "Selected element" || label === "Full document")).toEqual([["Selected element", "true"], ["Full document", "false"]]);
    expect(selected).toContain("&quot;id&quot;: &quot;doc/par-1/abs-1&quot;"); // the element's node only
    expect(selected).not.toContain("schemaVersion");
    const full = renderToStaticMarkup(<Artifacts result={r} element={abs} full onFull={() => {}} />);
    expect(pressed(full).filter(([label]) => label === "Selected element" || label === "Full document")).toEqual([["Selected element", "false"], ["Full document", "true"]]);
    const text = /<pre[^>]*>([\s\S]*?)<\/pre>/.exec(full)![1].replace(/&quot;/g, '"');
    expect(JSON.parse(text)).toEqual({ ...legal, structure: [{ ...legal.structure[0], nativeType: undefined, germanType: "Paragraph", children: [{ ...legal.structure[0].children[0], nativeType: undefined, germanType: "Absatz" }] }] });
    expect(full).toContain('href="/api/jobs/j1/files/document.json?download=true"'); // the download is the same either way
    expect(selected).toContain('href="/api/jobs/j1/files/document.json?download=true"');
  });

  it("keeps selected-element and full-document controls limited to live jobs", () => {
    const html = renderToStaticMarkup(<Artifacts result={{ ...r, live: undefined }} />);
    expect(html).toContain("Rule JSON");
    expect(html).not.toContain("Selected element");
    expect(html).not.toContain("Full document");
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
