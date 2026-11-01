import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { box, el, modelOf } from "../testing";
import DemoApp, { Artifacts, ResultView } from "./DemoApp";
import type { DemoResult } from "./fixtures";

// the PDF viewer needs a browser (pdf.js, canvas): replaced by a stub that shows what the demo hands to it
vi.mock("../components/PdfViewer", () => ({
  PdfViewer: (p: { url: string; page: number; highlights: unknown[] }) => (
    <div className="pdf-stub" data-url={p.url} data-page={p.page} data-highlights={p.highlights.length} />
  ),
}));

// An invented provision with the shape of § 6 (1): the introduction runs over a page break, two numbered children follow.
const ABS = "doc/teil-2/par-6/abs-1";
const INTRO = "1 Erster Satz beginnt am Seitenende und geht auf der nächsten Seite weiter. 2 Zweiter Satz.";
const json = JSON.stringify({
  id: "doc/teil-2/par-6", type: "section", marker: "§ 6", title: "Beispiel",
  children: [{
    id: ABS, type: "subsection", marker: "(1)", text: INTRO,
    source: { pages: [9, 10], sourceSpans: [{ itemRef: "#/texts/144", page: 9 }, { itemRef: "#/texts/146", page: 10 }] },
    children: [
      { id: `${ABS}/nr-1`, type: "number", marker: "1.", text: "erste Nummer", source: { pages: [10], sourceSpans: [{ itemRef: "#/texts/147", page: 10 }] } },
      { id: `${ABS}/nr-2`, type: "number", marker: "2.", text: "zweite Nummer", source: { pages: [10], sourceSpans: [{ itemRef: "#/texts/148", page: 10 }] } },
    ],
  }],
}, null, 2) + "\n";
const xml = `<?xml version='1.0' encoding='UTF-8'?>\n<article eId="part_2__art_6">\n  <paragraph eId="part_2__art_6__para_1">\n    <intro><p odos:src="#/texts/144 #/texts/146">${INTRO}</p></intro>\n  </paragraph>\n</article>\n`;

const result: DemoResult = {
  doc: {
    id: "mbo", title: "Musterbauordnung (MBO)", pdfSha256: "0".repeat(64), pages: 83, profile: "german_law",
    files: { structure: "mbo/structure.json", json: "mbo/teil-2_par-6.legal.json", xml: "mbo/teil-2_par-6.akn.xml" },
    example: { label: "§ 6 Beispiel", modelId: "doc/teil-2/par-6", eId: "part_2__art_6", aknElement: "article", legalJsonSchemaVersion: "1.1", previewId: ABS },
    sources: { documentModelSha256: "", legalJsonSha256: "", aknXmlSha256: "" },
  },
  model: modelOf([
    el("doc", "document", null, ["doc/teil-2"], { region: "document" }),
    el("doc/teil-2", "teil", "doc", ["doc/teil-2/par-6"], { marker: "Zweiter Teil", pages: [9] }),
    el("doc/teil-2/par-6", "paragraph", "doc/teil-2", [ABS], { marker: "§ 6", title: "Beispiel", pages: [9] }),
    el(ABS, "absatz", "doc/teil-2/par-6", [`${ABS}/nr-1`, `${ABS}/nr-2`], {
      marker: "(1)", original_text: INTRO, pages: [9, 10], source_refs: ["#/texts/144", "#/texts/146"],
      provenance: [box(9, 65, 63, 531, 52), box(10, 65, 776, 531, 696)],
    }),
    el(`${ABS}/nr-1`, "nummer", ABS, [], { marker: "1.", original_text: "erste Nummer", pages: [10] }),
    el(`${ABS}/nr-2`, "nummer", ABS, [], { marker: "2.", original_text: "zweite Nummer", pages: [10] }),
  ]),
  json, xml,
};

const preview = (html: string, title: string) => {
  const card = html.split('<section class="demo-artifact">').find((c) => c.includes(title))!;
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
    expect(html).toContain("Select an element to highlight its source text in the PDF.");
  });
  it("starts on page 1 without highlights; the tree shows the hierarchy", () => {
    expect(html).toContain('data-page="1"');
    expect(html).toContain('data-highlights="0"');
    expect(html).toContain("Zweiter Teil");
    expect(html).not.toContain("badge");
  });
});

describe("JSON and Akoma Ntoso XML previews and downloads", () => {
  const html = renderToStaticMarkup(<Artifacts result={result} onShow={() => {}} />);
  it("names the provision both artifacts show", () => {
    expect(html).toContain("§ 6 Beispiel");
    expect(html).toContain("Show it in the PDF");
  });
  it("previews the complete Absatz subtree as in the downloaded JSON: full text, sources and both children", () => {
    const { text } = preview(html, "Legal Document JSON");
    const node = JSON.parse(text);
    expect(node.id).toBe(ABS);
    expect(node.text).toBe(INTRO);
    expect(node.source.pages).toEqual([9, 10]);
    expect(node.source.sourceSpans.map((s: { itemRef: string }) => s.itemRef)).toEqual(["#/texts/144", "#/texts/146"]);
    expect(node.children.map((c: { id: string; marker: string }) => [c.id, c.marker])).toEqual([[`${ABS}/nr-1`, "1."], [`${ABS}/nr-2`, "2."]]);
    expect(node.children.map((c: { text: string }) => c.text)).toEqual(["erste Nummer", "zweite Nummer"]);
    expect(text).not.toContain("part_2__art_6"); // not the whole excerpt, just the subtree
  });
  it("previews the XML excerpt with one introduction paragraph attributed to both sources", () => {
    const { text } = preview(html, "Akoma Ntoso XML");
    expect(text).toBe(xml.replace(/\n$/, ""));
    expect(text).toContain('odos:src="#/texts/144 #/texts/146"');
  });
  it("offers both files for download", () => {
    expect(preview(html, "Legal Document JSON").card).toContain('href="/demo/mbo/teil-2_par-6.legal.json" download="teil-2_par-6.legal.json"');
    expect(preview(html, "Akoma Ntoso XML").card).toContain('href="/demo/mbo/teil-2_par-6.akn.xml" download="teil-2_par-6.akn.xml"');
  });
  it("cuts a long preview without a previewId and reports the hidden lines", () => {
    const long: DemoResult = { ...result, json: Array.from({ length: 60 }, (_, i) => `"line ${i}"`).join("\n"), doc: { ...result.doc, example: { ...result.doc.example, previewId: undefined } } };
    const card = preview(renderToStaticMarkup(<Artifacts result={long} onShow={() => {}} />), "Legal Document JSON").card;
    expect(card).toContain("20 more lines in the download.");
  });
});
