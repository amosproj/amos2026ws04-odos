// @vitest-environment jsdom
// The three-panel Rule Validation page: the centre adapts to what each Rule JSON 2.0 record holds (and shows nothing it does not
// hold), the left panel filters by the records' own types and structure, and the right panel keeps one PDF viewer for all rules
// and shows the selected record as stored. The backend is faked; nothing here is an extraction result.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { RuleReviewEntry } from "./live";
import { RuleExtractionView, type RulesNav } from "./RuleExtraction";
import { ruleFacets, typeCounts, toRuleItem } from "./ruleResults";
import { ABS1, ABS2, demoResult, generation, rulesFile, status } from "./ruleTestData";

// one PdfViewer for the whole page: every mount and the props it was last given are recorded
const pdf = vi.hoisted(() => ({ mounts: 0, last: null as null | { url: string; page: number; groups?: Array<{ boxes: unknown[]; tone?: string; status?: string; edited?: boolean; approximate?: boolean }> } }));
vi.mock("../components/PdfViewer", async () => {
  const { useEffect } = await import("react");
  return {
    PdfViewer: (props: { url: string; page: number; groups?: Array<{ boxes: unknown[]; tone?: string; status?: string; edited?: boolean; approximate?: boolean }> }) => {
      useEffect(() => { pdf.mounts += 1; }, []);
      pdf.last = props;
      return <div className="pdf-stub" data-page={props.page} />;
    },
  };
});
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

// ── fixtures: Rule JSON 2.0 records of different shapes (test-only) ───────────────────────────────────────────────────
const base = (id: string, type: string, summary: string, elementId: string, page: number, extra: Record<string, unknown>) => ({
  schemaVersion: "2.0", id,
  source: { documentId: "beispielgesetz", documentTitle: "Beispielgesetz", language: "de", citation: `§ 1 ${id}`, elements: [{ elementId, role: "primary", pdfPages: [page] }] },
  classification: { type, normativeCategory: "substantive", summary },
  review: { status: "draft" },
  ...extra,
});
/** A definition: a term and its text, nothing else. */
const DEFINITION_TEXT = "Ein Raum, der zum nicht nur vorübergehenden Aufenthalt von Personen bestimmt ist.";
const DEF = base("aufenthaltsraum", "definition", "Begriff Aufenthaltsraum.", ABS1, 3, {
  definition: { term: "Aufenthaltsraum", text: DEFINITION_TEXT },
});
/** A minimal obligation: one yes/no requirement; no applicability, no exceptions, no numbers. */
const SIMPLE = base("brandabschnitt", "obligation", "Brandabschnitte sind zu begrenzen.", ABS2, 4, {
  requirements: [{ kind: "boolean", fact: "brandabschnitt_begrenzt", value: true }],
});
/** A long, complex rule: conditions, two numeric requirements (one without a unit) and two exceptions. */
const COMPLEX = base("raumhoehe", "obligation", "Aufenthaltsräume müssen eine lichte Höhe von mindestens 2,40 m haben.", ABS1, 3, {
  applicability: {
    targets: [{ entity: "Aufenthaltsraum" }],
    conditions: { kind: "all", conditions: [
      { kind: "comparison", fact: "gebaeude.geschosse", operator: ">", value: 2, valueType: "integer" },
      { kind: "comparison", fact: "raum.dauerhaft_genutzt", operator: "==", value: true, valueType: "boolean" },
    ] },
  },
  requirements: [
    { kind: "numeric", fact: "room_height", operator: ">=", value: 2.4, unit: "m" },
    { kind: "numeric", fact: "anzahl_fenster", operator: ">=", value: 1 },
  ],
  exceptions: [
    { kind: "exception", effect: "modifies_rule", description: "Geringere Höhe bei höchstens zwei Geschossen.",
      condition: { kind: "comparison", fact: "gebaeude.geschosse", operator: "<=", value: 2, valueType: "integer" },
      requirements: [{ kind: "numeric", fact: "room_height", operator: ">=", value: 2.3, unit: "m" }] },
    { kind: "exemption", effect: "disapplies_rule", description: "Gilt nicht für Dachgeschosse." },
  ],
});
/** Formula rules: one the reader can state, one with an expression the schema does not define. */
const FORMULA = base("abstandsflaeche", "obligation", "Tiefe der Abstandsfläche.", ABS2, 4, {
  requirements: [{ kind: "formula", fact: "setback_area_depth", operator: "==", unit: "m", description: "0,4 H, mindestens 3 m",
    expression: { kind: "operation", operator: "max", operands: [
      { kind: "operation", operator: "multiply", operands: [{ kind: "literal", value: 0.4 }, { kind: "fact", name: "measure_h", unit: "m" }] },
      { kind: "literal", value: 3, unit: "m" }] } }],
  exceptions: [{ kind: "alternative", effect: "adds_alternative", description: "In Gewerbegebieten genügt weniger.",
    requirements: [{ kind: "numeric", fact: "setback_area_depth", operator: ">=", value: 1.5, unit: "m" }] }],
});
const UNSTATABLE = base("unlesbar", "obligation", "Formel mit unbekannter Operation.", ABS1, 3, {
  requirements: [{ kind: "formula", fact: "x", operator: "==", unit: "m",
    expression: { kind: "operation", operator: "power", operands: [{ kind: "fact", name: "a" }, { kind: "literal", value: 2 }] } }],
});
/** A very large record: thousands of JSON lines and one extremely long line. */
const HUGE = base("riesig", "obligation", "Sehr große Regel.", ABS2, 4, {
  requirements: Array.from({ length: 400 }, (_, i) => ({ kind: "numeric", fact: `parameter_${i}`, operator: ">=", value: i, unit: "m" })),
  review: { status: "draft", notes: ["Z".repeat(4000)] },
});
const FILE = rulesFile([DEF, SIMPLE, COMPLEX]);
const MATH_FILE = rulesFile([FORMULA, UNSTATABLE, HUGE]);
let file: ReturnType<typeof rulesFile> = FILE; // what the fake backend serves and the page opens with
const EXTRACTION = String(generation.generatedAt);
const json = (body: unknown, code = 200) => new Response(JSON.stringify(body), { status: code, headers: { "Content-Type": "application/json" } });
const entry = (over: Partial<RuleReviewEntry> = {}): RuleReviewEntry => ({ ruleSha256: "a".repeat(64), state: "pending", edited: false, verification: "unverified", lastEventId: 0, reviewer: null, reason: null, at: null, effectiveRule: null, ...over });

let entries: Record<string, RuleReviewEntry>;
let calls: string[];
function install(over: Record<string, Partial<RuleReviewEntry>> = {}) {
  entries = Object.fromEntries((file.rules as Array<{ id: string }>).map((r) => [r.id, entry(over[r.id])]));
  calls = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push(`${init?.method ?? "GET"} ${url}`);
    if (url.endsWith("/rule-extraction")) return json(status("completed"));
    if (url.endsWith("/files/rules.json")) return json(file);
    if (url.includes("/rule-reviews/history")) return json([]);
    if (url.endsWith("/rule-reviews")) {
      const counts = { pending: 0, accepted: 0, rejected: 0, edited: 0 };
      for (const e of Object.values(entries)) { counts[e.state]++; counts.edited += e.edited ? 1 : 0; }
      return json({ extractionId: EXTRACTION, criteriaVersion: 1, counts, rules: entries, earlierExtractionEvents: 0 });
    }
    return json({ detail: "unexpected request" }, 500);
  }));
}

let host: HTMLElement;
let root: Root;
const flush = async () => { await act(async () => { await vi.advanceTimersByTimeAsync(0); }); };
const open = async (nav?: { current: RulesNav | null }, pdfUrl = "blob:odos-test-pdf") => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => { root.render(<RuleExtractionView result={demoResult(file)} pdfUrl={pdfUrl || undefined} onBack={() => {}} onShowInPdf={() => {}} nav={nav} />); });
  await flush();
  await flush();
};
const close = () => { act(() => root.unmount()); host.remove(); };
const q = <T extends Element = HTMLElement>(sel: string) => document.body.querySelector<T>(sel);
const qa = <T extends Element = HTMLElement>(sel: string, within: ParentNode = document.body) => [...within.querySelectorAll<T>(sel)];
const click = async (el: Element | null | undefined) => { if (!el) throw new Error("nothing to click"); await act(async () => { (el as HTMLElement).click(); }); await flush(); };
const key = async (target: Element, k: string) => { await act(async () => { target.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true })); }); await flush(); };
const navRow = (label: string) => qa<HTMLButtonElement>(".rv-nav-row").find((b) => b.querySelector(".rv-nav-label")?.textContent === label);
const countOf = (label: string) => Number(navRow(label)?.querySelector(".rv-count")?.textContent);
const sections = () => qa(".rv-sec .rv-sec-label").map((s) => s.textContent);
const ruleId = () => q(".rv-id")?.textContent;
const goTo = async (id: string) => { for (let i = 0; i < 5 && ruleId() !== id; i++) await click(q('button[aria-label="Next rule"]')); expect(ruleId()).toBe(id); };

beforeEach(() => { file = FILE; vi.useFakeTimers(); window.localStorage.clear(); window.scrollTo = () => {}; pdf.mounts = 0; pdf.last = null; });
afterEach(() => { close(); vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("adaptive rule rendering", () => {
  it("shows a definition as its term and its text, and nothing a definition does not have", async () => {
    install();
    await open();
    expect(ruleId()).toBe("aufenthaltsraum");
    expect(q(".rex-kind")?.textContent).toBe("Definition");
    expect(q(".rv-term")?.textContent).toBe("Aufenthaltsraum");
    expect(q(".rv-def-text")?.textContent).toBe(DEFINITION_TEXT);
    expect(sections()).toEqual(["Definition"]);
    expect(q(".rv-tiles")).toBeNull(); // no operator, value or unit is invented
  });

  it("shows only the parts a minimal record states: no empty conditions, exceptions or threshold cards", async () => {
    install();
    await open();
    await goTo("brandabschnitt");
    expect(sections()).toEqual(["Main rule"]);
    expect(q(".rex-suggest")?.textContent).toContain("brandabschnitt begrenzt: yes");
    expect(q(".rv-tiles")).toBeNull();
    expect(q(".rex-suggest")?.textContent).not.toMatch(/Conditions|Exception|Parameter|Operator|Unit/);
    expect(q(".rex-gap")).toBeNull(); // the record is completely shown
  });

  it("organises a long, complex rule into collapsible sections, with thresholds as stored and exceptions apart", async () => {
    install();
    await open();
    await goTo("raumhoehe");
    expect(sections()).toEqual(["Main rule", "Applies to", "Conditions", "Exceptions"]);
    // all / any of the record is said in words; nothing is joined by an AND or OR the record does not state
    expect(qa(".rv-sec-sub").map((s) => s.textContent)).toEqual(["Requirements (all must be met)", "Applies when all of these are true"]);
    expect(q(".rv-sec.cond")?.textContent).toContain("gebaeude geschosse is more than 2");
    expect(q(".rv-sec.cond")?.textContent).toContain("raum dauerhaft genutzt: yes");
    expect(qa(".rv-limit .rv-params dd").map((d) => d.textContent)).toEqual([
      "room_height · in m",
      "anzahl_fenster", // the record states no unit: none is shown
      "room_height · in m", // the exception's own requirement
    ]);
    const exceptions = qa(".rv-exc");
    expect(exceptions).toHaveLength(2);
    expect(exceptions[0].querySelector(".rv-exc-tag")?.textContent).toBe("Exception");
    expect(exceptions[0].textContent).toContain("Geringere Höhe bei höchstens zwei Geschossen.");
    expect(exceptions[0].textContent).toContain("gebaeude geschosse is at most 2");
    expect(exceptions[1].querySelector(".rv-exc-tag")?.textContent).toBe("Exemption");
    expect(exceptions[1].textContent).toContain("Gilt nicht für Dachgeschosse.");
    expect(exceptions[1].querySelector(".rv-tiles")).toBeNull();
    // sections fold and unfold
    const cond = q<HTMLDetailsElement>(".rv-sec.cond")!;
    expect(cond.open).toBe(true);
    await click(cond.querySelector("summary"));
    expect(cond.open).toBe(false);
  });

  it("derives the left panel's types and facets from the records only", () => {
    const items = [DEF, SIMPLE, COMPLEX].map((r) => toRuleItem(r));
    expect(typeCounts(items)).toEqual([{ type: "definition", count: 1 }, { type: "obligation", count: 2 }]);
    expect(ruleFacets(DEF)).toEqual({ exceptions: false, conditions: false, thresholds: false });
    expect(ruleFacets(SIMPLE)).toEqual({ exceptions: false, conditions: false, thresholds: false });
    expect(ruleFacets(COMPLEX)).toEqual({ exceptions: true, conditions: true, thresholds: true });
  });
});

describe("left panel: rule navigation", () => {
  it("offers the types and facets that occur, with counts, and filters Previous / Next by them", async () => {
    install();
    await open();
    expect(q(".rv-side-head")?.textContent).toContain("Rules (3)");
    expect(qa(".rv-nav-row .rv-nav-label").slice(0, 6).map((l) => l.textContent)).toEqual(["All rules", "Definitions", "Obligations", "With conditions", "With exceptions", "Limits / thresholds"]);
    expect(navRow("Prohibitions")).toBeUndefined(); // a type with no rule is not offered
    expect(countOf("Obligations")).toBe(2);
    await click(navRow("With exceptions"));
    expect(q(".rex-pager-pos")?.textContent).toBe("Rule 1 of 1 · exceptions");
    expect(ruleId()).toBe("raumhoehe");
    expect(countOf("Pending")).toBe(1); // status counts follow the chosen category
    await click(navRow("All rules"));
    expect(q(".rex-pager-pos")?.textContent).toBe("Rule 3 of 3");
  });

  it("keeps an accepted rule accepted when it was edited: Edited is an attribute, not a state", async () => {
    install({ brandabschnitt: { state: "accepted", edited: true, reviewer: "Alex", at: "2026-11-21T10:00:00+00:00", lastEventId: 2,
      effectiveRule: { ...SIMPLE, requirements: [{ kind: "boolean", fact: "brandabschnitt_begrenzt", value: false }] } } });
    await open();
    expect(countOf("Accepted")).toBe(1);
    expect(countOf("Edited")).toBe(1);
    expect(countOf("Pending")).toBe(2);
    await click(navRow("Edited"));
    expect(ruleId()).toBe("brandabschnitt");
    expect(q(".rv-title-row .rex-state")?.textContent).toBe("Accepted");
    expect(q(".rv-title-row .rex-tag.edited")?.textContent).toBe("Edited");
    expect(q(".rex-decided")?.textContent).toContain("Accepted by Alex");
    expect(q(".rex-decided")?.textContent).toContain("edited");
    expect(q(".rex-suggest")?.textContent).toContain("brandabschnitt begrenzt: no"); // the edited record is the one in force
  });
});

describe("right panel: document context", () => {
  it("keeps one PDF viewer for all rules and moves it to the selected rule's source page and passage", async () => {
    install();
    await open();
    expect(pdf.mounts).toBe(1);
    expect(pdf.last?.url).toBe("blob:odos-test-pdf");
    expect(pdf.last?.page).toBe(3);
    expect(pdf.last?.groups).toHaveLength(1); // the cited element's geometry, with the tone of the rule's classification
    expect(pdf.last?.groups?.[0]).toMatchObject({ tone: "definition", status: "pending" });
    expect(q(".rv-legend-precision")?.textContent).toContain("exactly the cited text");
    await goTo("brandabschnitt");
    expect(pdf.last?.page).toBe(4);
    expect(q(".rv-legend-precision")?.textContent).toContain("exactly the cited text");
    await click(q("#rv-tab-json"));
    await click(q("#rv-tab-pdf"));
    expect(pdf.mounts).toBe(1); // neither another rule nor the other tab loads the PDF again
  });

  it("Go to source brings the PDF tab and the rule's page back", async () => {
    install();
    await open();
    await click(q("#rv-tab-json"));
    expect(q("#rv-panel-pdf")?.className).toContain("rv-panel-off");
    await click(q(".rv-goto"));
    expect(q("#rv-tab-pdf")?.getAttribute("aria-selected")).toBe("true");
    expect(q("#rv-panel-pdf")?.className).not.toContain("rv-panel-off");
    expect(pdf.last?.page).toBe(3);
  });

  it("shows the selected record exactly as stored in the Rule JSON tab, and the tabs work with the keyboard", async () => {
    install();
    await open();
    expect(q(".jsonv-code")).toBeNull();
    const tablist = q('[role="tablist"]')!;
    q<HTMLButtonElement>("#rv-tab-pdf")!.focus();
    await key(tablist, "ArrowRight");
    expect(q("#rv-tab-json")?.getAttribute("aria-selected")).toBe("true");
    expect(ruleId()).toBe("aufenthaltsraum"); // the arrow key switched the tab, not the rule
    expect(JSON.parse(q(".jsonv-code")!.textContent!)).toEqual(DEF);
    await goTo("raumhoehe");
    expect(JSON.parse(q(".jsonv-code")!.textContent!)).toEqual(COMPLEX);
    await key(tablist, "ArrowLeft");
    expect(q("#rv-tab-pdf")?.getAttribute("aria-selected")).toBe("true");
  });

  it("says so when the PDF is not available, instead of showing an empty viewer", async () => {
    install();
    await open(undefined, "");
    expect(pdf.mounts).toBe(0);
    expect(q("#rv-panel-pdf")?.textContent).toContain("The original PDF is not available");
  });
});

describe("state preservation", () => {
  it("restores the category and the open tab when the page is opened again", async () => {
    install();
    const nav = { current: null as RulesNav | null };
    await open(nav);
    await click(navRow("Definitions"));
    await click(q("#rv-tab-json"));
    expect(nav.current).toMatchObject({ category: "type:definition", tab: "json", selectedId: "aufenthaltsraum" });
    close();
    await open(nav);
    expect(navRow("Definitions")?.getAttribute("aria-pressed")).toBe("true");
    expect(q("#rv-tab-json")?.getAttribute("aria-selected")).toBe("true");
    expect(ruleId()).toBe("aufenthaltsraum");
    expect(calls.filter((c) => c.startsWith("POST"))).toEqual([]);
  });
});

describe("simplified rule view", () => {
  it("has no original wording and no history or details panel; the main rule comes first", async () => {
    install();
    await open();
    await goTo("raumhoehe");
    expect(q(".rv-origtext, .rex-quote, .rex-advanced, .rex-adv-toggle, .rex-audit")).toBeNull();
    const first = q(".rex-card")!.firstElementChild!;
    expect(first.className).toContain("rex-suggest");
    expect([...first.children].find((c) => c.tagName !== "H3")?.className).toContain("rv-sec");
    expect(q(".rex-summary-text")).toBeNull(); // the structured rule states the rule; the model's summary is not repeated
  });

  it("shows the model's summary only where the structured rule cannot state the rule alone", async () => {
    file = MATH_FILE; install();
    await open();
    await goTo("unlesbar"); // a part cannot be put into words
    expect(q(".rv-summary-line")?.textContent).toContain(UNSTATABLE.classification.summary);
  });

  it("keeps the source navigation and names the cited passage", async () => {
    install();
    await open();
    expect(q(".rv-goto")?.getAttribute("aria-label")).toBe("Go to source");
    expect(q(".rex-view-btn")?.getAttribute("aria-label")).toBe("View in document");
    expect(q(".rv-center-head .rex-cite")?.textContent).toBe("§ 1 aufenthaltsraum");
    expect(q(".rv-goto")?.getAttribute("title")).toContain("Absatz (1)");
    expect(q(".rex-source")).toBeNull(); // no separate Source card
  });
});

describe("mathematical presentation", () => {
  it("writes a formula rule as a formula card with its parameters, and keeps the plain-language line", async () => {
    file = MATH_FILE; install();
    await open();
    expect(ruleId()).toBe("abstandsflaeche");
    const card = q(".rv-sec.main .rv-formula")!;
    expect(card.querySelector(".rv-eq")?.textContent).toBe("setback area depth=max(0.4 × h, 3\u00a0m)[m]");
    expect(card.querySelector(".rv-m-fact.sym")?.getAttribute("title")).toBe("measure_h"); // a short symbol only where the identifier ends in one; the exact id stays
    expect(card.querySelector(".rv-m-rel")?.textContent).toBe("="); // == on a formula states a calculated value
    expect([...card.querySelectorAll(".rv-params > div")].map((d) => d.textContent)).toEqual(["setback area depthsetback_area_depth · in m · determined by this formula", "hmeasure_h · in m"]);
    expect(q(".rv-sec.main")?.textContent).toContain("setback area depth equals the larger of 0.4 × measure h and 3 m (in m)");
    expect(card.getAttribute("aria-label")).toContain("setback_area_depth equals max(0.4 × measure_h, 3\u00a0m)");
  });

  it("keeps the exception's own limit apart from the primary formula and names the kind of exception", async () => {
    file = MATH_FILE; install();
    await open();
    const exc = q(".rv-sec.exc")!;
    expect(exc.querySelector(".rv-exc-tag")?.textContent).toBe("Alternative");
    expect(exc.querySelector(".rv-limit .rv-eq")?.textContent).toBe("setback area depth≥1.5\u00a0m");
    expect(exc.querySelector(".rv-formula")).toBeNull();
    expect(q(".rv-sec.main .rv-limit")).toBeNull(); // the exception's bound is not shown as the main rule's
  });

  it("shows a bound with its stored operator symbol, and no unit tile when the record has no unit", async () => {
    install();
    await open();
    await goTo("raumhoehe");
    const bounds = qa(".rv-limit .rv-eq").map((e) => e.textContent);
    expect(bounds).toEqual(["room height≥2.4\u00a0m", "anzahl fenster≥1", "room height≥2.3\u00a0m"]);
  });

  it("falls back to the text line when the expression cannot be stated, and says nothing mathematical", async () => {
    file = MATH_FILE; install();
    await open();
    await goTo("unlesbar");
    expect(q(".rv-formula")).toBeNull();
    expect(q(".rv-eq")).toBeNull();
    expect(q(".rv-sec.main")?.textContent).toContain("x equals"); // the accurate text representation
    expect(q(".rex-gap")?.textContent).toContain("cannot be shown in plain language"); // and the page says the reading is incomplete
  });

  it("shows no formula or limit for a rule that has no numbers", async () => {
    install();
    await open();
    await goTo("brandabschnitt");
    expect(q(".rv-eq")).toBeNull();
    expect(q(".rv-formula, .rv-limit")).toBeNull();
  });

  it("colours by meaning: definitions purple, main rule teal, conditions and exceptions amber", async () => {
    install();
    await open();
    expect(q(".rv-sec.def")).not.toBeNull();
    expect(q(".rex-kind.def")?.textContent).toBe("Definition");
    await goTo("raumhoehe");
    expect(qa(".rv-sec").map((s) => s.className.replace(/\s*rv-sec\s*/, "").trim())).toEqual(["main", "plain", "cond", "exc"]);
  });
});

describe("Rule JSON tab with large records", () => {
  it("renders every line of a very large record, including the last, in its own scroll area", async () => {
    file = MATH_FILE; install();
    await open();
    await goTo("riesig");
    await click(q("#rv-tab-json"));
    const code = q(".jsonv-code")!.textContent!;
    expect(JSON.parse(code)).toEqual(HUGE);
    expect(code.trimEnd().endsWith("}")).toBe(true);
    expect(q(".jsonv-gutter")!.textContent!.trim().split("\n").length).toBe(code.split("\n").length);
    expect(q(".rv-json .jsonv-scroll")).not.toBeNull(); // the scroll area is inside the JSON tab, which is not itself scrolled
    expect(q(".jsonv-bar")?.textContent).toContain("Copy");
  });

  it("is laid out so the viewer owns the scrolling: every flex link down to the scroll area may shrink and none is height-capped", () => {
    const css = readFileSync(resolve(process.cwd(), "src/demo/rule-extraction.css"), "utf8");
    const rule = (selector: string) => css.split("\n").filter((l) => l.startsWith(`${selector} {`)).join(" ");
    for (const sel of [".rv-json-body", ".rv-json .jsonv", ".rv-json .jsonv-scroll"]) expect(rule(sel), sel).toContain("min-height: 0");
    expect(rule(".rv-json .jsonv-scroll")).toContain("max-height: none");
    expect(rule(".rv-json .jsonv-scroll")).toContain("flex: 1 1 auto");
    expect(rule(".jsonv-scroll")).toContain("overflow: auto"); // scrolls vertically and, for very long lines, horizontally
    expect(rule(".jsonv-code")).toContain("white-space: pre"); // a long line scrolls sideways instead of widening the panel
    expect(rule(".rv-json")).toContain("overflow: hidden"); // the panel does not scroll as a whole
  });

  it("keeps the edited / extracted toggle above the viewer", async () => {
    install({ brandabschnitt: { state: "pending", edited: true, lastEventId: 1, effectiveRule: { ...SIMPLE, requirements: [{ kind: "boolean", fact: "brandabschnitt_begrenzt", value: false }] } } });
    await open();
    await goTo("brandabschnitt");
    await click(q("#rv-tab-json"));
    const toggle = q(".rv-json .rex-jsonview")!;
    expect(toggle.compareDocumentPosition(q(".rv-json .jsonv")!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(JSON.parse(q(".jsonv-code")!.textContent!).requirements[0].value).toBe(false);
    await click(qa("button", toggle).find((b) => b.textContent === "Extracted (original)"));
    expect(JSON.parse(q(".jsonv-code")!.textContent!).requirements[0].value).toBe(true);
  });
});
