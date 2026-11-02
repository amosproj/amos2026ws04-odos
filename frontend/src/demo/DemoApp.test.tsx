import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { box, el, modelOf } from "../testing";
import DemoApp, { Artifacts, ResultView } from "./DemoApp";
import { PipelineView } from "./PipelineView";
import type { DemoResult, PipelineDetails } from "./fixtures";

// the PDF viewer needs a browser (pdf.js, canvas): replaced by a stub that shows what the demo hands to it
vi.mock("../components/PdfViewer", () => ({
  PdfViewer: (p: { url: string; page: number; highlights: unknown[] }) => (
    <div className="pdf-stub" data-url={p.url} data-page={p.page} data-highlights={p.highlights.length} />
  ),
}));

// An invented provision with the shape of § 6 (1): the introduction runs over a page break, two numbered children follow.
const ABS = "doc/teil-2/par-6/abs-1";
const INTRO = "1 Erster Satz beginnt am Seitenende und geht auf der nächsten Seite weiter. 2 Zweiter Satz.";
// Its Legal JSON 2.0 excerpt as scripts/build-demo-fixtures.mjs writes it: Zweiter Teil down to § 6 Absatz 1 and 2.
const json = JSON.stringify({
  id: "doc/teil-2", type: "part", nativeType: "Teil", number: "2", marker: "Zweiter Teil", title: "Beispielteil", pages: [9],
  children: [{
    id: "doc/teil-2/par-6", type: "section", nativeType: "Paragraph", number: "6", marker: "§ 6", title: "Beispiel", pages: [9],
    children: [
      { id: ABS, type: "subsection", nativeType: "Absatz", number: "1", marker: "(1)", text: INTRO, pages: [9, 10], children: [
        { id: `${ABS}/nr-1`, type: "number", nativeType: "Nummer", number: "1", marker: "1.", text: "erste Nummer", pages: [10] },
        { id: `${ABS}/nr-2`, type: "number", nativeType: "Nummer", number: "2", marker: "2.", text: "zweite Nummer", pages: [10] },
      ] },
      { id: "doc/teil-2/par-6/abs-2", type: "subsection", nativeType: "Absatz", number: "2", marker: "(2)", text: "zweiter Absatz", pages: [10] },
    ],
  }],
}, null, 2).replace(/\[\s+(\d+(?:,\s+\d+)*)\s+\]/g, (_m, ns: string) => `[${ns.split(/,\s+/).join(", ")}]`) + "\n";

const result: DemoResult = {
  doc: {
    id: "mbo", title: "Musterbauordnung (MBO)", pdfSha256: "0".repeat(64), pages: 83, profile: "german_law",
    files: { structure: "mbo/structure.json", json: "mbo/teil-2.legal.json" },
    example: { label: "§ 6 Beispiel", modelId: "doc/teil-2/par-6", legalJsonSchemaVersion: "2.0" },
    sources: { documentModelSha256: "", legalJsonSha256: "" },
  },
  model: modelOf([
    el("doc", "document", null, ["doc/teil-2"], { region: "document" }),
    el("doc/teil-2", "teil", "doc", ["doc/teil-2/par-5", "doc/teil-2/par-6", "doc/teil-2/par-7"], { marker: "Zweiter Teil", pages: [9] }),
    el("doc/teil-2/par-5", "paragraph", "doc/teil-2", [], { marker: "§ 5", pages: [8] }),
    el("doc/teil-2/par-6", "paragraph", "doc/teil-2", [ABS, "doc/teil-2/par-6/abs-2", "doc/teil-2/par-6/abs-3"], { marker: "§ 6", title: "Beispiel", pages: [9] }),
    el(ABS, "absatz", "doc/teil-2/par-6", [`${ABS}/nr-1`, `${ABS}/nr-2`, `${ABS}/fn-1`], {
      marker: "(1)", original_text: INTRO, pages: [9, 10], source_refs: ["#/texts/144", "#/texts/146"],
      provenance: [box(9, 65, 63, 531, 52), box(10, 65, 776, 531, 696)],
    }),
    el(`${ABS}/nr-1`, "nummer", ABS, [], { marker: "1.", original_text: "erste Nummer", pages: [10] }),
    el(`${ABS}/nr-2`, "nummer", ABS, [], { marker: "2.", original_text: "zweite Nummer", pages: [10] }),
    el(`${ABS}/fn-1`, "footnote", ABS, [], { original_text: "eine Fußnote", pages: [10] }),
    el("doc/teil-2/par-6/abs-2", "absatz", "doc/teil-2/par-6", [], { marker: "(2)", original_text: "zweiter Absatz", pages: [10] }),
    el("doc/teil-2/par-6/abs-3", "absatz", "doc/teil-2/par-6", [], { marker: "(3)", original_text: "dritter Absatz", pages: [10] }),
    el("doc/teil-2/par-7", "paragraph", "doc/teil-2", [], { marker: "§ 7", pages: [11] }),
  ]),
  json,
};

const preview = (html: string, title: string) => {
  const card = html.split('<section class="demo-artifact">').find((c) => c.includes(`<h3>${title}</h3>`))!;
  const pre = /<pre[^>]*>([\s\S]*?)<\/pre>/.exec(card)![1];
  return { card, text: pre.replace(/&quot;/g, '"').replace(/&#x27;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&") };
};

describe("upload screen", () => {
  const html = renderToStaticMarkup(<DemoApp />);
  it("shows only the title, the PDF upload and the Process Document button", () => {
    expect(html).toContain(">ODOS</h1>");
    expect(html).toContain('type="file"');
    expect(html).toContain("Choose a PDF or drop it here");
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Process Document<\/button>/); // nothing chosen yet
    expect(html).not.toContain('role="alert"');
  });
});

describe("result view", () => {
  const html = renderToStaticMarkup(<ResultView result={result} pdfUrl="blob:pdf" onReset={() => {}} />);
  it("shows the PDF on the left and the structure tree on the right", () => {
    expect(html).toContain('aria-label="Original PDF"');
    expect(html).toContain('data-url="blob:pdf"');
    expect(html).toContain('aria-label="Recognized legal structure"');
    expect(html).toContain("Musterbauordnung (MBO)");
    expect(html).toContain("precomputed result");
    expect(html).toContain("Choose another PDF");
    expect(html).toContain("Legal structure");
    expect(html).toContain("Artifacts");
    expect(html).toContain("Processing details");
    expect(html).toContain("Select an element to highlight its source text in the PDF.");
  });
  it("starts on page 1 without highlights; the tree shows the hierarchy", () => {
    expect(html).toContain('data-page="1"');
    expect(html).toContain('data-highlights="0"');
    expect(html).toContain("Zweiter Teil");
    expect(html).not.toContain("badge");
  });
});

describe("Custom Legal JSON preview and downloads", () => {
  const html = renderToStaticMarkup(<Artifacts result={result} />);
  it("shows only the heading, the download and the preview", () => {
    expect(html.replace(/<pre[\s\S]*<\/pre>/, "<pre/>").replace(/<[^>]+>/g, "|").split("|").filter((t) => t.trim())).toEqual(["Custom Legal JSON", "Download"]);
  });
  it("previews the Legal JSON 2.0 excerpt exactly as the downloaded file: Zweiter Teil, § 6, Absatz 1 with both Nummern, Absatz 2", () => {
    const { text } = preview(html, "Custom Legal JSON");
    expect(text + "\n").toBe(json);
    expect(text.startsWith('{\n  "id": "doc/teil-2",')).toBe(true);
    expect(text).toContain('"pages": [9, 10]');
    const teil = JSON.parse(text);
    const par = teil.children[0];
    expect([teil.id, par.id, par.children.map((c: { id: string }) => c.id)]).toEqual(["doc/teil-2", "doc/teil-2/par-6", [ABS, "doc/teil-2/par-6/abs-2"]]);
    expect(par.children[0].children.map((c: { id: string }) => c.id)).toEqual([`${ABS}/nr-1`, `${ABS}/nr-2`]);
    expect(text).not.toMatch(/sourceSpans|bbox|charStart|bboxScope|omittedChildren/);
  });
  it("offers the excerpt for download", () => {
    expect(preview(html, "Custom Legal JSON").card).toContain('href="/demo/mbo/teil-2.legal.json" download="teil-2.legal.json"');
  });
  it("shows no Akoma Ntoso XML", () => {
    expect(html).not.toMatch(/Akoma|\.akn\.xml/);
  });
});

// The shape of pipeline.json for the invented provision above (in the real build it is cut from the pipeline outputs).
const pipeline: PipelineDetails = {
  focusId: ABS,
  docling: {
    version: "1.10.0", itemsTotal: 1260, itemsInModel: 1260, pageSizes: { 9: { width: 595, height: 842 } },
    items: [
      { self_ref: "#/texts/144", label: "list_item", content_layer: "body", prov: [box(9, 65, 63, 531, 52)], orig: "(1) 1 Erster Satz beginnt am Seitenende" },
      { self_ref: "#/texts/145", label: "page_footer", content_layer: "furniture", prov: [box(9, 513, 46, 519, 36)], orig: "9" },
      { self_ref: "#/texts/146", label: "text", content_layer: "body", prov: [box(10, 65, 776, 531, 696)], orig: "und geht auf der nächsten Seite weiter." },
    ],
  },
  elements: [ABS, `${ABS}/nr-1`, `${ABS}/nr-2`].map((id) => {
    const e = result.model.elements.find((x) => x.id === id)!;
    return { ...e, hygiene_flags: id === ABS ? ["page_break_continuation_merged_confirmed"] : [] };
  }),
  warnings: [],
};

describe("processing details", () => {
  const html = renderToStaticMarkup(<PipelineView result={{ ...result, pipeline }} onSelect={() => {}} onOpenArtifacts={() => {}} />);
  it("names every stage and shows neither normalization nor Akoma Ntoso XML", () => {
    for (const s of ["Original PDF", "Docling output", "Legal parser → Document model", "Custom Legal JSON"]) expect(html).toContain(s);
    expect(html).not.toContain("Normalization");
    expect(html).not.toMatch(/Akoma|odos:src|eId/);
  });
  it("starts with every stage collapsed", () => {
    expect(html).toMatch(/<details class="demo-step">/);
    expect(html).not.toMatch(/<details[^>]*\bopen/);
  });
  it("shows three numbered stages: Docling output, legal parser and Custom Legal JSON", () => {
    expect([...html.matchAll(/<span class="demo-step-n">(\d)<\/span> <strong>([^<]*)<\/strong>/g)].map((m) => [m[1], m[2]]))
      .toEqual([["1", "Docling output"], ["2", "Legal parser → Document model"], ["3", "Custom Legal JSON"]]);
  });
  it("shows the Docling items with label, page and box", () => {
    expect(html).toContain("3 extracted text items (of 1260 in the document)");
    expect(html).toContain("page_footer");
    expect(html).toContain("l 65.0, t 63.0, r 531.0, b 52.0");
    expect(html).not.toContain("furniture/p9-footer"); // where each item ended up is no longer shown
    expect(html).not.toContain("running_footer");
  });
  it("shows the recognized hierarchy with parent and children ids and the page-break join", () => {
    expect(html).toContain(`<code>${ABS}/nr-1</code>`);
    expect(html).toContain("runs over pages 9–10");
    expect(html).toContain("page_break_continuation_merged_confirmed");
    expect(html).toContain("the text after the page break continues this unfinished Absatz");
  });
  it("lists the Legal JSON excerpt from Zweiter Teil down, with parents from the nesting, omitted siblings and pages", () => {
    const table = html.slice(html.lastIndexOf("<table"));
    expect([...table.matchAll(/<tr><td style="[^"]*"><code>([^<]+)<\/code><\/td>/g)].map((m) => m[1]))
      .toEqual(["doc/teil-2", "doc/teil-2/par-6", ABS, `${ABS}/nr-1`, `${ABS}/nr-2`, "doc/teil-2/par-6/abs-2"]);
    expect(table).toContain(`<td><code>doc/teil-2/par-6</code></td>`); // the parent of both Absätze
    expect(table).toContain("(+2 not shown)"); // §§ 5 and 7, counted in the document model
    expect(table).toContain("(+1 not shown)"); // Absatz 3; the footnote of Absatz 1 is not a child in Legal JSON
    expect(table).toContain("<td>9, 10</td>");
    expect(table).toContain("zweite Nummer");
  });
  it("explains that a build without processing details has none", () => {
    const none = renderToStaticMarkup(<PipelineView result={result} onSelect={() => {}} onOpenArtifacts={() => {}} />);
    expect(none).toContain("Processing details are not part of this build");
    expect(none).not.toContain("demo-step");
  });
});
