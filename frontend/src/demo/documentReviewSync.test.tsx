// @vitest-environment jsdom
// Document Review shows the persisted review decisions of the rules on the elements they cite, and leads from a cited element to
// its rules. The backend is faked; with no review storage nothing is shown and nothing is invented.
import { act, useState } from "react";
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
let failPost = false;
const install = (over: Record<string, Partial<RuleReviewEntry>> = {}, enabled = true) => {
  reviews = Object.fromEntries(["regel-a", "regel-b", "regel-c"].map((id) => [id, entry(over[id] ?? {})]));
  calls = [];
  failPost = false;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push(`${init?.method ?? "GET"} ${url}`);
    if (url.endsWith("/rule-extraction")) return json({ status: "completed", scope: "document", requestedAt: "2026-11-20T10:00:00+00:00" });
    if (url.endsWith("/files/rules.json")) return json(FILE);
    if (url.endsWith("/rule-reviews") && init?.method === "POST") {
      if (failPost) return json({ detail: "boom" }, 500);
      const b = JSON.parse(String(init.body)) as { ruleId: string; action: string; reviewer: string; reason?: string };
      const cur = reviews![b.ruleId];
      reviews![b.ruleId] = { ...cur, state: b.action === "accept" ? "accepted" : b.action === "reject" ? "rejected" : "pending", edited: b.action === "reset" ? false : cur.edited,
        lastEventId: cur.lastEventId + 1, reviewer: b.reviewer, reason: b.reason ?? null, at: "2026-11-21T10:00:00+00:00" };
      return json(reviews![b.ruleId], 201);
    }
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
    expect(chips()).toEqual([["Regel C", ["Pending"]]]);
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

  it("colours each rule by its state (accepted, rejected, pending), with the state word and a legend", async () => {
    install({ "regel-a": { state: "accepted" }, "regel-b": { state: "rejected" } });
    await mount(<ResultView result={result()} pdfUrl="blob:pdf" initialSelectedId={ABS1} onReset={() => {}} />);
    expect(qa(".elrules li").map((li) => li.dataset.state)).toEqual(["accepted", "rejected"]);
    expect(qa(".marks-legend li.st").map((li) => li.textContent)).toEqual(["Accepted", "Pending", "Rejected"]);
    expect(qa(".marks-legend li.scope").map((li) => li.textContent)).toEqual(["This element", "Sub-elements"]);
    expect(qa(".marks-legend .rm-dot").map((d) => d.className)).toEqual(["rm-dot accepted", "rm-dot pending", "rm-dot rejected"]);
    await click(q(`[id="node-${ABS2}"]`));
    expect(qa(".elrules li").map((li) => [li.dataset.state, li.querySelector(".rm-chip")?.textContent])).toEqual([["pending", "Pending"]]); // default state
  });

  it("labels the tree chips for assistive technology, with an icon, and keeps own and sub-element counts apart", async () => {
    install({ "regel-a": { state: "accepted" }, "regel-b": { state: "rejected" } });
    await mount(<ResultView result={result()} pdfUrl="blob:pdf" initialSelectedId={ABS1} onReset={() => {}} />);
    const own = qa(`[id="node-${ABS1}"] .rm`);
    expect(own.map((c) => c.getAttribute("aria-label"))).toEqual(["1 rule accepted", "1 rule rejected"]);
    expect(own.every((c) => c.querySelector("svg") && !c.classList.contains("below"))).toBe(true);
    const parent = qa('[id="node-doc/par-1"] .rm');
    expect(parent.length).toBeGreaterThan(0);
    expect(parent.every((c) => c.classList.contains("below") && /in sub-elements$/.test(c.getAttribute("aria-label")!))).toBe(true);
  });

  it("presents the selected element as original source text with technical details apart, and the rules as extracted rules", async () => {
    install({ "regel-c": { state: "pending" } });
    await mount(<ResultView result={result()} pdfUrl="blob:pdf" initialSelectedId={ABS2} onReset={() => {}} onOpenRule={() => {}} />);
    expect(q(".detail-label")?.textContent).toBe("Original source text");
    expect(q(".detail details.srctext")?.hasAttribute("open")).toBe(false); // collapsed: the text is already highlighted in the PDF
    expect(q(".detail details.srctext")?.textContent).toContain("Highlighted in the PDF");
    expect(q(".detail details.srctext .origtext")?.textContent).toBeTruthy(); // never removed, only folded
    expect(q(".detail h3")?.textContent).toMatch(/\(\d+\)|Absatz|Paragraph/);
    expect(q(".detail details.techref")?.hasAttribute("open")).toBe(false);
    expect(q(".detail details.techref")?.textContent).toContain(ABS2);
    expect(q(".elrules h4")?.textContent).toBe("Extracted rules");
    expect(q(".elrules-hint")?.textContent).toContain("AI-extracted");
    expect(q(".elrule-no")?.textContent).toMatch(/^Rule 01/);
    expect(q(".elrule-open")?.textContent).toContain("View full rule details");
  });

  it("shows no legend without review storage", async () => {
    install({}, false);
    await mount(<ResultView result={result()} pdfUrl="blob:pdf" initialSelectedId={ABS1} onReset={() => {}} />);
    expect(qa(".marks-legend")).toHaveLength(0);
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

// Accept / Reject directly on the rules of the selected element (Legal structure panel), through the same review state as Rule Validation.
describe("rules that are not valid Rule JSON in the legal structure", () => {
  const BAD = { valid: false, issues: ["classification/type: 'informational' is not one of ['definition', 'obligation']"] };
  const rowBtn = (verb: string) => q<HTMLButtonElement>(`button[aria-label^="${verb} rule regel-c"]`)!;
  it("flags the rule on its card, in the tree and in the legend, and does not offer Accept", async () => {
    install({ "regel-c": { validity: BAD } });
    window.localStorage.setItem("odos.reviewer", "Dana");
    await mount(<ResultView result={result()} pdfUrl="blob:pdf" initialSelectedId={ABS2} onReset={() => {}} />);
    expect(q(".elrule .rm-chip.invalid")?.textContent).toBe("Invalid Rule JSON");
    expect(q(".elrule-invalid")?.textContent).toContain("classification/type");
    expect(rowBtn("Accept").disabled).toBe(true);
    expect(rowBtn("Accept").title).toContain("not valid Rule JSON 2.0");
    expect(rowBtn("Reject").disabled).toBe(false);
    await click(rowBtn("Accept"));
    expect(calls.filter((c) => c.startsWith("POST"))).toHaveLength(0);
    expect(qa(`[id="node-${ABS2}"] .rm.invalid`).map((c) => c.getAttribute("aria-label"))).toEqual(["1 not valid Rule JSON"]);
    expect(q(".marks-legend .invalidkey")?.textContent).toBe("Invalid Rule JSON");
  });
  it("shows an old acceptance of an invalid rule as accepted and invalid, without changing the decision", async () => {
    install({ "regel-c": { state: "accepted", validity: BAD } });
    await mount(<ResultView result={result()} pdfUrl="blob:pdf" initialSelectedId={ABS2} onReset={() => {}} />);
    expect(q(".elrule")?.dataset.state).toBe("accepted");
    expect(qa(".elrule .rm-chip").map((c) => c.textContent)).toEqual(["Accepted", "Invalid Rule JSON"]);
  });
  it("shows no validity marks when every rule is valid", async () => {
    install();
    await mount(<ResultView result={result()} pdfUrl="blob:pdf" initialSelectedId={ABS2} onReset={() => {}} />);
    expect(qa(".rm.invalid, .rm-chip.invalid, .invalidkey, .elrule-invalid")).toHaveLength(0);
  });
});

describe("deciding in the legal structure panel", () => {
  const setName = (name = "Dana") => window.localStorage.setItem("odos.reviewer", name);
  const rowBtn = (ruleId: string, verb: "Accept" | "Reject") => q<HTMLButtonElement>(`button[aria-label="${verb} rule ${ruleId}"]`)!;
  const states = () => qa(".elrules li").map((li) => li.dataset.state);
  const posts = () => calls.filter((c) => c.startsWith("POST"));
  const reject = async (id: string, reason: string, opened = false) => {
    if (!opened) await click(rowBtn(id, "Reject"));
    await act(async () => { const t = q<HTMLTextAreaElement>(".elrule-reject textarea")!; Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(t, reason); t.dispatchEvent(new Event("input", { bubbles: true })); });
    await click([...document.querySelectorAll<HTMLButtonElement>(".elrule-reject button")].find((b) => b.textContent === "Reject rule"));
  };
  const show = (id = ABS2) => mount(<ResultView result={result()} pdfUrl="blob:pdf" initialSelectedId={id} onReset={() => {}} />);

  it("offers both buttons on every rule, pending by default, and disables the current state's button", async () => {
    install({ "regel-a": { state: "accepted" }, "regel-b": { state: "rejected" } }); setName();
    await show(ABS1);
    expect(states()).toEqual(["accepted", "rejected"]);
    expect([rowBtn("regel-a", "Accept").disabled, rowBtn("regel-a", "Reject").disabled]).toEqual([true, false]);
    expect([rowBtn("regel-b", "Accept").disabled, rowBtn("regel-b", "Reject").disabled]).toEqual([false, true]);
  });

  it("accepts a pending rule: state, colour, tree counter and PDF outline change at once, and one event is sent", async () => {
    install(); setName();
    await show();
    expect(states()).toEqual(["pending"]);
    await click(rowBtn("regel-c", "Accept"));
    expect(states()).toEqual(["accepted"]);
    expect(marksOf(ABS2)).toEqual([["accepted", "1"]]);
    expect(pdf.last?.groups).toEqual([expect.objectContaining({ status: "accepted" })]);
    expect(posts()).toHaveLength(1);
    expect(reviews!["regel-c"]).toMatchObject({ state: "accepted", reviewer: "Dana" });
  });

  it("rejects only with a reason, then shows red", async () => {
    install(); setName();
    await show();
    await click(rowBtn("regel-c", "Reject"));
    expect([...document.querySelectorAll<HTMLButtonElement>(".elrule-reject button")].find((b) => b.textContent === "Reject rule")!.disabled).toBe(true);
    expect(posts()).toHaveLength(0);
    await reject("regel-c", "Wrong threshold", true);
    expect(states()).toEqual(["rejected"]);
    expect(marksOf(ABS2)).toEqual([["rejected", "1"]]);
    expect(reviews!["regel-c"]).toMatchObject({ state: "rejected", reason: "Wrong threshold" });
  });

  it("changes a decision later in both directions", async () => {
    install({ "regel-c": { state: "accepted" } }); setName();
    await show();
    await reject("regel-c", "On second thought");
    expect(states()).toEqual(["rejected"]);
    await click(rowBtn("regel-c", "Accept"));
    expect(states()).toEqual(["accepted"]);
    expect(posts()).toHaveLength(2);
  });

  it("needs a reviewer name and sends nothing without one", async () => {
    install();
    await show();
    await click(rowBtn("regel-c", "Accept"));
    expect(posts()).toHaveLength(0);
    expect(q(".elrule-error")?.textContent).toContain("Enter your name");
    expect(states()).toEqual(["pending"]);
  });

  it("a failed request keeps the old state and shows the error", async () => {
    install(); setName();
    await show();
    failPost = true;
    await click(rowBtn("regel-c", "Accept"));
    expect(states()).toEqual(["pending"]);
    expect(marksOf(ABS2)).toEqual([["pending", "1"]]);
    expect(q(".elrule-error")?.textContent).toContain("boom");
    expect(rowBtn("regel-c", "Accept").disabled).toBe(false); // can be retried
  });

  it("shows no controls while the review state is unavailable", async () => {
    install({}, false); setName();
    await show();
    expect(qa(".elrule-actions")).toHaveLength(0);
  });
});

// The colours follow the stored decision when the reviewer moves between Rule Validation and the legal structure, without a page reload.
describe("review decisions made in Rule Validation show in the legal structure panel", () => {
  const NAV = () => ({ current: { jobId: "j1", filter: "all", search: "", selectedId: "regel-c", category: "all", pageScroll: 0 } as RulesNav | null });
  function Flow() {
    const [view, setView] = useState<"doc" | "rules">("doc");
    return view === "doc"
      ? <ResultView result={result()} pdfUrl="blob:pdf" initialSelectedId={ABS2} onReset={() => {}} onOpenRule={() => setView("rules")} onContinueToRules={() => setView("rules")} />
      : <RuleExtractionView result={result()} pdfUrl="blob:pdf" onBack={() => setView("doc")} nav={NAV()} />;
  }
  const btn = (re: RegExp) => qa<HTMLButtonElement>("button").find((b) => re.test((b.textContent ?? "").trim()));
  const states = () => qa(".elrules li").map((li) => li.dataset.state);
  const fill = async (el: HTMLInputElement | HTMLTextAreaElement, v: string) => {
    await act(async () => { Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), "value")!.set!.call(el, v); el.dispatchEvent(new Event("input", { bubbles: true })); });
  };
  const choice = (name: string) => qa<HTMLButtonElement>(".rex-choice").find((b) => b.querySelector(".rex-choice-main")?.textContent === name)!;

  it("starts pending, turns accepted after Accept", async () => {
    install();
    await mount(<Flow />);
    expect(states()).toEqual(["pending"]);
    await click(btn(/Continue to Rule Extraction/));
    await fill(q<HTMLInputElement>('input[aria-label^="Reviewing as"]')!, "Dana");
    await click(choice("Accept"));
    await click(btn(/Back to (Document|documents)/));
    await click(q(`[id="node-${ABS2}"]`));
    expect(states()).toEqual(["accepted"]);
    expect(marksOf(ABS2)).toEqual([["accepted", "1"]]);
  });

  it("turns rejected after Reject with a reason", async () => {
    install();
    await mount(<Flow />);
    await click(btn(/Continue to Rule Extraction/));
    await fill(q<HTMLInputElement>('input[aria-label^="Reviewing as"]')!, "Dana");
    await click(choice("Reject"));
    await fill(q<HTMLTextAreaElement>(".rex-form textarea")!, "Wrong");
    await click(btn(/^Reject rule$/));
    await click(btn(/Back to (Document|documents)/));
    await click(q(`[id="node-${ABS2}"]`));
    expect(states()).toEqual(["rejected"]);
  });

  it("Reset edit returns an edited, accepted rule to pending", async () => {
    install({ "regel-c": { state: "accepted", edited: true } });
    await mount(<Flow />);
    expect(states()).toEqual(["accepted"]);
    await click(btn(/Continue to Rule Extraction/));
    await fill(q<HTMLInputElement>('input[aria-label^="Reviewing as"]')!, "Dana");
    await click(btn(/^Reset edit$/));
    await click(btn(/Back to (Document|documents)/));
    await click(q(`[id="node-${ABS2}"]`));
    expect(states()).toEqual(["pending"]);
    expect(qa(".elrules .rm-chip.edited")).toHaveLength(0);
  });

  it("a failed request leaves the stored state, so no wrong colour is shown", async () => {
    install();
    await mount(<Flow />);
    await click(btn(/Continue to Rule Extraction/));
    await fill(q<HTMLInputElement>('input[aria-label^="Reviewing as"]')!, "Dana");
    failPost = true;
    await click(choice("Accept"));
    await click(btn(/Back to (Document|documents)/));
    await click(q(`[id="node-${ABS2}"]`));
    expect(states()).toEqual(["pending"]);
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
