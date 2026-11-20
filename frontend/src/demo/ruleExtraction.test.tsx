// @vitest-environment jsdom
// The Rule Extraction page against a faked backend (global fetch): what it shows before an extraction, while one runs, when
// it fails or takes too long, and how it presents the stored Rule JSON, with human review unavailable. The fixtures come from
// ruleTestData.ts (test-only); the application itself contains no sample rules.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ResultView } from "./DemoApp";
import { RuleExtractionView } from "./RuleExtraction";
import type { RuleExtractionStatus } from "./live";
import { ABS1, ABS2, NESTED, RULE_DOOR, RULE_FIRE, STORED, demoResult, rule, rulesFile, status } from "./ruleTestData";

vi.mock("../components/PdfViewer", () => ({
  PdfViewer: (p: { url: string; page: number; highlights: unknown[] }) => <div className="pdf-stub" data-page={p.page} data-highlights={p.highlights.length} />,
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** What the faked backend currently has: the latest extraction status (null = none), the stored rules.json (null = none),
 *  and how a POST is answered. `calls` lists every request as "METHOD path". */
interface Backend {
  status: RuleExtractionStatus | null;
  rules: unknown | null;
  post: { status: number; detail?: string } | null; // null: accepted, the extraction becomes queued
  down: boolean; // the backend does not answer at all
  calls: string[];
}
let backend: Backend;
const json = (body: unknown, code = 200) => new Response(JSON.stringify(body), { status: code, headers: { "Content-Type": "application/json" } });

function installBackend(initial: Partial<Backend> = {}): Backend {
  backend = { status: null, rules: null, post: null, down: false, calls: [], ...initial };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    backend.calls.push(`${method} ${url}`);
    if (backend.down) throw new TypeError("network down");
    if (url.endsWith("/rule-extraction")) {
      if (method === "POST") {
        if (backend.post) return json({ detail: backend.post.detail }, backend.post.status);
        backend.status = status("queued");
        return json(backend.status, 202);
      }
      return backend.status ? json(backend.status) : json({ detail: "No rule extraction was started for this job." }, 404);
    }
    if (url.endsWith("/files/rules.json")) return backend.rules === null ? json({ detail: "no" }, 404) : json(backend.rules);
    return json({ detail: "unexpected request" }, 500);
  }));
  return backend;
}
const posts = () => backend.calls.filter((c) => c.startsWith("POST"));

let host: HTMLElement;
let root: Root;
const flush = async (ms = 0) => { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); };
const mount = async (node: React.ReactElement) => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => { root.render(node); });
  await flush();
};
const q = <T extends Element = HTMLElement>(sel: string) => host.querySelector<T>(sel);
const qa = <T extends Element = HTMLElement>(sel: string) => [...host.querySelectorAll<T>(sel)];
const button = (name: string | RegExp) => qa<HTMLButtonElement>("button").find((b) => { const t = (b.textContent ?? "").trim(); return typeof name === "string" ? t === name : name.test(t); });
const click = async (target: Element | null | undefined) => { if (!target) throw new Error("nothing to click"); await act(async () => { (target as HTMLElement).click(); }); await flush(); };
const type = async (input: HTMLInputElement, value: string) => {
  const setValue = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")!.set!;
  await act(async () => { setValue.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); });
  await flush();
};
const text = () => host.textContent ?? "";

beforeEach(() => { vi.useFakeTimers(); Element.prototype.scrollIntoView = () => {}; });
afterEach(() => { act(() => root.unmount()); host.remove(); vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("before an extraction", () => {
  it("shows the document, its page count, the Legal JSON status and a Start button, and sends nothing to Bedrock", async () => {
    installBackend();
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} />);
    expect(q(".docbar h2")?.textContent).toBe("MusterBauVerordnung.pdf");
    expect(q(".rex-facts")?.textContent).toContain("MusterBauVerordnung.pdf");
    expect(q(".rex-facts")?.textContent).toContain("83");
    expect(q(".rex-facts")?.textContent).toContain("Ready");
    const start = button("Start Rule Extraction");
    expect(start?.disabled).toBe(false);
    expect(start?.className).toContain("primary");
    expect(posts()).toEqual([]); // only the status of an earlier extraction was asked for
    expect(backend.calls).toEqual(["GET /api/jobs/j1/rule-extraction"]);
  });

  it("has no Ontology / Digital Twin section, upload area, Coming Soon label, mock rules or validation step", async () => {
    installBackend();
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} />);
    for (const gone of ["Ontology", "Digital Twin", "Coming Soon", "Upload", "mock", "Auto-Accepted", "80%", "Confidence", "Validation"]) expect(text(), gone).not.toContain(gone);
    expect(q('input[type="file"]')).toBeNull();
    expect(qa(".rex-step").map((s) => s.querySelector(".rex-step-label")?.textContent)).toEqual(["Document Review", "LLM Rule Extraction & Review"]);
    expect(qa(".rex-step")[1].className).toContain("current");
  });

  it("cannot start without Legal JSON structure or without the backend's job", async () => {
    installBackend();
    await mount(<RuleExtractionView result={demoResult(null, false)} onBack={() => {}} />);
    expect(button("Start Rule Extraction")?.disabled).toBe(true);
    expect(text()).toContain("not processed by the ODOS backend");
    expect(backend.calls).toEqual([]);
  });

  it("returns to Document Review", async () => {
    installBackend();
    const onBack = vi.fn();
    await mount(<RuleExtractionView result={demoResult()} onBack={onBack} />);
    await click(button("Back to Document Review"));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("mentions the last extraction's failure without hiding the Start button", async () => {
    installBackend({ status: status("failed", { message: "Amazon Bedrock is not configured on the server.", errorCode: "not_configured" }) });
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} />);
    expect(text()).toContain("The last extraction failed: Amazon Bedrock is not configured on the server.");
    expect(button("Start Rule Extraction")).not.toBeUndefined();
  });
});

describe("starting an extraction", () => {
  it("sends one request even when clicked twice, shows an indeterminate progress state and then the stored rules", async () => {
    installBackend();
    const onRulesLoaded = vi.fn();
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} onRulesLoaded={onRulesLoaded} />);
    const start = button("Start Rule Extraction")!;
    await act(async () => { start.click(); start.click(); });
    await flush();
    expect(posts()).toEqual(["POST /api/jobs/j1/rule-extraction"]);
    expect(q(".rex-progress")?.getAttribute("aria-busy")).toBe("true");
    expect(q(".rex-progress-title")?.textContent).toBe("AI Rule Extraction in Progress");
    expect(q(".rex-progress-facts")?.textContent).toContain("Queued");

    backend.status = status("running", { startedAt: new Date().toISOString() });
    await flush(2000);
    expect(q(".rex-progress-title")?.textContent).toBe("AI Rule Extraction in Progress");
    expect(q(".rex-progress-facts")?.textContent).toContain("Running");
    expect(text()).not.toContain("Amazon Bedrock"); // the heading is provider-neutral
    expect(q(".rex-indeterminate")).not.toBeNull();
    expect(q('[role="progressbar"]')).not.toBeNull();
    expect(q('[role="progressbar"]')?.hasAttribute("aria-valuenow")).toBe(false); // indeterminate: no invented percentage
    expect(text()).not.toMatch(/\d+\s?%/);
    expect(q(".rex-elapsed")?.textContent).toMatch(/^0:0\d$/);
    await flush(5000);
    expect(q(".rex-elapsed")?.textContent).toBe("0:07"); // real time since the backend reported the start
    expect(q(".rex-progress-facts")?.textContent).toContain("Started");

    backend.rules = STORED;
    backend.status = status("completed", { rulesFile: "rules.json" });
    await flush(2000);
    expect(q(".rex-progress")).toBeNull();
    expect(onRulesLoaded).toHaveBeenCalledWith(STORED);
    expect(qa(".rex-rule")).toHaveLength(3);
    expect(posts()).toHaveLength(1);
  });

  it("follows an extraction that is already running (409) instead of failing", async () => {
    installBackend({ post: { status: 409, detail: "A rule extraction of this job is already queued or running." } });
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} />);
    backend.status = status("running", { startedAt: new Date().toISOString() });
    await click(button("Start Rule Extraction"));
    expect(q(".rex-progress-facts")?.textContent).toContain("Running");
    expect(q(".alert.error")).toBeNull();
  });

  it("picks up an extraction that is still running when the page opens, without starting another", async () => {
    installBackend({ status: status("running", { startedAt: new Date().toISOString() }) });
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} />);
    expect(q(".rex-progress-title")?.textContent).toBe("AI Rule Extraction in Progress");
    expect(button("Start Rule Extraction")).toBeUndefined();
    expect(posts()).toEqual([]);
  });

  it("loads the result of an extraction that finished while the page was closed", async () => {
    installBackend({ status: status("completed"), rules: STORED });
    const onRulesLoaded = vi.fn();
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} onRulesLoaded={onRulesLoaded} />);
    expect(qa(".rex-rule")).toHaveLength(3);
    expect(onRulesLoaded).toHaveBeenCalledWith(STORED);
    expect(posts()).toEqual([]);
  });
});

describe("failures and timeouts", () => {
  it("shows the backend's refusal (e.g. Bedrock not configured) and allows trying again", async () => {
    installBackend({ post: { status: 503, detail: "Rule extraction is not available: Amazon Bedrock is not configured on the server." } });
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} />);
    await click(button("Start Rule Extraction"));
    expect(q(".alert.error")?.textContent).toContain("Amazon Bedrock is not configured on the server.");
    expect(button("Try again")?.disabled).toBe(false);
    backend.post = null;
    await click(button("Try again"));
    expect(posts()).toHaveLength(2);
  });

  it("shows a failed extraction with the backend's message and code, and explains output-limit failures", async () => {
    installBackend();
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} />);
    await click(button("Start Rule Extraction"));
    backend.status = status("failed", { message: "The answer exceeded the output limit. Select fewer provisions.", errorCode: "output_truncated" });
    await flush(2000);
    const alert = q(".alert.error")!;
    expect(alert.textContent).toContain("The answer exceeded the output limit.");
    expect(alert.textContent).toContain("output_truncated");
    expect(alert.textContent).toContain("not available in this interface yet");
    expect(q(".rex-progress")).toBeNull();
  });

  it("reports a Bedrock timeout as a failed extraction", async () => {
    installBackend();
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} />);
    await click(button("Start Rule Extraction"));
    backend.status = status("failed", { message: "Amazon Bedrock did not answer in time.", errorCode: "bedrock_timeout" });
    await flush(2000);
    expect(q(".alert.error")?.textContent).toContain("did not answer in time");
    expect(q(".alert.error")?.textContent).toContain("bedrock_timeout");
  });

  it("keeps the interface usable when the connection is lost while waiting, and can check the status again", async () => {
    installBackend();
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} />);
    await click(button("Start Rule Extraction"));
    backend.down = true;
    await flush(10000);
    expect(q(".alert.warn")?.textContent).toContain("Still waiting for the extraction");
    expect(text()).toContain("may still be running on the server");
    backend.down = false;
    backend.rules = STORED;
    backend.status = status("completed");
    await click(button("Check status"));
    expect(qa(".rex-rule")).toHaveLength(3);
  });

  it("a failed new extraction keeps the previous results available", async () => {
    installBackend({ rules: STORED, status: status("completed") });
    await mount(<RuleExtractionView result={demoResult(STORED)} onBack={() => {}} />);
    await click(button("Restart Extraction"));
    await click(button("Start new extraction"));
    backend.status = status("failed", { message: "Amazon Bedrock is busy. Try again later.", errorCode: "bedrock_throttled" });
    await flush(2000);
    expect(q(".alert.error")?.textContent).toContain("busy");
    await click(button("Show previous results"));
    expect(qa(".rex-rule")).toHaveLength(3);
  });
});

describe("a stored rules.json", () => {
  it("is shown at once, without any request to the model, and the extraction is not started", async () => {
    installBackend({ status: status("completed"), rules: STORED });
    await mount(<RuleExtractionView result={demoResult(STORED)} onBack={() => {}} />);
    expect(qa(".rex-rule")).toHaveLength(3);
    expect(button("Start Rule Extraction")).toBeUndefined();
    expect(posts()).toEqual([]);
  });

  it("is rendered on the first paint, before the backend answered anything", () => {
    installBackend();
    const html = renderToStaticMarkup(<RuleExtractionView result={demoResult(STORED)} onBack={() => {}} />);
    expect(html).toContain("Extracted Rules");
    expect(html).toContain("tuer-breite");
  });

  it("Restart Extraction asks for confirmation naming the cost; Cancel sends nothing, confirming sends one request", async () => {
    installBackend({ status: status("completed"), rules: STORED });
    await mount(<RuleExtractionView result={demoResult(STORED)} onBack={() => {}} />);
    await click(button("Restart Extraction"));
    const dialog = q('[role="alertdialog"]')!;
    expect(dialog.textContent).toContain("paid request");
    expect(dialog.textContent).toContain("stay in place until the new extraction has succeeded");
    expect(posts()).toEqual([]);
    await click(button("Cancel"));
    expect(q('[role="alertdialog"]')).toBeNull();
    expect(posts()).toEqual([]);
    await click(button("Restart Extraction"));
    await click(button("Start new extraction"));
    expect(posts()).toHaveLength(1);
    expect(q(".rex-progress-facts")?.textContent).toContain("Queued");
  });
});

describe("displaying the real Rule JSON", () => {
  it("lists the records by their summary and id and shows the selected record unchanged, nested structures included", async () => {
    installBackend({ status: status("completed"), rules: STORED });
    await mount(<RuleExtractionView result={demoResult(STORED)} onBack={() => {}} />);
    expect(qa(".rex-rule-title").map((t) => t.textContent)).toEqual([RULE_DOOR.classification.summary, RULE_FIRE.classification.summary, "Regel mit Quelle außerhalb des Dokuments."]);
    expect(qa(".rex-rule-id").map((t) => t.textContent)).toEqual(["tuer-breite", "brandabschnitt", "fremd"]);
    const shown = JSON.parse(q(".rex-detail .jsonv-code")!.textContent!);
    expect(shown).toEqual(RULE_DOOR); // exactly the record, no added or removed field
    expect(shown.applicability.conditions).toEqual(NESTED);
    await click(qa(".rex-rule")[1]);
    expect(JSON.parse(q(".rex-detail .jsonv-code")!.textContent!)).toEqual(RULE_FIRE);
  });

  it("shows no confidence value or invented accept status", async () => {
    installBackend({ status: status("completed"), rules: STORED });
    await mount(<RuleExtractionView result={demoResult(STORED)} onBack={() => {}} />);
    expect(text()).not.toMatch(/confidence/i);
    expect(text()).not.toContain("Auto-Accepted");
    expect(qa(".rex-rule .rex-status").map((s) => s.textContent)).toEqual(["Pending Review", "Flagged", "Pending Review", "Reviewed"]);
  });

  it("states only counts that the stored result supports and keeps automated refusals apart from human decisions", async () => {
    installBackend({ status: status("completed"), rules: STORED });
    await mount(<RuleExtractionView result={demoResult(STORED)} onBack={() => {}} />);
    const stats = (scope: ParentNode) => [...scope.querySelectorAll(".rex-stat")].map((s) => [s.querySelector(".rex-stat-label")?.textContent, s.querySelector(".rex-stat-value")?.textContent]);
    expect(stats(q(".rex-overview-head")!)).toEqual([["Extracted Rules", "3"]]);
    expect(stats(q('[aria-label="Human review"].rex-group')!)).toEqual([["Pending Review", "2"], ["Reviewed or Approved", "1"]]);
    // what the automated checks found is a separate group, with the backend's own counts
    expect(stats(q('[aria-label="Automated ODOS checks"]')!)).toEqual([
      ["Flagged by ODOS Checks", "1"], ["Refused by ODOS Checks", "1"], ["Repaired by Schema Repair", "0"], ["Sentences Cited by a Rule", "8 of 10"],
    ]);
    expect(q('[aria-label="Human review"].rex-group')?.textContent).toContain("Review decisions are not stored yet, so human rejections cannot be counted.");
    expect(q('[aria-label="Automated ODOS checks"]')?.textContent).toContain("A rule without a flag is not verified as correct");
    expect(q(".rex-rejected")?.textContent).toContain("abgelehnt-1");
    expect(q(".rex-rejected")?.textContent).toContain("unknown operator");
    expect(qa(".rex-rule")).toHaveLength(3); // the refused candidate is not a rule in the list
    expect(text()).not.toMatch(/\b\d+%/);
    expect(q(".rex-bar")?.getAttribute("aria-label")).toBe("2 of 3 rules pending review, 1 reviewed or approved");
  });

  it("handles an empty result", async () => {
    const empty = rulesFile([], { modelId: "m", counts: { proposed: 0 }, rulesRejected: [] });
    installBackend({ status: status("completed"), rules: empty });
    await mount(<RuleExtractionView result={demoResult(empty)} onBack={() => {}} />);
    expect(q(".rex-noresults")?.textContent).toContain("produced no rules");
    expect(q(".rex-list")).toBeNull();
    expect(button("Restart Extraction")).not.toBeUndefined();
  });

  it("copes with a partial result: records that are not Rule JSON 2.0 are reported, optional fields may be missing", async () => {
    const bare = { schemaVersion: "2.0", id: "bare", source: { elements: [] }, classification: { type: "obligation" }, review: { status: "draft" } };
    const file = { rules: [bare, { schemaVersion: "1.0", id: "old" }] };
    installBackend({ status: status("completed"), rules: file });
    await mount(<RuleExtractionView result={demoResult(file)} onBack={() => {}} />);
    expect(text()).toContain("1 record in the result file is not valid Rule JSON 2.0");
    expect(qa(".rex-rule")).toHaveLength(1);
    expect(q(".rex-rule-title")?.textContent).toBe("bare"); // no summary: the id
    expect(q(".rex-overview")).not.toBeNull(); // no _generation block: nothing breaks
    expect(button("Show in PDF")?.disabled).toBe(true);
    await click(qa('[role="tab"]').find((t) => t.textContent === "Source Text"));
    expect(text()).toContain("names no source element");
  });
});

describe("search, filters and selection", () => {
  const open = async () => {
    installBackend({ status: status("completed"), rules: STORED });
    await mount(<RuleExtractionView result={demoResult(STORED)} onBack={() => {}} />);
  };

  it("searches by id, summary and citation, and falls back to the first match for the selection", async () => {
    await open();
    const search = q<HTMLInputElement>('input[type="search"]')!;
    await type(search, "brandabschnitt");
    expect(qa(".rex-rule")).toHaveLength(1);
    expect(q(".rex-detail-id")?.textContent).toBe("brandabschnitt");
    await type(search, "lichte Breite");
    expect(qa(".rex-rule-id").map((t) => t.textContent)).toEqual(["tuer-breite"]);
    await type(search, "§ 1 fremd");
    expect(qa(".rex-rule-id").map((t) => t.textContent)).toEqual(["fremd"]);
    await type(search, "gibt es nicht");
    expect(q(".rex-empty")?.textContent).toContain("No rules match");
    expect(q(".rex-empty-detail")).not.toBeNull();
  });

  it("filters by review status and by the backend's own flags", async () => {
    await open();
    await click(button(/^Pending Review \(2\)/));
    expect(qa(".rex-rule")).toHaveLength(2);
    await click(button(/^Flagged by Checks \(1\)/));
    expect(qa(".rex-rule-id").map((t) => t.textContent)).toEqual(["tuer-breite"]);
    await click(button(/^Reviewed \(1\)/));
    expect(qa(".rex-rule-id").map((t) => t.textContent)).toEqual(["fremd"]);
    await click(button(/^All Rules \(3\)/));
    expect(qa(".rex-rule")).toHaveLength(3);
  });

  it("switches between Rule JSON and Source Text without losing the selection", async () => {
    await open();
    await click(qa(".rex-rule")[1]);
    await click(qa('[role="tab"]').find((t) => t.textContent === "Source Text"));
    expect(q(".rex-sourcetext")?.textContent).toBe("(2) Brandabschnitte sind zu begrenzen.");
    expect(q(".rex-detail .jsonv")).toBeNull();
    await click(qa('[role="tab"]').find((t) => t.textContent === "Rule JSON"));
    expect(q(".rex-detail-id")?.textContent).toBe("brandabschnitt");
  });

  it("says so when a source element is not part of the opened document", async () => {
    await open();
    await click(qa(".rex-rule")[2]);
    await click(qa('[role="tab"]').find((t) => t.textContent === "Source Text"));
    expect(text()).toContain("not part of the opened document");
  });
});

describe("Human Review", () => {
  it("keeps Accept, Reject and Edit visible but disabled, explains why, and shows the rule as pending", async () => {
    installBackend({ status: status("completed"), rules: STORED });
    await mount(<RuleExtractionView result={demoResult(STORED)} onBack={() => {}} />);
    for (const name of ["Accept Rule", "Reject", "Edit JSON"]) {
      const b = button(new RegExp(`^${name}$`));
      expect(b, name).not.toBeUndefined();
      expect(b!.disabled, name).toBe(true);
      expect(b!.title).toContain("cannot be saved right now");
    }
    expect(q(".rex-detail")?.textContent).toContain("Review decisions cannot be saved right now");
    expect(q(".rex-detail")?.textContent).toContain("stays “Pending Review”");
  });

  it("shows the review information stored in the rule: ODOS check flags, ambiguities and notes", async () => {
    installBackend({ status: status("completed"), rules: STORED });
    await mount(<RuleExtractionView result={demoResult(STORED)} onBack={() => {}} />);
    const info = q(".rex-reviewinfo")!.textContent!;
    expect(info).toContain("unit of 'tuer.lichte_breite' is not stated in the source text");
    expect(info).toContain("Der Begriff 'Tür' ist nicht definiert.");
    expect(info).toContain("Model: eu.anthropic.claude-sonnet-4-6");
    expect(info).toContain("Machine-checkable: yes");
  });
});

describe("PDF source navigation", () => {
  it("'Show in PDF' hands the rule's first source element to Document Review", async () => {
    installBackend({ status: status("completed"), rules: STORED });
    const onShowInPdf = vi.fn();
    await mount(<RuleExtractionView result={demoResult(STORED)} onBack={() => {}} onShowInPdf={onShowInPdf} />);
    await click(button("Show in PDF"));
    expect(onShowInPdf).toHaveBeenLastCalledWith(ABS1);
    await click(qa(".rex-rule")[1]);
    await click(button("Show in PDF"));
    expect(onShowInPdf).toHaveBeenLastCalledWith(ABS2);
  });

  it("is unavailable for a rule whose source is not in the document, and never invents a page", async () => {
    installBackend({ status: status("completed"), rules: STORED });
    await mount(<RuleExtractionView result={demoResult(STORED)} onBack={() => {}} onShowInPdf={() => {}} />);
    await click(qa(".rex-rule")[2]);
    expect(button("Show in PDF")?.disabled).toBe(true);
  });

  it("Document Review opens with that element selected, on its page, with its source highlighted", async () => {
    installBackend();
    await mount(<ResultView result={demoResult(STORED)} pdfUrl="blob:pdf" initialSelectedId={ABS2} onReset={() => {}} />);
    expect(q(".pdf-stub")?.getAttribute("data-page")).toBe("4");
    expect(q(".pdf-stub")?.getAttribute("data-highlights")).toBe("1");
    expect(q(".detail")?.textContent).toContain("(2) Brandabschnitte sind zu begrenzen.");
  });

  it("Document Review ignores an unknown element ID", async () => {
    installBackend();
    await mount(<ResultView result={demoResult(STORED)} pdfUrl="blob:pdf" initialSelectedId="doc/unknown" onReset={() => {}} />);
    expect(q(".pdf-stub")?.getAttribute("data-page")).toBe("1");
    expect(q(".pdf-stub")?.getAttribute("data-highlights")).toBe("0");
  });
});

describe("source references", () => {
  const withSource = (id: string, elements: unknown[], citation: string | null = "§ 1 Test") =>
    rule(id, `Regel ${id}`, ABS1, {}, { source: { documentId: "d", citation, elements } });
  const open = async (rules: unknown[], onShowInPdf = vi.fn()) => {
    const file = rulesFile(rules);
    installBackend({ status: status("completed"), rules: file });
    await mount(<RuleExtractionView result={demoResult(file)} onBack={() => {}} onShowInPdf={onShowInPdf} />);
    return onShowInPdf;
  };
  const refs = () => qa<HTMLButtonElement>(".rex-ref");

  it("makes the citation a link into the PDF that reuses 'Show in PDF'", async () => {
    const onShowInPdf = await open([RULE_DOOR]);
    const citation = q<HTMLButtonElement>(".rex-citation")!;
    expect(citation.textContent).toBe("§ 1 tuer-breite");
    await click(citation);
    expect(onShowInPdf).toHaveBeenCalledWith(ABS1);
  });

  it("lists every source element with its name and pages and opens the one that is clicked", async () => {
    const multi = withSource("multi", [{ elementId: ABS1, pdfPages: [3] }, { elementId: ABS2, pdfPages: [4, 5] }], "§ 1 Abs. 1 und 2");
    const onShowInPdf = await open([multi]);
    expect(refs().map((r) => r.textContent)).toEqual(["Absatz (1) · p. 3", "Absatz (2) · p. 4–5"]);
    await click(refs()[1]);
    expect(onShowInPdf).toHaveBeenLastCalledWith(ABS2);
    await click(q(".rex-citation"));
    expect(onShowInPdf).toHaveBeenLastCalledWith(ABS1); // the citation opens the first source that exists
  });

  it("shows a source that is not in the document as unavailable, without a link", async () => {
    const mixed = withSource("mixed", [{ elementId: "doc/missing", pdfPages: [2] }, { elementId: ABS2, pdfPages: [4] }]);
    const onShowInPdf = await open([mixed]);
    expect(refs().map((r) => [r.textContent, r.disabled])).toEqual([["doc/missing · p. 2", true], ["Absatz (2) · p. 4", false]]);
    expect(refs()[0].title).toContain("not part of the opened document");
    await click(refs()[0]);
    expect(onShowInPdf).not.toHaveBeenCalled();
    await click(q(".rex-citation"));
    expect(onShowInPdf).toHaveBeenCalledWith(ABS2);
  });

  it("explains a rule none of whose sources can be shown, and leaves the citation as plain text", async () => {
    await open([withSource("foreign", [{ elementId: "doc/other", pdfPages: [1] }])]);
    expect(q(".rex-citation")).toBeNull();
    expect(q(".rex-refs")?.textContent).toContain("None of this rule's source elements is part of the opened document");
    expect(button("Show in PDF")?.disabled).toBe(true);
  });

  it("drops page numbers that cannot be pages of this document instead of guessing, and falls back to the element's own pages", async () => {
    const odd = withSource("odd", [{ elementId: ABS1, pdfPages: [0, 999, 3.5, -1] }]);
    await open([odd]);
    expect(refs()[0].textContent).toBe("Absatz (1) · p. 3"); // the document element's page, not a made-up one
    const unknown = withSource("unknown", [{ elementId: "doc/other", pdfPages: [0, 999] }]);
    await open([unknown]);
    expect(refs().map((r) => r.textContent)).toEqual(["doc/other"]);
  });

  it("handles a rule without citation or source elements", async () => {
    await open([withSource("bare", [], null)]);
    expect(q(".rex-citation")).toBeNull();
    expect(q(".rex-detail-source")?.textContent).toContain("Source: —");
    expect(q(".rex-refs")?.textContent).toContain("names no source element");
    expect(qa(".rex-ref")).toHaveLength(0);
  });
});

describe("the progress panel", () => {
  it("offers no cancel button and says why, instead of pretending to cancel", async () => {
    installBackend({ status: status("running", { startedAt: new Date().toISOString() }) });
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} />);
    expect(button(/cancel|stop|abort/i)).toBeUndefined();
    expect(q(".rex-progress")?.textContent).toContain("cannot be cancelled yet");
  });

  it("claims no stage or percentage: only the backend status and the real elapsed time", async () => {
    installBackend({ status: status("running", { startedAt: new Date().toISOString() }) });
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} />);
    const panel = q(".rex-progress")!;
    expect(panel.textContent).toContain("reports only whether the extraction is queued or running");
    expect(panel.textContent).not.toMatch(/\d+\s?%/);
    expect(panel.querySelector('[role="progressbar"]')?.hasAttribute("aria-valuenow")).toBe(false);
    expect(panel.querySelector(".rex-orb")?.getAttribute("aria-hidden")).toBe("true");
  });

  it("shows a queued extraction as queued, timed from the request", async () => {
    installBackend({ status: status("queued", { requestedAt: new Date(Date.now() - 65_000).toISOString() }) });
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} />);
    expect(q(".rex-progress-facts")?.textContent).toContain("Queued");
    expect(q(".rex-progress-facts")?.textContent).toContain("Requested");
    expect(q(".rex-elapsed")?.textContent).toBe("1:05");
    expect(q(".rex-progress")?.textContent).toContain("queued on the server");
  });

  it("shows hours for a very long run", async () => {
    installBackend({ status: status("running", { startedAt: new Date(Date.now() - 3_725_000).toISOString() }) });
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} />);
    expect(q(".rex-elapsed")?.textContent).toBe("1:02:05");
  });
});
