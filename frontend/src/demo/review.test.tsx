// @vitest-environment jsdom
// The review interface (PDF on the left, legal structure on the right) with real clicks and pointer events: the selection
// logic is the existing one, these tests pin that it keeps working under the new look and the resizable divider.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clampSplit, HANDLE_PX, MIN_PANEL_PX } from "../components/SplitDivider";
import { highlightsOf } from "../structure";
import { box, el, modelOf } from "../testing";
import { ResultView } from "./DemoApp";
import type { DemoResult } from "./fixtures";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// the PDF viewer needs pdf.js and a canvas: a stub that shows what the review view hands to it
let viewerMounts = 0;
vi.mock("../components/PdfViewer", async () => {
  const { useEffect } = await import("react");
  return {
    PdfViewer: (p: { url: string; page: number; highlights: unknown[]; onPageChange: (n: number) => void }) => {
      useEffect(() => { viewerMounts++; }, []);
      return (
        <div className="pdf-stub" data-url={p.url} data-page={p.page} data-highlights={p.highlights.length}>
          <button onClick={() => p.onPageChange(p.page + 1)}>stub next</button>
        </div>
      );
    },
  };
});

const TEIL = "doc/teil-2";
const PAR = "doc/teil-2/par-6";
const ABS = "doc/teil-2/par-6/abs-1";
const TEIL3 = "doc/teil-3";
const model = {
  ...modelOf([
    el("doc", "document", null, [TEIL, TEIL3], { region: "document" }),
    el(TEIL, "teil", "doc", [PAR], { marker: "Zweiter Teil", title: "Das Grundstück", pages: [9], source_refs: ["#/texts/10"], provenance: [box(9, 60, 700, 300, 688)] }),
    el(PAR, "paragraph", TEIL, [ABS], { marker: "§ 6", title: "Abstandsflächen", pages: [9, 10], source_refs: ["#/texts/144", "#/texts/146"], provenance: [box(9, 65, 600, 500, 580), box(10, 65, 776, 500, 700)] }),
    el(ABS, "absatz", PAR, [], { marker: "(1)", original_text: "(1) Vor den Außenwänden von Gebäuden sind Abstandsflächen freizuhalten.", pages: [10], source_refs: ["#/texts/147"], provenance: [box(10, 65, 650, 500, 630)] }),
    el(TEIL3, "teil", "doc", [], { marker: "Dritter Teil", title: "Bauliche Anlagen", pages: [12], source_refs: ["#/texts/200"], provenance: [box(12, 60, 700, 300, 688)] }),
  ]),
  metadata: { title: "Musterbauordnung" },
};
const legal = {
  schemaVersion: "2.0", id: "mbo", title: "Musterbauordnung", frontMatter: [], tableOfContents: [], footnotes: [],
  structure: [{ id: TEIL3, type: "part", nativeType: "Teil", number: "3", marker: "Dritter Teil", title: "Bauliche Anlagen", pages: [12], children: [] }],
};
const result: DemoResult = {
  title: "MUSTERBAUORDNUNG",
  filename: "MusterBauVerordnung.pdf",
  model,
  json: '{\n  "schemaVersion": "2.0"\n}\n',
  download: { href: "/api/jobs/j1/files/document.json?download=true", name: "MusterBauVerordnung.legal.json" },
  live: { jobId: "j1", persistent: true, legal },
};

let host: HTMLElement;
let root: Root;
let back = vi.fn();

const settle = async () => { for (let i = 0; i < 4; i++) await act(async () => { await Promise.resolve(); }); };
const mount = async (r: DemoResult = result) => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => { root.render(<ResultView result={r} pdfUrl="blob:pdf" onReset={back} />); });
  await settle();
};
const q = <T extends Element = HTMLElement>(sel: string) => host.querySelector<T>(sel);
const node = (id: string) => document.getElementById(`node-${id}`) as HTMLElement;
const text = () => host.textContent ?? "";
const button = (name: string) => [...host.querySelectorAll("button")].find((b) => (b.getAttribute("aria-label") ?? b.textContent ?? "").trim() === name) as HTMLButtonElement;
const click = async (target: Element | null | undefined) => { if (!target) throw new Error("nothing to click"); await act(async () => { (target as HTMLElement).click(); }); await settle(); };
const stub = () => q(".pdf-stub")!;
const expandAll = () => click(button("Expand all"));
const SPLIT_WIDTH = 1014; // 1000 px beside the 14 px divider; jsdom has no layout, so the container is given a width
const measure = () => { q(".split")!.getBoundingClientRect = () => ({ left: 0, top: 0, right: SPLIT_WIDTH, bottom: 600, width: SPLIT_WIDTH, height: 600, x: 0, y: 0, toJSON: () => ({}) }); };

beforeEach(() => {
  viewerMounts = 0;
  back = vi.fn();
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.scrollIntoView = () => {}; // not implemented by jsdom; the tree scrolls the selected row into view
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

describe("review header", () => {
  it("shows the logo, the file name, the status and Back to documents, and links nowhere outside the app", async () => {
    await mount();
    const bar = q(".docbar")!;
    expect(bar.querySelector('[aria-label="ODOS, ontology-driven operating system"]')).not.toBeNull();
    expect(bar.querySelector("h2")?.textContent).toBe("MusterBauVerordnung.pdf");
    expect(bar.querySelector("h2")?.getAttribute("title")).toContain("MUSTERBAUORDNUNG"); // the document's own title stays available
    expect(bar.querySelector(".demo-status.ok")?.textContent).toBe("Completed");
    expect(host.querySelectorAll("a[href^='http'], a[target='_blank']")).toHaveLength(0);
    await click(button("Back to documents"));
    expect(back).toHaveBeenCalledTimes(1);
  });

  it("falls back to the document title when the file name is not known", async () => {
    await mount({ ...result, filename: undefined });
    expect(q(".docbar h2")?.textContent).toBe("MUSTERBAUORDNUNG");
  });
});

describe("selecting an element", () => {
  it("highlights the selected row and nothing else", async () => {
    await mount();
    expect(q(".node.selected")).toBeNull();
    await click(node(PAR));
    expect([...host.querySelectorAll(".node.selected")].map((n) => n.id)).toEqual([`node-${PAR}`]);
    await click(node(TEIL3));
    expect([...host.querySelectorAll(".node.selected")].map((n) => n.id)).toEqual([`node-${TEIL3}`]);
  });

  it("jumps to the element's first page and hands its provenance boxes to the PDF viewer", async () => {
    await mount();
    expect(stub().getAttribute("data-page")).toBe("1");
    expect(stub().getAttribute("data-highlights")).toBe("0");
    await click(node(PAR));
    expect(stub().getAttribute("data-page")).toBe("9");
    expect(Number(stub().getAttribute("data-highlights"))).toBe(highlightsOf(model.elements.find((e) => e.id === PAR)!).boxes.length);
    expect(Number(stub().getAttribute("data-highlights"))).toBeGreaterThan(0);
    await click(node(TEIL3));
    expect(stub().getAttribute("data-page")).toBe("12");
    expect(stub().getAttribute("data-url")).toBe("blob:pdf");
  });

  it("shows the element's own data in the details: type, marker, title, text, pages, source and id, and nothing invented", async () => {
    await mount();
    expect(q(".detail.empty")?.textContent).toBe("Select an element to highlight its source text in the PDF.");
    await expandAll();
    await click(node(ABS));
    const detail = q(".detail")!;
    expect(detail.classList.contains("empty")).toBe(false);
    expect(detail.querySelector("h3")?.textContent).toMatch(/\(1\)/); // type label and marker
    expect(detail.querySelector(".origtext")?.textContent).toBe("(1) Vor den Außenwänden von Gebäuden sind Abstandsflächen freizuhalten.");
    const rows = Object.fromEntries([...detail.querySelectorAll("dt")].map((dt) => [dt.textContent, dt.nextElementSibling?.textContent]));
    expect(rows).toEqual({ Pages: "p. 10", Source: "#/texts/147", "Element id": ABS });
    await click(node(PAR));
    expect(q(".detail .title")?.textContent).toBe("Abstandsflächen");
    expect(q(".detail dd")?.textContent).toBe("p. 9p. 10");
  });

  it("goes to another page of the element from the details, keeping the selection", async () => {
    await mount();
    await click(node(PAR));
    await click([...host.querySelectorAll(".detail button.link")].find((b) => b.textContent === "p. 10"));
    expect(stub().getAttribute("data-page")).toBe("10");
    expect(q(".node.selected")?.id).toBe(`node-${PAR}`);
  });

  it("keeps the selection and the page when the PDF is paged by hand", async () => {
    await mount();
    await click(node(TEIL));
    await click(button("stub next"));
    expect(stub().getAttribute("data-page")).toBe("10");
    expect(q(".node.selected")?.id).toBe(`node-${TEIL}`);
  });
});

describe("expanding and collapsing", () => {
  it("opens and closes branches without losing the selection", async () => {
    await mount();
    expect(node(ABS)).toBeNull(); // a paragraph's children are closed at first
    await click(node(PAR));
    await click(node(PAR).querySelector(".twisty"));
    expect(node(ABS)).not.toBeNull(); // the twisty opens it ...
    expect(q(".node.selected")?.id).toBe(`node-${PAR}`); // ... and the selection stays
    expect(node(PAR).querySelector(".twisty")?.classList.contains("open")).toBe(true);
    await click(node(PAR).querySelector(".twisty"));
    expect(node(ABS)).toBeNull();
    expect(q(".node.selected")?.id).toBe(`node-${PAR}`);
    expect(stub().getAttribute("data-page")).toBe("9");
  });

  it("Expand all and Collapse all change what is shown, not what is selected", async () => {
    await mount();
    await click(node(PAR));
    await expandAll();
    expect(node(ABS)).not.toBeNull();
    expect(q(".node.selected")?.id).toBe(`node-${PAR}`);
    await click(button("Collapse all"));
    expect(node(ABS)).toBeNull();
    expect(text()).toContain("Abstandsflächen"); // the details still show the selected element
    await expandAll();
    expect(q(".node.selected")?.id).toBe(`node-${PAR}`); // the row is selected again as soon as it is visible
  });

  it("selecting a row does not close the other branches", async () => {
    await mount();
    await expandAll();
    await click(node(TEIL3));
    expect(node(ABS)).not.toBeNull();
    expect(node(PAR)).not.toBeNull();
  });
});

describe("resizing the panels", () => {
  const split = () => q(".split")!;
  const divider = () => q('[role="separator"]')!;
  const pointer = async (type: string, x = 0) => {
    const E = typeof PointerEvent === "function" ? PointerEvent : MouseEvent;
    await act(async () => { divider().dispatchEvent(new E(type, { bubbles: true, cancelable: true, clientX: x, button: 0, pointerId: 1 })); });
  };
  const drag = async (to: number) => { await pointer("pointerdown", 500); await pointer("pointermove", to); await pointer("pointerup", to); };
  const columns = () => [split().style.getPropertyValue("--left"), split().style.getPropertyValue("--right")];

  it("is a focusable vertical separator between the two panels, starting at about 50/50", async () => {
    await mount();
    expect(divider().getAttribute("aria-orientation")).toBe("vertical");
    expect(divider().getAttribute("aria-valuenow")).toBe("50");
    expect(divider().tabIndex).toBe(0);
    expect([...split().children].map((c) => c.className.split(" ")[0])).toEqual(["pane", "splitter", "pane"]);
    expect(columns()).toEqual(["500.0fr", "500.0fr"]);
  });

  it("follows the pointer while dragging and keeps the new split afterwards", async () => {
    await mount();
    measure();
    await pointer("pointerdown", 507);
    expect(divider().classList.contains("active")).toBe(true);
    await pointer("pointermove", 400 + HANDLE_PX / 2); // 400 px for the left panel
    expect(columns()).toEqual(["400.0fr", "600.0fr"]);
    await pointer("pointermove", 650 + HANDLE_PX / 2);
    expect(columns()).toEqual(["650.0fr", "350.0fr"]); // it follows the pointer
    await pointer("pointerup", 650);
    expect(divider().classList.contains("active")).toBe(false);
    expect(divider().getAttribute("aria-valuenow")).toBe("65"); // the split is kept
    expect(columns()).toEqual(["650.0fr", "350.0fr"]);
  });

  it("never lets either panel get narrower than the minimum", async () => {
    await mount();
    measure();
    await drag(-200); // far past the left edge
    expect(columns()).toEqual([`${MIN_PANEL_PX}.0fr`, `${1000 - MIN_PANEL_PX}.0fr`]);
    await drag(5000); // far past the right edge
    expect(columns()).toEqual([`${1000 - MIN_PANEL_PX}.0fr`, `${MIN_PANEL_PX}.0fr`]);
    expect(divider().getAttribute("aria-valuenow")).toBe("68");
    expect(split().style.getPropertyValue("--left")).not.toBe("");
    // and the style sheet guarantees the same minimum when the window is made narrower later
    expect(readFileSync(resolve(__dirname, "../styles.css"), "utf8")).toMatch(/grid-template-columns: minmax\(var\(--min-panel, 320px\), var\(--left, 1fr\)\) 14px minmax\(var\(--min-panel, 320px\), var\(--right, 1fr\)\)/);
  });

  it("keeps the selected element, the PDF page and the PDF viewer itself while resizing", async () => {
    await mount();
    measure();
    await click(node(PAR));
    const before = stub();
    const mounted = viewerMounts;
    await drag(300);
    await drag(800);
    expect(q(".node.selected")?.id).toBe(`node-${PAR}`);
    expect(stub().getAttribute("data-page")).toBe("9");
    expect(Number(stub().getAttribute("data-highlights"))).toBeGreaterThan(0);
    expect(stub()).toBe(before); // the same element: not rebuilt, so the PDF is not reloaded
    expect(viewerMounts).toBe(mounted);
    expect(q(".detail")?.textContent).toContain("Abstandsflächen");
  });

  it("can be operated with the keyboard", async () => {
    await mount();
    measure();
    const press = async (key: string, shiftKey = false) => { await act(async () => { divider().dispatchEvent(new KeyboardEvent("keydown", { key, shiftKey, bubbles: true, cancelable: true })); }); };
    await press("ArrowRight");
    expect(divider().getAttribute("aria-valuenow")).toBe("52");
    await press("ArrowLeft");
    await press("ArrowLeft");
    expect(divider().getAttribute("aria-valuenow")).toBe("48");
    await press("ArrowRight", true); // a larger step with Shift
    expect(divider().getAttribute("aria-valuenow")).toBe("58");
    await press("Home");
    expect(divider().getAttribute("aria-valuenow")).toBe("32");
    await press("End");
    expect(divider().getAttribute("aria-valuenow")).toBe("68");
    await press("Enter");
    expect(divider().getAttribute("aria-valuenow")).toBe("50");
    expect(columns()).toEqual(["500.0fr", "500.0fr"]);
    await press("a"); // other keys are left alone
    expect(divider().getAttribute("aria-valuenow")).toBe("50");
  });

  it("goes back to an even split on a double click", async () => {
    await mount();
    measure();
    await drag(400);
    expect(divider().getAttribute("aria-valuenow")).not.toBe("50");
    await act(async () => { divider().dispatchEvent(new MouseEvent("dblclick", { bubbles: true })); });
    expect(divider().getAttribute("aria-valuenow")).toBe("50");
  });

  it("ignores moves when no drag is going on", async () => {
    await mount();
    measure();
    await pointer("pointermove", 100);
    expect(columns()).toEqual(["500.0fr", "500.0fr"]);
  });
});

describe("clampSplit", () => {
  it("keeps both panels at the minimum width", () => {
    expect(clampSplit(0.5, 1014)).toBe(0.5);
    expect(clampSplit(0, 1014)).toBeCloseTo(320 / 1000);
    expect(clampSplit(1, 1014)).toBeCloseTo(1 - 320 / 1000);
    expect(clampSplit(0.1, 1014, 200)).toBeCloseTo(0.2);
  });
  it("splits evenly when the container is too narrow for two minimum panels", () => {
    expect(clampSplit(0.9, 600)).toBe(0.5);
    expect(clampSplit(0.1, 0)).toBe(0.5);
    expect(clampSplit(0.7, NaN)).toBe(0.5);
  });
});

describe("responsive layout", () => {
  const css = readFileSync(resolve(__dirname, "../styles.css"), "utf8");
  const stacked = css.slice(css.indexOf("@media (max-width: 1000px)"), css.indexOf("/* ---- PDF viewer"));

  it("stacks the panels and drops the divider on small screens", () => {
    expect(stacked).toMatch(/\.split \{ grid-template-columns: minmax\(0, 1fr\);/);
    expect(stacked).toMatch(/\.splitter \{ display: none; \}/);
    expect(stacked).toMatch(/\.pane \{ height: 80vh; \}/);
  });

  it("keeps the divider as a real element on desktop, so that it can be hidden by the style sheet only", async () => {
    await mount();
    expect(q(".splitter")).not.toBeNull();
    expect(css).toMatch(/\.splitter \{[^}]*cursor: col-resize;[^}]*touch-action: none;/);
  });
});

describe("tabs and artifacts", () => {
  const tab = (name: string) => [...host.querySelectorAll('[role="tab"]')].find((t) => t.textContent === name)!;

  it("switches between the legal structure and the artifacts", async () => {
    await mount();
    expect([...host.querySelectorAll('[role="tab"]')].map((t) => [t.textContent, t.getAttribute("aria-selected")])).toEqual([["Legal structure", "true"], ["Artifacts", "false"]]);
    await click(tab("Artifacts"));
    expect(tab("Artifacts").getAttribute("aria-selected")).toBe("true");
    expect(q(".structure")).toBeNull();
    expect(text()).toContain("Custom Legal JSON");
    expect(q('a[download="MusterBauVerordnung.legal.json"]')?.getAttribute("href")).toBe("/api/jobs/j1/files/document.json?download=true");
    expect(text()).toContain("Docling Raw JSON");
  });

  it("shows the selected element's JSON, or the whole document, and offers the download either way", async () => {
    await mount();
    await click(node(TEIL3));
    await click(tab("Artifacts"));
    expect(q(".demo-code")?.textContent).toContain('"id": "doc/teil-3"'); // the selected element's node
    expect(q(".demo-code")?.textContent).not.toContain("schemaVersion");
    await click(button("Full document"));
    expect(q(".demo-code")?.textContent).toContain('"schemaVersion": "2.0"');
    expect(button("Full document").getAttribute("aria-pressed")).toBe("true");
    expect(q("a[download]")).not.toBeNull();
  });

  it("comes back to the structure with the selection, the page and the panel split intact", async () => {
    await mount();
    measure();
    await click(node(PAR));
    const sep = q('[role="separator"]')!;
    await act(async () => { sep.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true, cancelable: true })); });
    expect(sep.getAttribute("aria-valuenow")).toBe("52");
    await click(tab("Artifacts"));
    await click(tab("Legal structure"));
    expect(q(".node.selected")?.id).toBe(`node-${PAR}`);
    expect(stub().getAttribute("data-page")).toBe("9");
    expect(q('[role="separator"]')?.getAttribute("aria-valuenow")).toBe("52");
    expect(q(".detail .title")?.textContent).toBe("Abstandsflächen");
  });
});
