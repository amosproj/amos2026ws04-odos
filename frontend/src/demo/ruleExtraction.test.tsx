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
  post: { status: number; detail?: string; code?: string } | null; // null: accepted, the extraction becomes queued
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
        if (backend.post) {
          const refused = json({ detail: backend.post.detail }, backend.post.status);
          if (backend.post.code) refused.headers.set("X-ODOS-Error", backend.post.code);
          return refused;
        }
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
// dialogs (the overview, help) are rendered on document.body
const q = <T extends Element = HTMLElement>(sel: string) => document.body.querySelector<T>(sel);
const qa = <T extends Element = HTMLElement>(sel: string) => [...document.body.querySelectorAll<T>(sel)];
const button = (name: string | RegExp) => qa<HTMLButtonElement>("button").find((b) => { const t = (b.textContent ?? "").trim(); return typeof name === "string" ? t === name : name.test(t); });
const click = async (target: Element | null | undefined) => { if (!target) throw new Error("nothing to click"); await act(async () => { (target as HTMLElement).click(); }); await flush(); };
const type = async (input: HTMLInputElement, value: string) => {
  const setValue = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")!.set!;
  await act(async () => { setValue.call(input, value); input.dispatchEvent(new Event("input", { bubbles: true })); });
  await flush();
};
const text = () => document.body.textContent ?? "";
/** The page's text without the review-progress ring (the one real percentage on the page: decisions of people). */
const textWithoutRing = () => { const c = document.body.cloneNode(true) as HTMLElement; c.querySelectorAll(".rex-ring").forEach((r) => r.remove()); return c.textContent ?? ""; };
/** Restart Extraction lives in the ⋯ menu: open it first. */
const restart = async () => { await click(q('button[aria-label="More actions"]')); await click(button("Restart Extraction")); };
const openOverview = () => click(button("All rules"));
const closeOverview = () => click(q('.rex-dialog button[aria-label="Close"]'));
/** The citation line of each rule in the overview, without the fixtures' "§ 1 " prefix: stands for the rule's id. */
const queued = () => qa(".rex-dialog .rex-rule-sub").map((t) => t.textContent!.replace("§ 1 ", ""));
const current = () => q(".rex-card")?.getAttribute("aria-label");
const pager = () => q(".rex-pager-pos")?.textContent;
const side = () => q(".rex-side")?.textContent ?? "";
const next = () => click(q('button[aria-label="Next rule"]'));
const choices = () => qa<HTMLButtonElement>(".rex-choice");
const view = () => button("View in document");

beforeEach(() => { vi.useFakeTimers(); Element.prototype.scrollIntoView = () => {}; });
afterEach(() => { act(() => root.unmount()); host.remove(); vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("before an extraction", () => {
  it("shows the document, its page count, the Legal JSON status and a Start button, and sends nothing to Bedrock", async () => {
    installBackend();
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} />);
    expect(q(".rex-facts")?.textContent).toContain("MusterBauVerordnung.pdf");
    expect(q(".rex-facts")?.textContent).toContain("83");
    expect(q(".rex-facts")?.textContent).toContain("Ready");
    const start = button("Find Rules");
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
    expect(qa(".rex-step").map((s) => s.querySelector(".rex-step-label")?.textContent)).toEqual(["Document", "Rules extracted", "Review"]);
    expect(qa(".rex-step")[1].className).toContain("current"); // before the rules exist, "Rules extracted" is the step in progress
    expect(qa(".rex-step")[1].getAttribute("aria-current")).toBe("step");
  });

  it("cannot start without Legal JSON structure or without the backend's job", async () => {
    installBackend();
    await mount(<RuleExtractionView result={demoResult(null, false)} onBack={() => {}} />);
    expect(button("Find Rules")?.disabled).toBe(true);
    expect(text()).toContain("not processed by the ODOS backend");
    expect(backend.calls).toEqual([]);
  });

  it("returns to Document Review", async () => {
    installBackend();
    const onBack = vi.fn();
    await mount(<RuleExtractionView result={demoResult()} onBack={onBack} />);
    await click(q('button[aria-label="Back to Document Review"]')); // the "Document" step
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("the ODOS logo goes home, the Back to Document button goes one step back, and neither starts an extraction", async () => {
    installBackend();
    const onBack = vi.fn();
    const onHome = vi.fn();
    await mount(<RuleExtractionView result={demoResult()} onBack={onBack} onHome={onHome} />);
    await click(q('button[aria-label="ODOS home"]'));
    expect(onHome).toHaveBeenCalledTimes(1);
    expect(onBack).not.toHaveBeenCalled();
    await click(button("Back to Document"));
    expect(onBack).toHaveBeenCalledTimes(1);
    expect(onHome).toHaveBeenCalledTimes(1);
    expect(vi.mocked(fetch).mock.calls.filter(([, i]) => i?.method === "POST")).toHaveLength(0); // nothing was started
  });

  it("uses the shared header: branding left, steps in the centre, Back to Document right before Help", async () => {
    installBackend();
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} />);
    const header = q(".rex-top")!;
    const [brand, center, end] = [...header.children];
    expect(brand.getAttribute("aria-label")).toBe("ODOS home");
    expect(brand.textContent).toContain("ONTOLOGY-DRIVEN"); // the same branding as the workspace, once
    expect(header.querySelectorAll(".logo-mark")).toHaveLength(1);
    expect(center.querySelector(".rex-steps")).not.toBeNull();
    const controls = [...end.querySelectorAll("button")].map((b) => b.getAttribute("aria-label") ?? b.textContent);
    expect(controls).toEqual(["Back to Document", "Help"]);
  });

  it("mentions the last extraction's failure without hiding the Start button", async () => {
    installBackend({ status: status("failed", { message: "Amazon Bedrock is not configured on the server.", errorCode: "not_configured" }) });
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} />);
    expect(text()).toContain("The last attempt to find rules did not work. Finding rules is not available right now.");
    expect(text()).not.toMatch(/Amazon Bedrock|not_configured/);
    expect(button("Find Rules")).not.toBeUndefined();
  });
});

describe("starting an extraction", () => {
  it("sends one request even when clicked twice, shows an indeterminate progress state and then the stored rules", async () => {
    installBackend();
    const onRulesLoaded = vi.fn();
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} onRulesLoaded={onRulesLoaded} />);
    const start = button("Find Rules")!;
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
    expect(q(".rex-progress")?.textContent).not.toContain("Amazon Bedrock"); // the heading is provider-neutral
    expect(q(".rex-indeterminate")).not.toBeNull();
    expect(q('[role="progressbar"]')).not.toBeNull();
    expect(q('[role="progressbar"]')?.hasAttribute("aria-valuenow")).toBe(false); // indeterminate: no invented percentage
    expect(q(".rex-progress")?.textContent).not.toMatch(/\d+\s?%/);
    expect(q(".rex-elapsed")?.textContent).toMatch(/^0:0\d$/);
    await flush(5000);
    expect(q(".rex-elapsed")?.textContent).toBe("0:07"); // real time since the backend reported the start
    expect(q(".rex-progress-facts")?.textContent).toContain("Started");

    backend.rules = STORED;
    backend.status = status("completed", { rulesFile: "rules.json" });
    await flush(2000);
    expect(q(".rex-progress")).toBeNull();
    expect(onRulesLoaded).toHaveBeenCalledWith(STORED);
    expect(current()).toBe(RULE_DOOR.classification.summary); // one rule at a time, the first that waits for a decision
    expect(pager()).toBe("1 of 3");
    expect(qa(".rex-step")[2].getAttribute("aria-current")).toBe("step"); // now: Review
    expect(posts()).toHaveLength(1);
  });

  it("follows an extraction that is already running (409) instead of failing", async () => {
    installBackend({ post: { status: 409, detail: "A rule extraction of this job is already queued or running." } });
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} />);
    backend.status = status("running", { startedAt: new Date().toISOString() });
    await click(button("Find Rules"));
    expect(q(".rex-progress-facts")?.textContent).toContain("Running");
    expect(q(".alert.error")).toBeNull();
  });

  it("picks up an extraction that is still running when the page opens, without starting another", async () => {
    installBackend({ status: status("running", { startedAt: new Date().toISOString() }) });
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} />);
    expect(q(".rex-progress-title")?.textContent).toBe("AI Rule Extraction in Progress");
    expect(button("Find Rules")).toBeUndefined();
    expect(posts()).toEqual([]);
  });

  it("loads the result of an extraction that finished while the page was closed", async () => {
    installBackend({ status: status("completed"), rules: STORED });
    const onRulesLoaded = vi.fn();
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} onRulesLoaded={onRulesLoaded} />);
    expect(pager()).toBe("1 of 3");
    expect(onRulesLoaded).toHaveBeenCalledWith(STORED);
    expect(posts()).toEqual([]);
  });
});

describe("failures and timeouts", () => {
  it("shows the backend's refusal (e.g. Bedrock not configured) and allows trying again", async () => {
    installBackend({ post: { status: 503, detail: "Rule extraction is not available: Amazon Bedrock is not configured on the server." } });
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} />);
    await click(button("Find Rules"));
    expect(q(".alert.error")?.textContent).toContain("Finding rules is not available right now.");
    expect(q(".alert.error")?.textContent).not.toMatch(/Amazon Bedrock|HTTP|503/);
    expect(button("Try again")?.disabled).toBe(false);
    backend.post = null;
    await click(button("Try again"));
    expect(posts()).toHaveLength(2);
  });

  it("explains an output-limit failure in plain words, without the backend's message or code", async () => {
    installBackend();
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} />);
    await click(button("Find Rules"));
    backend.status = status("failed", { message: "The answer exceeded the output limit. Select fewer provisions.", errorCode: "output_truncated" });
    await flush(2000);
    const alert = q(".alert.error")!;
    expect(alert.textContent).toContain("This document is too large to find all of its rules in one go.");
    expect(alert.textContent).not.toMatch(/output_truncated|output limit|provisions/);
    expect(button("Try again")).toBeDefined();
    expect(q(".rex-progress")).toBeNull();
  });

  it("reports a Bedrock timeout as a failed extraction", async () => {
    installBackend();
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} />);
    await click(button("Find Rules"));
    backend.status = status("failed", { message: "Amazon Bedrock did not answer in time.", errorCode: "bedrock_timeout" });
    await flush(2000);
    expect(q(".alert.error")?.textContent).toContain("did not answer in time");
    expect(q(".alert.error")?.textContent).not.toMatch(/bedrock_timeout|Bedrock/);
  });

  it("never shows the internal element-ID message: a refused document gets a plain explanation and can be retried", async () => {
    installBackend({ post: { status: 422, detail: "The requested parts are not part of this document.", code: "invalid_scope" } });
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} />);
    await click(button("Find Rules"));
    const alert = q(".alert.error")!;
    expect(alert.textContent).toContain("This document could not be prepared for finding rules.");
    expect(alert.textContent).not.toMatch(/element ID|not part of this document|invalid_scope|422/);
    backend.post = null;
    await click(button("Try again"));
    expect(posts()).toHaveLength(2);
    expect(q(".rex-progress")).not.toBeNull();
  });

  it("explains a document with nothing to check and offers the way back instead of a pointless retry", async () => {
    installBackend({ post: { status: 422, detail: "This document has no provisions left to find rules in after filtering.", code: "nothing_to_extract" } });
    const onBack = vi.fn();
    await mount(<RuleExtractionView result={demoResult()} onBack={onBack} />);
    await click(button("Find Rules"));
    expect(q(".alert.error")?.textContent).toContain("There are no rules to find in this document.");
    expect(button("Try again")).toBeUndefined();
    await click(q(".rex-statuspanel .btn.primary"));
    expect(onBack).toHaveBeenCalledTimes(1);
    expect(posts()).toHaveLength(1);
  });

  it("explains a failure reported by the worker by its code, without the raw message", async () => {
    installBackend();
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} />);
    await click(button("Find Rules"));
    backend.status = status("failed", { message: "The requested parts are not part of this document.", errorCode: "invalid_scope" });
    await flush(2000);
    expect(q(".alert.error")?.textContent).toContain("This document could not be prepared for finding rules.");
    expect(q(".alert.error")?.textContent).not.toMatch(/not part of this document|invalid_scope/);
  });

  it("keeps the interface usable when the connection is lost while waiting, and can check the status again", async () => {
    installBackend();
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} />);
    await click(button("Find Rules"));
    backend.down = true;
    await flush(10000);
    expect(q(".alert.warn")?.textContent).toContain("Still waiting for the extraction");
    expect(text()).toContain("may still be running on the server");
    backend.down = false;
    backend.rules = STORED;
    backend.status = status("completed");
    await click(button("Check status"));
    expect(pager()).toBe("1 of 3");
  });

  it("a failed new extraction keeps the previous results available", async () => {
    installBackend({ rules: STORED, status: status("completed") });
    await mount(<RuleExtractionView result={demoResult(STORED)} onBack={() => {}} />);
    await restart();
    await click(button("Start new extraction"));
    backend.status = status("failed", { message: "Amazon Bedrock is busy. Try again later.", errorCode: "bedrock_throttled" });
    await flush(2000);
    expect(q(".alert.error")?.textContent).toContain("busy");
    await click(button("Show previous results"));
    expect(pager()).toBe("1 of 3");
  });
});

describe("a stored rules.json", () => {
  it("is shown at once, without any request to the model, and the extraction is not started", async () => {
    installBackend({ status: status("completed"), rules: STORED });
    await mount(<RuleExtractionView result={demoResult(STORED)} onBack={() => {}} />);
    expect(current()).toBe(RULE_DOOR.classification.summary);
    expect(button("Find Rules")).toBeUndefined();
    expect(posts()).toEqual([]);
  });

  it("is rendered on the first paint, before the backend answered anything", () => {
    installBackend();
    const html = renderToStaticMarkup(<RuleExtractionView result={demoResult(STORED)} onBack={() => {}} />);
    expect(html).toContain("Review Rule");
    expect(html).toContain("Türen müssen eine lichte Breite");
  });

  it("Restart Extraction asks for confirmation naming the cost; Cancel sends nothing, confirming sends one request", async () => {
    installBackend({ status: status("completed"), rules: STORED });
    await mount(<RuleExtractionView result={demoResult(STORED)} onBack={() => {}} />);
    await restart();
    const dialog = q('[role="alertdialog"]')!;
    expect(dialog.textContent).toContain("paid request");
    expect(dialog.textContent).toContain("stay in place until the new extraction has succeeded");
    expect(posts()).toEqual([]);
    await click(button("Cancel"));
    expect(q('[role="alertdialog"]')).toBeNull();
    expect(posts()).toEqual([]);
    await restart();
    await click(button("Start new extraction"));
    expect(posts()).toHaveLength(1);
    expect(q(".rex-progress-facts")?.textContent).toContain("Queued");
  });
});

describe("the review page: one rule at a time", () => {
  const openStored = async (file: unknown = STORED, onShowInPdf?: (id: string) => void) => {
    installBackend({ status: status("completed"), rules: file });
    await mount(<RuleExtractionView result={demoResult(file)} onBack={() => {}} onShowInPdf={onShowInPdf} />);
  };

  it("shows the original text and ODOS's suggestion of one rule, and the three decisions in the mockup's order", async () => {
    await openStored();
    expect(qa(".rex-card")).toHaveLength(1);
    expect(q(".rex-main-title")?.textContent).toBe("Review Rule");
    expect(q(".rex-source .rex-cite")?.textContent).toBe("§ 1 tuer-breite");
    expect(q(".rex-quote")?.textContent).toBe("(1) Türen müssen mindestens 0,90 m breit sein."); // the exact wording of the document
    expect(q(".rex-summary-text")?.textContent).toBe(RULE_DOOR.classification.summary);
    expect(q(".rex-suggest")?.textContent).toContain("tuer lichte breite is at least 0.9 m"); // derived from the record, operator and unit as stored
    expect(q(".rex-suggest")?.textContent).toContain("gebaeude hoehe is more than 7 m");
    expect(q(".rex-question")?.textContent).toBe("Is this rule suggestion correct?");
    expect(choices().map((b) => b.querySelector(".rex-choice-main")?.textContent)).toEqual(["Yes, correct", "Adjust", "No, incorrect"]);
    expect(q(".rex-source")!.compareDocumentPosition(q(".rex-suggest")!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(q(".rex-suggest")!.compareDocumentPosition(q(".rex-choices")!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("keeps the record unchanged: the Rule JSON under Advanced details is exactly the stored record, nested structures included", async () => {
    await openStored();
    expect(q(".jsonv-code")).toBeNull(); // no JSON in the default view
    await click(q(".rex-adv-toggle"));
    const shown = JSON.parse(q(".jsonv-code")!.textContent!);
    expect(shown).toEqual(RULE_DOOR);
    expect(shown.applicability.conditions).toEqual(NESTED);
    await next();
    expect(JSON.parse(q(".jsonv-code")!.textContent!)).toEqual(RULE_FIRE);
  });

  it("shows no confidence value or invented status, and never calls an unflagged rule verified", async () => {
    await openStored();
    expect(text()).not.toMatch(/confidence/i);
    expect(text()).not.toMatch(/auto-?(accepted|verified|approved)/i);
    expect(text()).not.toMatch(/\b(is|are) verified\b/i);
    expect(textWithoutRing()).not.toMatch(/\b\d+\s?%/); // the only percentage is the share of rules people reviewed
    expect(side()).toContain("1 with potential issues");
    expect(side()).toContain("2 waiting for review"); // the unflagged rule waits too; the third is marked reviewed in the file
    expect(side()).toContain("Every rule is a draft");
    await click(q(".rex-side-issues button"));
    expect(q(".rex-side-why")?.textContent).toContain("A rule without such a notice is not verified");
  });

  it("states only counts the stored result supports, and keeps everything technical behind Advanced details", async () => {
    await openStored();
    expect(side()).toContain("3 rules found");
    expect(q(".rex-ring")?.getAttribute("aria-valuenow")).toBe("33"); // one of three rules is marked reviewed in the file
    expect(side()).toContain("1 of 3 reviewed");
    expect(q(".rex-adv-body")).toBeNull();
    await click(q(".rex-adv-toggle"));
    const rows = qa(".rex-tech-list > div").map((d) => [d.querySelector("dt")?.textContent, d.querySelector("dd")?.textContent]);
    expect(rows).toEqual(expect.arrayContaining([
      ["Rule ID", "tuer-breite"], ["Model", "eu.anthropic.claude-sonnet-4-6"], ["Refused by checks", "1"], ["Repaired by schema repair", "0"],
      ["Text units cited by a rule", expect.stringContaining("8 of 10")], ["Provisions with a rule", expect.stringContaining("1 of 1")],
    ]));
    expect(q(".rex-rejected")?.textContent).toContain("abgelehnt-1");
    expect(q(".rex-rejected")?.textContent).toContain("unknown operator");
    expect(q(".rex-advanced")?.textContent).toContain("Der Begriff 'Tür' ist nicht definiert."); // the model's notes
    await openOverview();
    expect(qa(".rex-dialog .rex-rule")).toHaveLength(3); // the refused candidate is not a rule
  });

  it("keeps the model identifier, raw IDs, JSON and the rule list out of the default view", async () => {
    await openStored();
    const shown = text();
    expect(shown).not.toContain("eu.anthropic");
    expect(shown).not.toContain("doc/par-1/abs-1");
    expect(shown).not.toContain("tuer-breite\""); // no JSON
    expect(q(".rex-list")).toBeNull();
    expect(qa('[role="tab"]')).toHaveLength(0); // no tabs
  });

  it("explains a potential issue only when asked", async () => {
    await openStored();
    expect(q(".rex-issue-btn")?.textContent).toContain("Potential issue");
    expect(q(".rex-issue-list")).toBeNull();
    await click(q(".rex-issue-btn"));
    expect(q(".rex-issue-list")?.textContent).toContain("unit of 'tuer.lichte_breite' is not stated in the source text");
    await next(); // an unflagged rule has no notice
    expect(q(".rex-issue")).toBeNull();
  });

  it("handles an empty result", async () => {
    const empty = rulesFile([], { modelId: "m", counts: { proposed: 0 }, rulesRejected: [] });
    await openStored(empty);
    expect(q(".rex-noresults")?.textContent).toContain("produced no rules");
    expect(q(".rex-card")).toBeNull();
  });

  it("copes with a partial result: records that are not Rule JSON 2.0 are reported, optional fields may be missing", async () => {
    const bare = { schemaVersion: "2.0", id: "bare", source: { elements: [] }, classification: { type: "obligation" }, review: { status: "draft" } };
    const file = { rules: [bare, { schemaVersion: "1.0", id: "old" }] };
    await openStored(file);
    expect(text()).toContain("1 record in the result file is not valid Rule JSON 2.0");
    expect(pager()).toBe("1 of 1");
    expect(current()).toBe("bare"); // no summary: the id
    expect(view()?.disabled).toBe(true);
    expect(q(".rex-source")?.textContent).toContain("names no passage of the document");
    expect(q(".rex-gap")?.textContent).toContain("cannot be shown in plain language"); // no requirement at all: said so, not hidden
  });

  it("a rule whose structure the page cannot put into words says so and points to the complete rule", async () => {
    const odd = rule("odd", "Eine Regel mit unbekannter Form.", ABS1, {}, { requirements: [{ kind: "spline", fact: "x" }] });
    await openStored(rulesFile([odd]));
    expect(q(".rex-gap")?.textContent).toContain("not the complete rule");
    expect(q(".rex-gap")?.textContent).toContain("Advanced details → Rule JSON");
  });
});

describe("the overview of all rules (hidden by default)", () => {
  const open = async (file: unknown = STORED) => {
    installBackend({ status: status("completed"), rules: file });
    await mount(<RuleExtractionView result={demoResult(file)} onBack={() => {}} />);
    await openOverview();
  };

  it("lists the rules by title and citation, potential issues first", async () => {
    await open();
    expect(qa(".rex-dialog .rex-rule-title").map((t) => t.textContent)).toEqual([RULE_DOOR.classification.summary, RULE_FIRE.classification.summary, "Regel mit Quelle außerhalb des Dokuments."]);
    expect(queued()).toEqual(["tuer-breite", "brandabschnitt", "fremd"]);
    expect(qa(".rex-dialog .rex-rule .rex-chips").map((s) => s.textContent)).toEqual(["OpenPotential issue", "Open", "Reviewed"]);
  });

  it("searches by id, summary and citation; Previous and Next then walk the matches", async () => {
    await open();
    const search = q<HTMLInputElement>('input[type="search"]')!;
    await type(search, "brandabschnitt");
    expect(queued()).toEqual(["brandabschnitt"]);
    expect(current()).toBe(RULE_FIRE.classification.summary);
    await type(search, "lichte Breite");
    expect(queued()).toEqual(["tuer-breite"]);
    await type(search, "gibt es nicht");
    expect(q(".rex-dialog .rex-empty")?.textContent).toContain("No rules match");
    await closeOverview();
    expect(q(".rex-main.rex-empty-detail")?.textContent).toContain("No rules match");
    await click(button("Show all rules"));
    expect(pager()).toBe("1 of 3");
  });

  it("filters by review status and by the checks' notices", async () => {
    await open();
    expect(qa(".rex-tabs button").map((b) => [b.textContent, b.getAttribute("aria-pressed")])).toEqual([["All (3)", "true"], ["To review (2)", "false"], ["Potential issues (1)", "false"], ["Reviewed (1)", "false"]]);
    await click(button(/^Potential issues \(1\)/));
    expect(queued()).toEqual(["tuer-breite"]);
    await click(button(/^Reviewed \(1\)/));
    expect(queued()).toEqual(["fremd"]);
  });

  it("lists the rules by provision on request, without dropping any", async () => {
    const flaggedLater = rulesFile([RULE_FIRE, RULE_DOOR]);
    await open(flaggedLater);
    expect(queued()).toEqual(["tuer-breite", "brandabschnitt"]); // the rule with a potential issue moves up
    expect(q(".rex-group-h")).toBeNull();
    const order = q<HTMLSelectElement>('select[aria-label="Order of the rules"]')!;
    await act(async () => { order.value = "document"; order.dispatchEvent(new Event("change", { bubbles: true })); });
    await flush();
    expect(queued()).toEqual(["brandabschnitt", "tuer-breite"]);
    expect(qa(".rex-group-h").map((h) => h.textContent)).toEqual(["§ 1 · Türen"]);
  });
});

describe("Human Review without stored decisions", () => {
  it("keeps the three decisions visible but disabled, explains why, and shows the rule as pending", async () => {
    installBackend({ status: status("completed"), rules: STORED });
    await mount(<RuleExtractionView result={demoResult(STORED)} onBack={() => {}} />);
    for (const b of choices()) {
      expect(b.disabled).toBe(true);
      expect(b.title).toContain("cannot be saved right now");
    }
    expect(q(".rex-card")?.textContent).toContain("Review decisions cannot be saved right now");
    expect(q(".rex-card")?.textContent).toContain("stays “Pending Review”");
  });
});

describe("PDF source navigation", () => {
  it("'View in document' hands the source element of the rule to Document Review", async () => {
    installBackend({ status: status("completed"), rules: STORED });
    const onShowInPdf = vi.fn();
    await mount(<RuleExtractionView result={demoResult(STORED)} onBack={() => {}} onShowInPdf={onShowInPdf} />);
    await click(view());
    expect(onShowInPdf).toHaveBeenLastCalledWith(ABS1);
    await next();
    await click(view());
    expect(onShowInPdf).toHaveBeenLastCalledWith(ABS2);
  });

  it("offers exactly one way into the document for the rule's passage", async () => {
    installBackend({ status: status("completed"), rules: STORED });
    await mount(<RuleExtractionView result={demoResult(STORED)} onBack={() => {}} onShowInPdf={() => {}} />);
    expect(qa("button").filter((b) => /document|PDF/i.test(`${b.textContent} ${b.getAttribute("aria-label") ?? ""}`) && !/Back to Document/i.test(b.textContent ?? "") && !/Back to Document Review/.test(b.getAttribute("aria-label") ?? ""))).toHaveLength(1);
  });

  it("is unavailable for a rule whose source is not in the document, and never invents a page", async () => {
    installBackend({ status: status("completed"), rules: STORED });
    await mount(<RuleExtractionView result={demoResult(STORED)} onBack={() => {}} onShowInPdf={() => {}} />);
    await next();
    await next();
    expect(view()?.disabled).toBe(true);
    expect(q(".rex-source")?.textContent).toContain("not part of the opened document");
    expect(q(".rex-pages")?.textContent).toBe("p. 3"); // the page the record itself states, nothing else
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

  it("shows the citation and the pages of the passage", async () => {
    await open([RULE_DOOR]);
    expect(q(".rex-cite")?.textContent).toBe("§ 1 tuer-breite");
    expect(q(".rex-pages")?.textContent).toBe("p. 3");
  });

  it("shows every primary passage with its name, and opens the first one", async () => {
    const multi = withSource("multi", [{ elementId: ABS1, pdfPages: [3] }, { elementId: ABS2, pdfPages: [4, 5] }], "§ 1 Abs. 1 und 2");
    const onShowInPdf = await open([multi]);
    expect(qa(".rex-quote-label").map((l) => l.textContent)).toEqual(["Absatz (1) · p. 3", "Absatz (2) · p. 4–5"]);
    expect(qa(".rex-quote").map((x) => x.textContent)).toEqual(["(1) Türen müssen mindestens 0,90 m breit sein.", "(2) Brandabschnitte sind zu begrenzen."]);
    expect(q(".rex-pages")?.textContent).toBe("p. 3–5");
    await click(view());
    expect(onShowInPdf).toHaveBeenLastCalledWith(ABS1);
  });

  it("puts context and definition passages behind “Related passages”, each with its own way into the document", async () => {
    const ctx = withSource("ctx", [{ elementId: ABS1, role: "primary", pdfPages: [3] }, { elementId: ABS2, role: "context", pdfPages: [4] }]);
    const onShowInPdf = await open([ctx]);
    expect(qa(".rex-quote")).toHaveLength(2); // the related one is in the closed disclosure, rendered but folded
    expect(q(".rex-related summary")?.textContent).toBe("Related passages (1)");
    expect(q(".rex-related .rex-quote-label")?.textContent).toBe("Absatz (2) · context · p. 4");
    await click(q('.rex-related button[aria-label="View Absatz (2) in the document"]'));
    expect(onShowInPdf).toHaveBeenLastCalledWith(ABS2);
  });

  it("opens the first primary passage that is part of the document", async () => {
    const mixed = withSource("mixed", [{ elementId: "doc/missing", pdfPages: [2] }, { elementId: ABS2, pdfPages: [4] }]);
    const onShowInPdf = await open([mixed]);
    expect(q(".rex-source")?.textContent).toContain("not part of the opened document");
    await click(view());
    expect(onShowInPdf).toHaveBeenLastCalledWith(ABS2);
  });

  it("drops page numbers that cannot be pages of this document instead of guessing, and falls back to the element's own pages", async () => {
    await open([withSource("odd", [{ elementId: ABS1, pdfPages: [0, 999, 3.5, -1] }])]);
    expect(q(".rex-pages")?.textContent).toBe("p. 3"); // the document element's page, not a made-up one
  });

  it("handles a rule without citation or source elements", async () => {
    await open([withSource("bare", [], null)]);
    expect(q(".rex-cite")).toBeNull();
    expect(q(".rex-source")?.textContent).toContain("names no passage of the document");
    expect(view()?.disabled).toBe(true);
  });
});

describe("the progress panel", () => {
  it("shows a stop-extraction button that opens a cancellation confirmation dialog", async () => {
    installBackend({ status: status("running", { startedAt: new Date().toISOString() }) });
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} />);
    const stopBtn = button(/stop extraction/i);
    expect(stopBtn).toBeDefined();
    await click(stopBtn);
    expect(q('[role="alertdialog"]')).not.toBeNull();
    expect(text()).toContain("Stop the extraction?");
    await click(button(/keep running/i));
    expect(q('[role="alertdialog"]')).toBeNull();
    expect(button(/stop extraction/i)).toBeDefined();
  });

  it("shows a stopping indicator and no cancel button when cancelRequested is true", async () => {
    installBackend({ status: status("running", { startedAt: new Date().toISOString(), cancelRequested: true }) });
    await mount(<RuleExtractionView result={demoResult()} onBack={() => {}} />);
    expect(q(".rex-progress")?.textContent).toContain("Stopping");
    expect(button(/stop|cancel|abort/i)).toBeUndefined();
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
