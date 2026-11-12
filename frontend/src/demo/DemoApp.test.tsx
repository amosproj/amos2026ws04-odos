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
  id: "doc/teil-2", type: "part", germanType: "Teil", number: "2", marker: "Zweiter Teil", title: "Beispielteil", pages: [9],
  children: [{
    id: "doc/teil-2/par-6", type: "section", germanType: "Paragraph", number: "6", marker: "§ 6", title: "Beispiel", pages: [9],
    children: [
      { id: ABS, type: "subsection", germanType: "Absatz", number: "1", marker: "(1)", text: INTRO, pages: [9, 10], children: [
        { id: `${ABS}/nr-1`, type: "number", germanType: "Nummer", number: "1", marker: "1.", text: "erste Nummer", pages: [10] },
        { id: `${ABS}/nr-2`, type: "number", germanType: "Nummer", number: "2", marker: "2.", text: "zweite Nummer", pages: [10] },
      ] },
      { id: "doc/teil-2/par-6/abs-2", type: "subsection", germanType: "Absatz", number: "2", marker: "(2)", text: "zweiter Absatz", pages: [10] },
    ],
  }],
}, null, 2).replace(/\[\s+(\d+(?:,\s+\d+)*)\s+\]/g, (_m, ns: string) => `[${ns.split(/,\s+/).join(", ")}]`) + "\n";

const result: DemoResult = {
  title: "Musterbauordnung (MBO)",
  download: { href: "/demo/mbo/teil-2.legal.json", name: "teil-2.legal.json" },
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

describe("workspace page", () => {
  const html = renderToStaticMarkup(<DemoApp />);
  it("has the ODOS header: the logo with its subtitle and a minimal navigation", () => {
    const header = /<header class="site-nav">([\s\S]*?)<\/header>/.exec(html)![1];
    expect(header).toContain('aria-label="ODOS, ontology-driven operating system"');
    expect(header).toMatch(/<span class="logo-mark"[^>]*><span><b>O<\/b>D<\/span><span><b>O<\/b>S<\/span><\/span>/); // the stacked O D / O S
    expect(header).toContain("ONTOLOGY-DRIVEN<br/>OPERATING SYSTEM");
    expect(header.match(/<a /g)).toHaveLength(3); // logo, Documents, Processing: internal links only
    expect(header).toMatch(/<a [^>]*href="#library"[^>]*aria-current="page"[^>]*>Documents<\/a>/);
    expect(header).toMatch(/<a [^>]*href="#upload"[^>]*>Processing<\/a>/);
    expect(header).toContain('href="#top"'); // the logo stays on this page
  });
  it("links nowhere outside the application: no external website link anywhere on the page", () => {
    expect(html).not.toMatch(/href="(https?:)?\/\//);
    expect(html).not.toMatch(/odos-chi|vercel|ODOS website|target="_blank"/i);
    for (const href of html.matchAll(/href="([^"]*)"/g)) expect(href[1]).toMatch(/^#/);
  });
  it("is a workspace, not a landing page: heading, description, upload, then the library", () => {
    expect(html).toMatch(/<h1[^>]*>Your documents<\/h1>/);
    expect(html).toContain("Upload, process and review German and EU legal documents.");
    expect(html).toContain('type="file"');
    expect(html).toContain('accept="application/pdf,.pdf"');
    expect(html).toContain("Choose a PDF or drop it here");
    expect(html).toMatch(/<button[^>]*disabled=""[^>]*>Process document<\/button>/); // nothing chosen yet
    expect(html).not.toContain('role="alert"');
    expect(html).toContain('id="upload"');
    expect(html).toContain('id="library"');
    expect(html.indexOf("Your documents")).toBeLessThan(html.indexOf("Document library"));
    expect(html).not.toMatch(/hero|pricing|testimonial|statistics/i);
  });
  it("shows the document library below, loading its data from the backend", () => {
    expect(html).toContain(">Document library</h2>");
    expect(html).toContain("Loading documents…"); // the first render, before the list request has answered
    expect(html).not.toContain("demo-docitem"); // no example records
  });
});

describe("result view", () => {
  const html = renderToStaticMarkup(<ResultView result={result} pdfUrl="blob:pdf" onReset={() => {}} />);
  it("shows the PDF on the left and the structure tree on the right", () => {
    expect(html).toContain('aria-label="Original PDF"');
    expect(html).toContain('data-url="blob:pdf"');
    expect(html).toContain('aria-label="Recognized legal structure"');
    // the docbar: no "precomputed result" chip since the prepared example mode was removed, every result is live
    const docbar = /<div class="docbar">([\s\S]*?)<\/div>/.exec(html)![1];
    expect(docbar).toContain('aria-label="ODOS, ontology-driven operating system"'); // the compact logo, without the subtitle
    expect(docbar).not.toContain("ONTOLOGY-DRIVEN");
    expect(docbar.replace(/<span class="logo-mark"[\s\S]*?<\/span><\/span>/, "").replace(/<[^>]+>/g, "|").split("|").filter((t) => t.trim())).toEqual(["Musterbauordnung (MBO)", "Completed", "Back to documents"]);
    expect(html).toContain("Legal structure");
    expect(html).toContain("Artifacts");
    expect(html.match(/role="tab"/g)).toHaveLength(2); // Legal structure and Artifacts only
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
    expect(text).not.toMatch(/sourceSpans|bbox|charStart|bboxScope|omittedChildren|nativeType/);
    expect(teil.germanType).toBe("Teil");
  });
  it("offers the excerpt for download", () => {
    expect(preview(html, "Custom Legal JSON").card).toContain('href="/demo/mbo/teil-2.legal.json" download="teil-2.legal.json"');
  });
  it("shows no Akoma Ntoso XML", () => {
    expect(html).not.toMatch(/Akoma|\.akn\.xml/);
  });
});
