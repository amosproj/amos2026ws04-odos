// @vitest-environment jsdom
// Navigation between Document Review and the Rule Extraction preview, and the preview's own local interactions
// (filtering, search, rule selection, tabs, the Ontology/Digital Twin toggle). Everything here is UI-only: no network
// call is made, so these tests only pin down behaviour that is entirely client-side.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { el, modelOf } from "../testing";
import { ResultView } from "./DemoApp";
import type { DemoResult } from "./fixtures";
import { RuleExtractionView } from "./RuleExtraction";
import { AUTO_ACCEPTED_COUNT, MOCK_RULES, NEEDS_REVIEW_COUNT } from "./ruleExtractionMock";

vi.mock("../components/PdfViewer", () => ({
  PdfViewer: () => <div className="pdf-stub" />,
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const result: DemoResult = {
  title: "MUSTERBAUORDNUNG",
  filename: "MusterBauVerordnung.pdf",
  model: modelOf([el("doc", "document", null, [], { region: "document" })], { source: { num_pages: 83 } }),
  json: '{\n  "schemaVersion": "2.0"\n}\n',
  download: { href: "/api/jobs/j1/files/document.json?download=true", name: "MusterBauVerordnung.legal.json" },
};

let host: HTMLElement;
let root: Root;
const settle = async () => { for (let i = 0; i < 3; i++) await act(async () => { await Promise.resolve(); }); };
const mount = async (node: React.ReactElement) => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => { root.render(node); });
  await settle();
};
const q = <T extends Element = HTMLElement>(sel: string) => host.querySelector<T>(sel);
const qa = <T extends Element = HTMLElement>(sel: string) => [...host.querySelectorAll<T>(sel)];
const button = (name: string) => qa<HTMLButtonElement>("button").find((b) => (b.textContent ?? "").trim() === name);
const click = async (target: Element | null | undefined) => { if (!target) throw new Error("nothing to click"); await act(async () => { (target as HTMLElement).click(); }); await settle(); };

beforeEach(() => { Element.prototype.scrollIntoView = () => {}; });
afterEach(() => { act(() => root.unmount()); host.remove(); });

describe("navigating from Document Review to Rule Extraction and back", () => {
  it("shows a primary 'Continue to Rule Extraction' button in the document review header that triggers navigation", async () => {
    const onContinueToRules = vi.fn();
    await mount(<ResultView result={result} pdfUrl="blob:pdf" onReset={() => {}} onContinueToRules={onContinueToRules} />);
    const cta = button("Continue to Rule Extraction");
    expect(cta).not.toBeUndefined();
    expect(cta!.className).toContain("primary");
    await click(cta);
    expect(onContinueToRules).toHaveBeenCalledTimes(1);
  });

  it("omits the button when no handler is given, so the existing review view is unaffected", () => {
    const html = renderToStaticMarkup(<ResultView result={result} pdfUrl="blob:pdf" onReset={() => {}} />);
    expect(html).not.toContain("Continue to Rule Extraction");
  });

  it("the Rule Extraction page shows a 'Back to Document Review' button that returns", async () => {
    const onBack = vi.fn();
    await mount(<RuleExtractionView result={result} onBack={onBack} />);
    const back = button("Back to Document Review");
    expect(back).not.toBeUndefined();
    await click(back);
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("preserves the document context: filename and page count carry over to the new page", async () => {
    await mount(<RuleExtractionView result={result} onBack={() => {}} />);
    expect(q(".docbar h2")?.textContent).toBe("MusterBauVerordnung.pdf");
    expect(host.textContent).toContain("83 pages");
  });
});

describe("Rule Extraction page layout", () => {
  it("shows the three-step workflow indicator with step 2 current", async () => {
    await mount(<RuleExtractionView result={result} onBack={() => {}} />);
    const steps = qa(".rex-step");
    expect(steps).toHaveLength(3);
    expect(steps.map((s) => s.querySelector(".rex-step-label")?.textContent?.replace(/\s+/g, " ").trim())).toEqual([
      "Document Review",
      "LLM Rule Extraction & Review",
      "ValidationComing Soon",
    ]);
    expect(steps[0].className).toContain("done");
    expect(steps[1].className).toContain("current");
    expect(steps[2].className).toContain("upcoming");
  });

  it("shows the mock extraction overview numbers, clearly marked as mock data", async () => {
    await mount(<RuleExtractionView result={result} onBack={() => {}} />);
    expect(host.textContent).toContain(`${MOCK_RULES.length}`);
    expect(host.textContent).toContain("mock data");
    expect(host.textContent).toContain(`Auto-Accepted (${AUTO_ACCEPTED_COUNT} rules)`);
    expect(host.textContent).toContain(`Needs Review (${NEEDS_REVIEW_COUNT} rules)`);
  });

  it("marks unavailable actions as disabled and Coming Soon rather than pretending they work", async () => {
    await mount(<RuleExtractionView result={result} onBack={() => {}} />);
    for (const name of ["Restart Extraction", "Accept Rule", "Reject", "Edit JSON", "Show in PDF"]) {
      const btn = button(name);
      expect(btn, name).not.toBeUndefined();
      expect(btn!.disabled, name).toBe(true);
    }
    expect(button("Coming Soon")?.disabled).toBe(true); // the upload placeholder
  });
});

describe("filtering and searching the mock rule list", () => {
  it("All Rules shows every mock rule; Auto-Accepted and Needs Review filter by status", async () => {
    await mount(<RuleExtractionView result={result} onBack={() => {}} />);
    expect(qa(".rex-rule")).toHaveLength(MOCK_RULES.length);
    await click(button(`Auto-Accepted (${AUTO_ACCEPTED_COUNT})`));
    expect(qa(".rex-rule")).toHaveLength(AUTO_ACCEPTED_COUNT);
    expect(qa(".rex-rule .rex-status.review")).toHaveLength(0);
    await click(button(`Needs Review (${NEEDS_REVIEW_COUNT})`));
    expect(qa(".rex-rule")).toHaveLength(NEEDS_REVIEW_COUNT);
    expect(qa(".rex-rule .rex-status.auto")).toHaveLength(0);
    await click(button(`All Rules (${MOCK_RULES.length})`));
    expect(qa(".rex-rule")).toHaveLength(MOCK_RULES.length);
  });

  it("searches by rule id or title", async () => {
    await mount(<RuleExtractionView result={result} onBack={() => {}} />);
    const search = q<HTMLInputElement>('input[type="search"]')!;
    const setValue = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")!.set!;
    await act(async () => {
      setValue.call(search, "Türen");
      search.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await settle();
    expect(qa(".rex-rule")).toHaveLength(1);
    expect(q(".rex-rule-title")?.textContent).toBe("Mindestbreite von Türen");
  });

  it("falls back to the first match when the selected rule is filtered out", async () => {
    await mount(<RuleExtractionView result={result} onBack={() => {}} />);
    const firstReview = MOCK_RULES.find((r) => r.status === "review")!;
    await click(button(`Needs Review (${NEEDS_REVIEW_COUNT})`));
    expect(q(".rex-detail-id")?.textContent).toBe(firstReview.id);
  });
});

describe("selecting a rule and reading its detail", () => {
  it("shows the selected rule's id, title, confidence and Rule JSON by default", async () => {
    await mount(<RuleExtractionView result={result} onBack={() => {}} />);
    const r2 = MOCK_RULES[1];
    await click(qa(".rex-rule")[1]);
    expect(q(".rex-detail-id")?.textContent).toBe(r2.id);
    expect(q(".rex-detail-title strong")?.textContent).toBe(r2.title);
    expect(q(".rex-confidence")?.textContent).toBe(`Confidence: ${r2.confidence.toFixed(2)}`);
    expect(q(".rex-detail .preview")?.textContent).toContain(`"rule_id": "${r2.id}"`);
  });

  it("switches to Source Text and back without losing the selection", async () => {
    await mount(<RuleExtractionView result={result} onBack={() => {}} />);
    const r1 = MOCK_RULES[0];
    await click([...qa('[role="tab"]')].find((t) => t.textContent === "Source Text"));
    expect(q(".rex-sourcetext")?.textContent).toBe(r1.sourceText);
    expect(q(".rex-detail .preview")).toBeNull();
    await click([...qa('[role="tab"]')].find((t) => t.textContent === "Rule JSON"));
    expect(q(".rex-detail .preview")).not.toBeNull();
    expect(q(".rex-detail-id")?.textContent).toBe(r1.id);
  });
});

describe("Ontology / Digital Twin toggle", () => {
  it("only one source is selected at a time, and the upload label follows the selection", async () => {
    await mount(<RuleExtractionView result={result} onBack={() => {}} />);
    const ontology = button("Ontology")!;
    const digitalTwin = button("Digital Twin")!;
    expect(ontology.getAttribute("aria-pressed")).toBe("true");
    expect(digitalTwin.getAttribute("aria-pressed")).toBe("false");
    expect(host.textContent).toContain("Upload ontology file (JSON)");
    await click(digitalTwin);
    expect(ontology.getAttribute("aria-pressed")).toBe("false");
    expect(digitalTwin.getAttribute("aria-pressed")).toBe("true");
    expect(host.textContent).toContain("Upload digital twin file (JSON)");
  });
});
