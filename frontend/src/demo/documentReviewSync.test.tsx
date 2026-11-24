// @vitest-environment jsdom
// Document Review shows the persisted review decisions of the rules on the elements they cite, and leads from a cited element to
// its rules. The backend is faked; with no review storage nothing is shown and nothing is invented.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ResultView } from "./DemoApp";
import type { RuleReviewEntry } from "./live";
import { RuleExtractionView, type RulesNav } from "./RuleExtraction";
import { sha256Hex } from "../sha256";
import { ABS1, ABS2, demoResult, generation, model, rule, rulesFile } from "./ruleTestData";

const pdf = vi.hoisted(() => ({ last: null as null | { groups?: Array<{ tone?: string; status?: string; edited?: boolean }>; highlights: unknown[] } }));
vi.mock("../components/PdfViewer", () => ({ PdfViewer: (props: { groups?: Array<{ tone?: string; status?: string; edited?: boolean }>; highlights: unknown[] }) => { pdf.last = props; return <div className="pdf-stub" />; } }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const TEXT1 = "(1) Türen müssen mindestens 0,90 m breit sein."; // the fixture's ABS1 has content_text = its id; give it real text
const doc = {
  ...model,
  elements: model.elements.map((e) => (e.id === ABS1 ? { ...e, content_text: TEXT1 } : e)),
  sentences: [{ id: `${ABS1}/satz-1`, unit_id: ABS1, number: "1", ranges: [{ element_id: ABS1, start: 0, end: 11, text_sha256: sha256Hex(TEXT1) }] }],
};
const A = rule("regel-a", "Regel A", ABS1, {}, {}); // two rules on the same element, one of them naming a sentence
const B = { ...rule("regel-b", "Regel B", ABS1, {}, {}), source: { ...(rule("x", "x", ABS1) as { source: object }).source, citation: "§ 1 B", elements: [{ elementId: ABS1, sentenceId: `${ABS1}/satz-1`, role: "primary", pdfPages: [3] }] } };
const C = rule("regel-c", "Regel C", ABS2, {});
const FILE = rulesFile([A, B, C]);
const EXTRACTION = String(generation.generatedAt);
const entry = (over: Partial<RuleReviewEntry>): RuleReviewEntry => ({ ruleSha256: "a".repeat(64), state: "pending", edited: false, verification: "unverified", lastEventId: 0, reviewer: null, reason: null, at: null, effectiveRule: null, ...over });
const json = (body: unknown, code = 200) => new Response(JSON.stringify(body), { status: code, headers: { "Content-Type": "application/json" } });

let reviews: Record<string, RuleReviewEntry> | null;
let calls: string[];
const install = (over: Record<string, Partial<RuleReviewEntry>> = {}, enabled = true) => {
  reviews = Object.fromEntries(["regel-a", "regel-b", "regel-c"].map((id) => [id, entry(over[id] ?? {})]));
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push(`${init?.method ?? "GET"} ${url}`);
    if (url.endsWith("/rule-extraction")) return json({ status: "completed", scope: "document", requestedAt: "2026-11-20T10:00:00+00:00" });
    if (url.endsWith("/files/rules.json")) return json(FILE);
    if (url.endsWith("/rule-reviews")) {
      if (!enabled) return json({ detail: "Review storage is not initialised" }, 503);
      return json({ extractionId: EXTRACTION, criteriaVersion: 1, counts: { pending: 0, accepted: 0, rejected: 0, edited: 0 }, rules: reviews, earlierExtractionEvents: 0 });
    }
    return json({ detail: "unexpected" }, 500);
  }));
};

let host: HTMLElement;
let root: Root;
const flush = async () => { await act(async () => { await vi.advanceTimersByTimeAsync(0); }); };
const q = <T extends Element = HTMLElement>(sel: string) => document.body.querySelector<T>(sel);
const qa = <T extends Element = HTMLElement>(sel: string) => [...document.body.querySelectorAll<T>(sel)];
const click = async (el: Element | null | undefined) => { if (!el) throw new Error("nothing to click"); await act(async () => { (el as HTMLElement).click(); }); await flush(); };
const result = () => ({ ...demoResult(FILE), model: doc });
const mount = async (node: React.ReactElement) => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => { root.render(node); });
  await flush(); await flush();
};
beforeEach(() => { vi.useFakeTimers(); window.localStorage.clear(); window.scrollTo = () => {}; Element.prototype.scrollIntoView = () => {}; pdf.last = null; });
afterEach(() => { act(() => root.unmount()); host.remove(); vi.useRealTimers(); vi.unstubAllGlobals(); });
const marksOf = (id: string) => qa(`[id="node-${id}"] .rm`).map((m) => [m.className.replace("rm ", ""), m.textContent]);
const chips = () => qa(".elrules li").map((li) => [li.querySelector(".elrules-title")?.textContent, [...li.querySelectorAll(".rm-chip")].map((c) => c.textContent)]);

describe("review decisions in Document Review", () => {
  it("shows each rule's persisted state on the element it cites, without merging conflicting decisions", async () => {
    install({ "regel-a": { state: "accepted" }, "regel-b": { state: "rejected", edited: true }, "regel-c": { state: "pending" } });
    await mount(<ResultView result={result()} pdfUrl="blob:pdf" initialSelectedId={ABS1} onReset={() => {}} />);
    expect(marksOf(ABS1)).toEqual([["accepted", "1"], ["rejected", "1"], ["edited", ""]]); // two rules on one element: both states stay visible
    expect(marksOf(ABS2)).toEqual([["pending", "1"]]);
    expect(marksOf("doc/par-1").map((m) => m[0])).toEqual(["accepted below", "pending below", "rejected below", "edited below"]); // rolled up, fainter
    expect(chips()).toEqual([["Regel A", ["Accepted"]], ["Regel B", ["Rejected", "Edited"]]]);
    expect(pdf.last?.groups).toBeUndefined(); // two rules: the plain highlight, no single state is painted over the other
  });

  it("an edited and accepted rule is shown as accepted, with Edited as an additional mark", async () => {
    install({ "regel-a": { state: "accepted", edited: true } });
    await mount(<ResultView result={result()} pdfUrl="blob:pdf" initialSelectedId={ABS2} onReset={() => {}} />);
    expect(marksOf(ABS1).map((m) => m[0])).toEqual(["accepted", "pending", "edited"]);
    expect(chips()).toEqual([["Regel C", ["Needs review"]]]);
  });

  it("colours the PDF highlight by meaning and outlines it by state when one rule cites the element", async () => {
    install({ "regel-c": { state: "accepted", edited: true } });
    await mount(<ResultView result={result()} pdfUrl="blob:pdf" initialSelectedId={ABS2} onReset={() => {}} />);
    expect(pdf.last?.groups).toEqual([expect.objectContaining({ tone: "obligation", status: "accepted", edited: true })]);
  });

  it("loads the saved decisions each time the document is opened", async () => {
    install({ "regel-c": { state: "rejected" } });
    await mount(<ResultView result={result()} pdfUrl="blob:pdf" initialSelectedId={ABS2} onReset={() => {}} />);
    expect(calls.filter((c) => c.endsWith("/rule-reviews"))).toHaveLength(1);
    expect(marksOf(ABS2)).toEqual([["rejected", "1"]]);
  });

  it("shows no state at all without review storage, and never invents a status", async () => {
    install({}, false);
    await mount(<ResultView result={result()} pdfUrl="blob:pdf" initialSelectedId={ABS1} onReset={() => {}} />);
    expect(qa(".rm, .rm-chip, .elrules")).toHaveLength(0);
  });

  it("does not ask the backend for decisions when the document has no rules", async () => {
    install();
    await mount(<ResultView result={{ ...demoResult(null), model: doc }} pdfUrl="blob:pdf" onReset={() => {}} />);
    expect(calls).toEqual([]);
  });

  it("leads from a cited element to its rules: Open rule hands over that rule", async () => {
    install({ "regel-a": { state: "accepted" } });
    const onOpenRule = vi.fn();
    await mount(<ResultView result={result()} pdfUrl="blob:pdf" initialSelectedId={ABS1} onReset={() => {}} onOpenRule={onOpenRule} />);
    await click(q('button[aria-label="Open rule regel-b in Rule Validation"]'));
    expect(onOpenRule).toHaveBeenCalledWith("regel-b");
  });
});

describe("Rule Validation opened for a rule", () => {
  it("selects exactly that rule, whatever filters were saved, and stays there after a decision", async () => {
    install({ "regel-a": { state: "accepted" } });
    const nav = { current: { jobId: "j1", filter: "all", search: "", selectedId: "regel-c", category: "all", pageScroll: 0 } as RulesNav | null };
    await mount(<RuleExtractionView result={result()} pdfUrl="blob:pdf" onBack={() => {}} nav={nav} />);
    expect(q(".rv-id")?.textContent).toBe("regel-c");
    expect(q(".rv-title-row .rex-state")?.textContent).toBe("Pending");
    expect(pdf.last?.groups?.[0]).toMatchObject({ tone: "obligation", status: "pending" });
  });

  it("marks a cited sentence that is only part of its element as element-level in the highlight legend", async () => {
    install();
    const nav = { current: { jobId: "j1", filter: "all", search: "", selectedId: "regel-b", category: "all", pageScroll: 0 } as RulesNav | null };
    await mount(<RuleExtractionView result={result()} pdfUrl="blob:pdf" onBack={() => {}} nav={nav} />);
    expect(q(".rv-legend-precision")?.textContent).toContain("not sentence-precise");
    expect(q(".rv-legend-precision")?.textContent).toContain("Satz 1");
    expect(q(".rv-goto")?.getAttribute("title")).toContain("not sentence-precise");
    expect(q(".rv-legend-status")).toBeNull(); // pending is the normal state: no status outline in the PDF
  });
});
