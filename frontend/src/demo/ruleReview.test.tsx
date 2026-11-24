// @vitest-environment jsdom
// Human Review on the Rule Extraction page against a faked backend that keeps decisions like the real one does
// (events with a last-event ID, validation answers 409/422). Fixtures: ruleTestData.ts (test-only).
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RuleExtractionView, type RulesNav } from "./RuleExtraction";
import { AuditTrail } from "./ReviewControls";
import type { RuleHistoryEvent, RuleReviewEntry } from "./live";
import { RULE_DOOR, RULE_FIRE, RULE_FOREIGN, STORED, demoResult, generation, rulesFile, status } from "./ruleTestData";

vi.mock("../components/PdfViewer", () => ({ PdfViewer: () => <div className="pdf-stub" /> }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const EXTRACTION = String(STORED._generation.generatedAt);
const NEWER = "2026-11-21T08:30:00+00:00"; // another extraction run of the same document: same rule IDs, new identity
const NEWER_FILE = rulesFile(STORED.rules, { ...generation, generatedAt: NEWER });
const json = (body: unknown, code = 200) => new Response(JSON.stringify(body), { status: code, headers: { "Content-Type": "application/json" } });
const sha = (rule: { id: string }) => rule.id.padEnd(64, "0").replace(/[^0-9a-f]/g, "a");

interface Fake {
  /** null: the review storage answers 503 like a database without the table. */
  enabled: boolean;
  entries: Record<string, RuleReviewEntry>;
  events: RuleHistoryEvent[];
  earlier: number;
  calls: string[];
  bodies: Array<Record<string, unknown>>;
  fail: { status: number; detail: string } | null; // the next POST fails like this
  nextId: number;
  /** What `rules.json` serves, and the rules the page is opened with. */
  file: unknown;
  /** The extraction the backend's review state belongs to (the identity of its current rules.json). */
  extraction: string;
  /** Holds the review state back until released (the page is still loading it). */
  reviewsGate: Promise<void> | null;
  /** Holds the history answer of one rule back until released. */
  historyGate: Record<string, Promise<void>>;
  /** The approved export fails like this. */
  exportFail: { status: number; detail: string } | null;
  /** The review endpoints cannot be reached at all. */
  unreachable: boolean;
}
let fake: Fake;

function install(over: Partial<Fake> = {}) {
  fake = { enabled: true, entries: {}, events: [], earlier: 0, calls: [], bodies: [], fail: null, nextId: 1, file: STORED, extraction: EXTRACTION,
           reviewsGate: null, historyGate: {}, exportFail: null, unreachable: false, ...over };
  for (const rule of STORED.rules as Array<{ id: string }>) {
    fake.entries[rule.id] ??= { ruleSha256: sha(rule), state: "pending", edited: false, verification: "unverified", lastEventId: 0, reviewer: null, reason: null, at: null, effectiveRule: null };
  }
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    fake.calls.push(`${method} ${url}`);
    if (url.endsWith("/rule-extraction")) return json(status("completed"));
    if (url.endsWith("/files/rules.json")) return json(fake.file);
    if (url.includes("/rule-reviews")) {
      if (fake.unreachable) throw new TypeError("Failed to fetch");
      if (fake.reviewsGate && method === "GET" && url.endsWith("/rule-reviews")) await fake.reviewsGate;
      if (!fake.enabled) return json({ detail: "Review storage is not initialised: apply backend/db/002_rule_reviews.sql to the database (see Documentation/database-poc.md)." }, 503);
      if (url.includes("/approved-export")) {
        if (fake.exportFail) return json({ detail: fake.exportFail.detail }, fake.exportFail.status);
        return new Response(JSON.stringify({ _review: { extractionId: fake.extraction, count: 1 }, rules: [] }), { status: 200, headers: { "Content-Type": "application/json", "Content-Disposition": "attachment; filename*=UTF-8''MusterBauVerordnung.approved.rules.json" } });
      }
      if (url.includes("/history")) {
        const ruleId = decodeURIComponent(url.split("ruleId=")[1]);
        await fake.historyGate[ruleId];
        return json(fake.events.filter((e) => e.ruleSha256 === sha({ id: ruleId })));
      }
      if (method === "POST") {
        const body = JSON.parse(String(init?.body)) as Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
        fake.bodies.push(body);
        if (fake.fail) { const { status: code, detail } = fake.fail; fake.fail = null; return json({ detail }, code); }
        if (body.extractionId !== fake.extraction) return json({ detail: "The rules of this job changed since they were loaded. Reload the page." }, 409);
        const entry = fake.entries[body.ruleId];
        if (body.expectedLastEventId !== entry.lastEventId) return json({ detail: "Someone else changed this rule's review in the meantime. Reload the page." }, 409);
        const next: RuleReviewEntry = { ...entry, state: body.action === "accept" ? "accepted" : body.action === "reject" ? "rejected" : "pending",
          reviewer: body.reviewer, reason: body.reason ?? null, at: "2026-11-21T10:00:00+00:00", lastEventId: fake.nextId++,
          edited: body.action === "edit" ? true : body.action === "reset" ? false : entry.edited,
          effectiveRule: body.action === "edit" ? body.editedRule : body.action === "reset" ? null : entry.effectiveRule };
        fake.entries[body.ruleId] = next;
        fake.events.push({ id: next.lastEventId, extractionId: fake.extraction, action: body.action, decision: next.state, reviewer: body.reviewer, reason: next.reason, at: next.at!, edited: next.edited, ruleSha256: entry.ruleSha256 });
        return json(next, 201);
      }
      const rules = fake.entries;
      const counts = { pending: 0, accepted: 0, rejected: 0, edited: 0 };
      for (const e of Object.values(rules)) { counts[e.state]++; counts.edited += e.edited ? 1 : 0; }
      return json({ extractionId: fake.extraction, criteriaVersion: 1, counts, rules, earlierExtractionEvents: fake.earlier });
    }
    return json({ detail: "unexpected request" }, 500);
  }));
  return fake;
}
const posts = () => fake.calls.filter((c) => c.startsWith("POST"));

let host: HTMLElement;
let root: Root;
const flush = async (ms = 0) => { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); };
const open = async (nav?: { current: RulesNav | null }) => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => { root.render(<RuleExtractionView result={demoResult(fake.file)} onBack={() => {}} nav={nav} />); });
  await flush();
  await flush();
};
const mount = async (over: Partial<Fake> = {}, { name = "", nav }: { name?: string; nav?: { current: RulesNav | null } } = {}) => {
  window.localStorage.clear();
  if (name) window.localStorage.setItem("odos.reviewer", name);
  install(over);
  await open(nav);
};
const close = () => { act(() => root.unmount()); host.remove(); };
// the overview and help are dialogs rendered on document.body, so queries look at the whole document
const q = <T extends Element = HTMLElement>(sel: string) => document.body.querySelector<T>(sel);
const qa = <T extends Element = HTMLElement>(sel: string) => [...document.body.querySelectorAll<T>(sel)];
const button = (name: string | RegExp) => qa<HTMLButtonElement>("button").find((b) => { const t = (b.textContent ?? "").trim(); return typeof name === "string" ? t === name : name.test(t); });
const click = async (target: Element | null | undefined) => { if (!target) throw new Error("nothing to click"); await act(async () => { (target as HTMLElement).click(); }); await flush(); };
const fill = async (el: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement, value: string) => {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : el instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
  await act(async () => { Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, value); el.dispatchEvent(new Event(el instanceof HTMLSelectElement ? "change" : "input", { bubbles: true })); });
  await flush();
};
const key = async (k: string, target: EventTarget = document.body) => { await act(async () => { target.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true })); }); await flush(); };

/** The three decisions under "Is this rule suggestion correct?". */
const YES = "Accept", ADJUST = "Edit", NO = "Reject";
const choice = (name: typeof YES | typeof ADJUST | typeof NO) => qa<HTMLButtonElement>(".rex-choice").find((b) => b.querySelector(".rex-choice-main")?.textContent === name)!;
const allOff = () => [YES, ADJUST, NO].every((n) => choice(n as typeof YES).disabled);
const reviewerInput = () => q<HTMLInputElement>(".rex-name input")!;
const current = () => q(".rex-card")?.getAttribute("aria-label"); // the title of the rule on screen
const pager = () => q(".rex-pager-pos")?.textContent?.replace(/^Rule /, ""); // "Rule 1 of 3" → "1 of 3"
const decided = () => q(".rex-decided")?.textContent ?? null;
const side = () => q(".rex-side")?.textContent ?? "";
const ring = () => Number(q(".rv-progress")?.getAttribute("aria-valuenow"));
const alert = () => q('.rex-decide [role="alert"]')?.textContent;
const openOverview = () => click(q('button[aria-label="Rule list"]'));
/** The count beside a review-status filter in the left panel; undefined when that filter is not offered. */
const statusCount = (label: string) => { const row = qa(".rv-status-row").find((r) => r.querySelector(".rv-nav-label")?.textContent === label); return row ? Number(row.querySelector(".rv-count")?.textContent) : undefined; };

const rows = () => qa(".rex-dialog .rex-rule");
const rowStates = () => qa(".rex-dialog .rex-rule .rex-state").map((c) => c.textContent);
const rowTags = (kind: "flag" | "edited") => qa(`.rex-dialog .rex-rule .rex-tag.${kind}`).length;
const closeOverview = () => click(q('.rex-dialog button[aria-label="Close"]'));
// The review history is no longer a section of the page; it is stored and served as before (the audit trail component reads it).
let auditHost: HTMLElement | null = null;
let auditRoot: Root | null = null;
const showAudit = async (ruleId: string, version = 0) => {
  if (!auditHost) { auditHost = document.createElement("div"); document.body.append(auditHost); auditRoot = createRoot(auditHost); }
  await act(async () => { auditRoot!.render(<AuditTrail jobId="j1" ruleId={ruleId} extractionId={EXTRACTION} version={version} />); });
  await flush();
};
const advanced = () => showAudit("tuer-breite");
const next = () => click(q('button[aria-label="Next rule"]'));
const previous = () => click(q('button[aria-label="Previous rule"]'));
const stayOnRule = async () => { await openOverview(); await click(q<HTMLInputElement>('.rex-queue-opts input[type="checkbox"]')); await closeOverview(); };

beforeEach(() => { vi.useFakeTimers(); Element.prototype.scrollIntoView = () => {}; window.scrollTo = () => {}; });
afterEach(() => { if (auditRoot) { act(() => auditRoot!.unmount()); auditHost!.remove(); auditRoot = null; auditHost = null; } close(); vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("without review storage", () => {
  it("keeps the three decisions disabled and passes on the backend's reason", async () => {
    await mount({ enabled: false });
    expect(allOff()).toBe(true);
    expect(q(".rex-card")?.textContent).toContain("Review decisions cannot be saved right now");
    expect(q(".rex-card")?.textContent).toContain("002_rule_reviews.sql");
    expect(button(/Download approved rules/)).toBeUndefined();
    expect(q(".rex-name")).toBeNull(); // no reviewer name is asked for when nothing can be decided
    expect(posts()).toEqual([]);
  });
});

describe("with review storage", () => {
  it("shows one rule with real progress in the sidebar, enables the decisions and offers the export only once something is accepted", async () => {
    await mount();
    expect(side()).toContain("Rules (3)");
    expect(ring()).toBe(0);
    expect(statusCount("Potential issues")).toBe(1);
    expect(statusCount("Pending")).toBe(3); // the unflagged rules wait for review too
    expect(pager()).toBe("1 of 3");
    expect(qa(".rex-card")).toHaveLength(1); // one rule at a time
    expect(choice(YES).disabled).toBe(false);
    expect(button(/Download approved rules/)?.disabled).toBe(true);
  });

  it("needs a reviewer name before it sends anything, and remembers the name in this browser", async () => {
    await mount();
    await click(choice(YES));
    expect(alert()).toContain("Enter your name next to “Reviewing as” first.");
    expect(reviewerInput().getAttribute("aria-invalid")).toBe("true");
    expect(posts()).toEqual([]);
    await fill(reviewerInput(), "Dana Prüfer");
    expect(window.localStorage.getItem("odos.reviewer")).toBe("Dana Prüfer");
    expect(alert()).toBeUndefined();
  });

  it("accepts a rule with the exact identifiers the backend gave, then moves on to the next open rule", async () => {
    await mount({}, { name: "Dana Prüfer" });
    expect(current()).toBe(RULE_DOOR.classification.summary);
    await click(choice(YES));
    expect(fake.bodies).toEqual([{ ruleId: "tuer-breite", extractionId: EXTRACTION, expectedRuleSha256: sha(RULE_DOOR), expectedLastEventId: 0, action: "accept", reviewer: "Dana Prüfer" }]);
    expect(current()).toBe(RULE_FIRE.classification.summary);
    expect(pager()).toBe("2 of 3"); // all rules stay in the sequence
    expect(statusCount("Accepted")).toBe(1);
    expect(statusCount("Pending")).toBe(2);
    expect(ring()).toBe(33);
    expect(button(/Download approved rules/)?.textContent).toContain("Download approved rules (1)");
    expect(button(/Download approved rules/)?.disabled).toBe(false);
    await previous();
    expect(decided()).toContain("Accepted by Dana Prüfer");
    expect(choice(YES).disabled).toBe(true); // already accepted
  });

  it("stays on the decided rule when the next-open-rule option is off, and remembers the option", async () => {
    const nav: { current: RulesNav | null } = { current: null };
    await mount({}, { name: "Dana", nav });
    await stayOnRule();
    expect(nav.current?.advance).toBe(false);
    await click(choice(YES));
    expect(current()).toBe(RULE_DOOR.classification.summary);
    expect(decided()).toContain("Accepted by Dana");
  });

  it("offers the next-open-rule option only where decisions can be made", async () => {
    await mount({ enabled: false });
    await openOverview();
    expect(q('.rex-queue-opts input[type="checkbox"]')).toBeNull();
  });

  it("sends one event even when clicked twice", async () => {
    await mount({}, { name: "Dana" });
    const yes = choice(YES);
    await act(async () => { yes.click(); yes.click(); });
    await flush();
    expect(posts()).toHaveLength(1);
  });

  it("rejects only with a reason and shows the reason on the rule", async () => {
    await mount({}, { name: "Dana" });
    await click(choice(NO));
    expect(choice(NO).getAttribute("aria-expanded")).toBe("true");
    expect(button("Reject rule")?.disabled).toBe(true);
    await fill(q<HTMLTextAreaElement>(".rex-form textarea")!, "Wrong threshold");
    await click(button("Reject rule"));
    expect(fake.bodies[0]).toMatchObject({ action: "reject", reason: "Wrong threshold" });
    expect(statusCount("Rejected")).toBe(1);
    await previous();
    expect(decided()).toContain("Rejected by Dana");
    expect(q(".rex-decided-reason")?.textContent).toBe("Reason: Wrong threshold");
  });

  it("adjusts a value in the simple editor: the same record with the new value, same JSON type, original kept", async () => {
    await mount({}, { name: "Dana" });
    await click(choice(ADJUST));
    const labels = qa(".rex-fields .rex-field > span").map((s) => s.textContent);
    expect(labels).toContain("Requirement: tuer lichte breite (m)");
    expect(labels).toContain("Applies when: gebaeude hoehe (m)");
    const width = qa<HTMLLabelElement>(".rex-fields .rex-field").find((l) => l.querySelector("span")?.textContent === "Requirement: tuer lichte breite (m)")!.querySelector("input")!;
    expect(width.value).toBe("0.9");
    await fill(width, "1,0"); // a decimal comma is read as a number
    await click(button("Save edit"));
    const sent = fake.bodies[0].editedRule as typeof RULE_DOOR;
    expect(fake.bodies[0].action).toBe("edit");
    expect(sent).toEqual({ ...RULE_DOOR, requirements: [{ ...RULE_DOOR.requirements[0], value: 1 }] });
    expect(typeof sent.requirements[0].value).toBe("number");
    expect(RULE_DOOR.requirements[0].value).toBe(0.9); // the extracted record is not touched
    expect(current()).toBe(RULE_DOOR.classification.summary); // an adjustment is not a decision: the rule stays
    expect(decided()).toContain("Edited · not reviewed yet");
    expect(q(".rex-suggest")?.textContent).toContain("tuer lichte breite is at least 1 m");
    await click(q("#rv-tab-json")); // the edited record (in force) and the extracted one, side by side in the Rule JSON tab
    expect(JSON.parse(q(".jsonv-code")!.textContent!)).toEqual(sent);
    expect(q('.rex-jsonview button[aria-pressed="true"]')?.textContent).toBe("Edited (in force)");
    await click(button("Extracted (original)"));
    expect(JSON.parse(q(".jsonv-code")!.textContent!)).toEqual(RULE_DOOR);
  });

  it("refuses values that are not numbers, and an adjustment that changes nothing, without sending", async () => {
    await mount({}, { name: "Dana" });
    await click(choice(ADJUST));
    await click(button("Save edit"));
    expect(alert()).toBe("Nothing was changed.");
    const width = qa<HTMLLabelElement>(".rex-fields .rex-field").find((l) => l.querySelector("span")?.textContent === "Requirement: tuer lichte breite (m)")!.querySelector("input")!;
    await fill(width, "breit");
    await click(button("Save edit"));
    expect(alert()).toContain("enter a number");
    expect(posts()).toEqual([]);
  });

  it("the advanced editor validates the JSON locally and stores the edit beside the original", async () => {
    await mount({}, { name: "Dana" });
    await click(choice(ADJUST));
    await click(button("Advanced editor"));
    const editor = q<HTMLTextAreaElement>(".rex-editor")!;
    expect(JSON.parse(editor.value)).toEqual(RULE_DOOR); // starts from the rule in force
    await fill(editor, "{ not json");
    await click(button("Save edit"));
    expect(alert()).toContain("not valid JSON");
    await fill(editor, "[1]");
    await click(button("Save edit"));
    expect(alert()).toContain("must be a JSON object");
    expect(posts()).toEqual([]);
    const edited = { ...RULE_DOOR, classification: { ...RULE_DOOR.classification, summary: "Türen: mindestens 1,00 m." } };
    await fill(editor, JSON.stringify(edited));
    await click(button("Save edit"));
    expect(fake.bodies[0]).toMatchObject({ action: "edit", editedRule: edited });
    expect(current()).toBe("Türen: mindestens 1,00 m.");
    expect(q(".rex-edited-note")?.textContent).toContain("Edited by a reviewer");
  });

  it("shows the backend's validation message for an invalid edit and keeps the editor open", async () => {
    await mount({}, { name: "Dana" });
    await click(choice(ADJUST));
    await click(button("Advanced editor"));
    fake.fail = { status: 422, detail: "The edited rule is not valid Rule JSON 2.0: classification: 'classification' is a required property" };
    await click(button("Save edit"));
    expect(alert()).toContain("is a required property");
    expect(q(".rex-editor")).not.toBeNull();
    expect(decided()).toBeNull(); // still open, nothing applied
  });

  it("undoes an adjustment", async () => {
    await mount({}, { name: "Dana" });
    await click(choice(ADJUST));
    await click(button("Advanced editor"));
    await click(button("Save edit"));
    await click(button("Reset edit"));
    expect(fake.bodies.map((b) => b.action)).toEqual(["edit", "reset"]);
    expect(button("Reset edit")).toBeUndefined();
    await openOverview();
    expect(rowTags("edited")).toBe(0);
  });

  it("on a conflict says so, keeps the rule in view and reloads the current state instead of applying anything", async () => {
    await mount({}, { name: "Dana" });
    fake.entries["tuer-breite"] = { ...fake.entries["tuer-breite"], state: "rejected", lastEventId: 7, reviewer: "Alex", reason: "no" }; // somebody else decided
    const before = fake.calls.filter((c) => c.startsWith("GET") && c.endsWith("/rule-reviews")).length;
    await click(choice(YES));
    expect(alert()).toContain("Someone else changed this rule's review");
    expect(fake.calls.filter((c) => c.startsWith("GET") && c.endsWith("/rule-reviews")).length).toBe(before + 1);
    expect(current()).toBe(RULE_DOOR.classification.summary);
    expect(decided()).toContain("Rejected by Alex"); // the other reviewer's decision is now shown
  });

  it("stores the review history of every decision and serves it per rule", async () => {
    await mount({}, { name: "Dana" });
    await stayOnRule();
    await click(choice(YES));
    await click(choice(NO));
    await fill(q<HTMLTextAreaElement>(".rex-form textarea")!, "On second thought");
    await click(button("Reject rule"));
    expect(q(".rex-audit")).toBeNull(); // not part of the page
    expect(fake.events.map((e) => [e.action, e.reviewer])).toEqual([["accept", "Dana"], ["reject", "Dana"]]); // but every decision is stored
    await advanced();
    expect(qa(".rex-audit-list li").map((li) => li.textContent)).toEqual([expect.stringContaining("Accepted by Dana"), expect.stringContaining("Rejected by Dana — On second thought")]);
    await showAudit("brandabschnitt"); // another rule has no events
    expect(q(".rex-audit")?.textContent).toContain("No review events yet");
  });

  it("keeps the stored history out of the page's UI", async () => {
    await mount({ earlier: 4 });
    expect(q(".rex-advanced, .rex-adv-toggle, .rex-audit")).toBeNull();
    expect(side()).not.toMatch(/history|Events of earlier/i);
  });

  it("keeps the potential issue apart from the human decision", async () => {
    await mount({}, { name: "Dana" });
    expect(q(".rex-issue-btn")?.textContent).toContain("flagged by automatic checks");
    await click(choice(YES)); // accepting a flagged rule does not clear its notice
    await openOverview();
    expect(rowStates()).toEqual(["Accepted", "Pending", "Pending"]);
    expect(rowTags("flag")).toBe(1);
    expect(statusCount("Potential issues")).toBe(1);
  });
});

// ── extraction identity (H1): a decision is only ever made on the rules of the extraction the reviewer is looking at ──────────

const stateOf = (state: RuleReviewEntry["state"] = "pending", lastEventId = 0): Record<string, RuleReviewEntry> =>
  Object.fromEntries((STORED.rules as Array<{ id: string }>).map((r) => [r.id, { ruleSha256: sha(r), state, edited: false, verification: "unverified" as const, lastEventId,
    reviewer: state === "pending" ? null : "Alex", reason: null, at: state === "pending" ? null : "2026-11-21T09:00:00+00:00", effectiveRule: null }]));

describe("extraction identity", () => {
  it("two tabs: after another extraction replaced the rules, nothing displayed can be decided, and reloading shows consistent rules and decisions", async () => {
    await mount({}, { name: "Dana" });
    // tab B ran a new extraction (same rule IDs, new identity); somebody already accepted a rule of it
    fake.extraction = NEWER;
    fake.file = NEWER_FILE;
    fake.entries = stateOf("accepted", 5);
    fake.entries["brandabschnitt"] = { ...fake.entries["brandabschnitt"], state: "pending", lastEventId: 0, reviewer: null, at: null };

    await click(choice(YES)); // tab A still shows the old extraction: the backend refuses it (409) ...
    expect(posts()).toHaveLength(1);
    expect(fake.bodies[0]).toMatchObject({ extractionId: EXTRACTION });
    // ... and the page now knows the review state belongs to another extraction
    expect(q(".rex-stale")?.textContent).toContain("The extraction has changed");
    expect(allOff()).toBe(true);
    expect(statusCount("Accepted") ?? 0).toBe(0); // the other extraction's decisions are not applied to the displayed rules by ID
    expect(button(/Download approved rules/)).toBeUndefined();
    for (const name of [YES, ADJUST, NO]) await click(choice(name as typeof YES));
    expect(posts()).toHaveLength(1); // disabled buttons send nothing

    const rulesGets = () => fake.calls.filter((c) => c === "GET /api/jobs/j1/files/rules.json").length;
    const before = rulesGets();
    await click(button("Reload results")); // the current rules.json, then the review state of those very rules
    expect(rulesGets()).toBe(before + 1);
    expect(q(".rex-stale")).toBeNull();
    expect(statusCount("Accepted")).toBe(2); // Alex's decisions on the new extraction, now on the new rules
    await openOverview();
    await click(rows().find((r) => r.textContent?.includes(RULE_FIRE.classification.summary)));
    await click(choice(YES)); // a decision made now carries the new identity
    expect(fake.bodies[1]).toMatchObject({ extractionId: NEWER, ruleId: "brandabschnitt" });
    expect(posts()).toHaveLength(2);
  });

  it("the same extraction is not stale: identical identity means decisions are applied and possible", async () => {
    await mount({}, { name: "Dana" });
    expect(q(".rex-stale")).toBeNull();
    expect(choice(YES).disabled).toBe(false);
  });

  it("review state of another extraction than the displayed rules: decisions are disabled at once and none of it is shown", async () => {
    await mount({ extraction: NEWER, entries: stateOf("rejected", 9) });
    expect(q(".rex-stale")?.textContent).toContain("The extraction has changed");
    expect(q(".rex-card")?.textContent).toContain("not the current extraction");
    expect(allOff()).toBe(true);
    expect(ring()).toBe(0);
    expect(statusCount("Rejected") ?? 0).toBe(0);
    expect(posts()).toEqual([]);
  });

  it("rules without an extraction identifier cannot be reviewed", async () => {
    await mount({ file: { rules: STORED.rules } }); // no _generation.generatedAt
    expect(allOff()).toBe(true);
    expect(q(".rex-card")?.textContent).toContain("carry no extraction identifier");
    expect(button("Reload results")).toBeUndefined(); // reloading would not help
    expect(posts()).toEqual([]);
  });

  it("a review action cannot be started while the review state is still loading", async () => {
    let release!: () => void;
    await mount({ reviewsGate: new Promise<void>((r) => { release = r; }) });
    expect(allOff()).toBe(true);
    expect(q(".rex-card")?.textContent).toContain("Loading the review state");
    await act(async () => { release(); });
    await flush();
    expect(choice(YES).disabled).toBe(false);
    expect(posts()).toEqual([]);
  });

  it("a backend that cannot be reached leaves the decisions disabled and sends nothing", async () => {
    await mount({ unreachable: true });
    expect(allOff()).toBe(true);
    expect(q(".rex-card")?.textContent).toContain("Review decisions cannot be saved right now");
    expect(q(".rex-card")?.textContent).toContain("This rule stays “Pending Review”");
    expect(posts()).toEqual([]);
  });

  it("a record that changed under the same page is refused by the backend and the fresh state is shown", async () => {
    await mount({}, { name: "Dana" });
    fake.entries["tuer-breite"] = { ...fake.entries["tuer-breite"], ruleSha256: "b".repeat(64) };
    fake.fail = { status: 409, detail: "The rules of this job changed since they were loaded. Reload the page." };
    await click(choice(YES));
    expect(alert()).toContain("changed since they were loaded");
    expect(decided()).toBeNull(); // nothing was applied
  });
});

// ── audit trail across extractions (M1) ──────────────────────────────────────────────────────────────────────────────────────

const earlierEvent = (over: Partial<RuleHistoryEvent> = {}): RuleHistoryEvent => ({ id: 3, extractionId: "2026-11-01T08:00:00+00:00", action: "accept", decision: "accepted", reviewer: "Alex",
  reason: null, at: "2026-11-01T09:00:00+00:00", edited: false, ruleSha256: sha(RULE_DOOR), ...over });

describe("audit trail across extractions", () => {
  it("lists events of earlier extractions apart, labelled as history that does not apply to these rules", async () => {
    await mount({ events: [earlierEvent()], earlier: 1 }, { name: "Dana" });
    expect(decided()).toBeNull(); // the earlier acceptance is not carried over
    await advanced();
    expect(qa('.rex-audit-list[aria-label="Events of this extraction"] li')).toHaveLength(0);
    expect(q(".rex-audit")?.textContent).toContain("No review events yet for these rules");
    expect(q(".rex-audit-earlier-h")?.textContent).toContain("history only, not applied to these rules");
    const earlier = qa(".rex-audit-earlier li");
    expect(earlier).toHaveLength(1);
    expect(earlier[0].textContent).toContain("Accepted by Alex");
    expect(earlier[0].textContent).toContain("earlier extraction");
  });

  it("keeps the current extraction's events and the earlier ones in separate lists", async () => {
    await mount({ events: [earlierEvent()], nextId: 10 }, { name: "Dana" });
    await stayOnRule();
    await click(choice(YES));
    await advanced();
    const now = qa('.rex-audit-list[aria-label="Events of this extraction"] li').map((li) => li.textContent);
    expect(now).toHaveLength(1);
    expect(now[0]).toContain("Accepted by Dana");
    expect(now[0]).not.toContain("earlier extraction");
    expect(qa(".rex-audit-earlier li")).toHaveLength(1);
    expect(decided()).toContain("Accepted by Dana"); // the state comes from the current extraction's event only
  });
});

describe("small review form fixes", () => {
  it("L1: the reason typed for a rejection is not carried into an adjustment", async () => {
    await mount({}, { name: "Dana" });
    await click(choice(NO));
    await fill(q<HTMLTextAreaElement>(".rex-form textarea")!, "Wrong threshold");
    await click(button("Cancel"));
    await click(choice(ADJUST));
    await click(button("Advanced editor"));
    const reason = qa<HTMLLabelElement>(".rex-form .rex-field").find((l) => l.textContent?.startsWith("Reason for the change"))!.querySelector("input")!;
    expect(reason.value).toBe("");
    await click(button("Save edit"));
    expect(fake.bodies[0]).toMatchObject({ action: "edit" });
    expect(fake.bodies[0]).not.toHaveProperty("reason");
  });

  it("L2: a slow history of the previous rule never shows under the one on screen", async () => {
    let release!: () => void;
    await mount({ events: [earlierEvent({ extractionId: EXTRACTION, reviewer: "Previous" })], historyGate: { "tuer-breite": new Promise<void>((r) => { release = r; }) } }, { name: "Dana" });
    await showAudit("tuer-breite"); // asks for tuer-breite, which is still on its way
    await showAudit("brandabschnitt"); // another rule meanwhile
    await act(async () => { release(); });
    await flush();
    expect(q(".rex-audit")?.textContent).not.toContain("Previous");
    expect(q(".rex-audit")?.textContent).toContain("No review events yet");
  });
});

// ── the approved export (L4) ─────────────────────────────────────────────────────────────────────────────────────────────────

describe("approved export download", () => {
  let created: Blob[];
  let saved: Array<{ name: string; href: string }>;
  beforeEach(() => {
    created = []; saved = [];
    URL.createObjectURL = vi.fn((b: Blob) => { created.push(b); return "blob:approved"; });
    URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { saved.push({ name: this.download, href: this.href }); });
  });
  afterEach(() => { vi.restoreAllMocks(); });

  it("saves the file the backend sent, under the name it proposed", async () => {
    await mount({}, { name: "Dana" });
    await click(choice(YES));
    await click(button(/Download approved rules/));
    expect(fake.calls).toContain("GET /api/jobs/j1/rule-reviews/approved-export?download=true");
    expect(created).toHaveLength(1);
    expect(saved).toEqual([{ name: "MusterBauVerordnung.approved.rules.json", href: "blob:approved" }]);
    expect(q('.rex-results > [role="alert"]')).toBeNull();
  });

  it("does not save anything when the backend answers with an error, and says why", async () => {
    await mount({ exportFail: { status: 409, detail: "A rule extraction of this job is running; rules can be reviewed when it has finished." } }, { name: "Dana" });
    await click(choice(YES));
    await click(button(/Download approved rules/));
    expect(created).toHaveLength(0);
    expect(saved).toEqual([]);
    expect(q('.rex-results > [role="alert"]')?.textContent).toContain("The approved rules were not downloaded: A rule extraction of this job is running");
  });

  it("does not save an error when the backend cannot be reached", async () => {
    await mount({}, { name: "Dana" });
    await click(choice(YES));
    fake.unreachable = true;
    await click(button(/Download approved rules/));
    expect(created).toHaveLength(0);
    expect(q('.rex-results > [role="alert"]')?.textContent).toContain("not reachable");
  });
});

// ── navigation: one rule at a time, the overview, the keyboard, and the place across "View in document" (M3) ─────────────────

describe("navigation", () => {
  it("walks the rules one at a time with Previous and Next, potential issues first, and stops at both ends", async () => {
    await mount({ enabled: false });
    expect(pager()).toBe("1 of 3");
    expect(current()).toBe(RULE_DOOR.classification.summary); // the flagged rule first
    expect(q<HTMLButtonElement>('button[aria-label="Previous rule"]')!.disabled).toBe(true);
    await next();
    expect(current()).toBe(RULE_FIRE.classification.summary);
    await next();
    expect(pager()).toBe("3 of 3");
    expect(q<HTMLButtonElement>('button[aria-label="Next rule"]')!.disabled).toBe(true);
    await previous();
    expect(pager()).toBe("2 of 3");
  });

  it("← and → move between rules, but not while the reviewer is typing", async () => {
    await mount({}, { name: "Dana" });
    await key("ArrowRight");
    expect(pager()).toBe("2 of 3");
    await key("ArrowRight", reviewerInput());
    expect(pager()).toBe("2 of 3");
    await key("ArrowLeft");
    expect(pager()).toBe("1 of 3");
  });

  it("opens on the first rule that still waits for a decision", async () => {
    await mount({ entries: { ...stateOf(), "tuer-breite": { ...stateOf("accepted", 1)["tuer-breite"] } } });
    expect(current()).toBe(RULE_FIRE.classification.summary);
    expect(pager()).toBe("2 of 3");
  });

  it("keeps the overview of all rules hidden until asked for; a rule chosen there is shown and the overview closes", async () => {
    await mount();
    expect(q(".rex-list")).toBeNull();
    await openOverview();
    expect(q('[role="dialog"]')?.getAttribute("aria-modal")).toBe("true");
    expect(rows().map((r) => r.querySelector(".rex-rule-title")?.textContent)).toEqual([RULE_DOOR, RULE_FIRE, RULE_FOREIGN].map((x) => x.classification.summary));
    await click(rows()[2]);
    expect(q('[role="dialog"]')).toBeNull();
    expect(pager()).toBe("3 of 3");
    await openOverview();
    await key("Escape", q('[role="dialog"] input[type="search"]')!);
    expect(q('[role="dialog"]')).toBeNull();
  });

  it("a filter chosen in the overview limits Previous and Next to its rules and says so", async () => {
    await mount();
    await openOverview();
    await click(button(/^Potential issues \(1\)/));
    await closeOverview();
    expect(pager()).toBe("1 of 1 · Potential issues");
  });

  it("restores the rule, filter and search when the page is opened again, without new extraction requests", async () => {
    const nav: { current: RulesNav | null } = { current: null };
    await mount({}, { name: "Dana", nav });
    await openOverview();
    await fill(q<HTMLInputElement>('input[type="search"]')!, "brand");
    await click(rows()[0]); // the only match: brandabschnitt
    expect(nav.current).toMatchObject({ jobId: "j1", filter: "all", search: "brand", selectedId: "brandabschnitt" });

    close(); // "View in document" leaves the page ...
    const callsBefore = fake.calls.length;
    await open(nav); // ... and "Continue to Rule Extraction" opens it again
    expect(current()).toBe(RULE_FIRE.classification.summary);
    expect(pager()).toBe("1 of 1 · “brand”");
    const again = fake.calls.slice(callsBefore);
    expect(again.filter((c) => c.startsWith("POST"))).toEqual([]); // nothing was started
    expect(again.filter((c) => c.endsWith("/files/rules.json"))).toEqual([]); // the rules in hand are not fetched again
  });

  it("starts clean for another document", async () => {
    const nav: { current: RulesNav | null } = { current: { jobId: "other", filter: "flagged", search: "x", selectedId: "fremd", pageScroll: 5 } };
    await mount({}, { name: "Dana", nav });
    expect(pager()).toBe("1 of 3");
    expect(current()).toBe(RULE_DOOR.classification.summary);
    expect(nav.current?.jobId).toBe("j1");
  });

  it("a saved filter that is not offered any more falls back to all rules", async () => {
    const nav: { current: RulesNav | null } = { current: { jobId: "j1", filter: "accepted", search: "", selectedId: null, pageScroll: 0 } };
    await mount({ enabled: false }, { nav }); // no review storage: there is no "Accepted" filter
    expect(pager()).toBe("1 of 3");
  });
});

// ── the ⋯ menu and help ─────────────────────────────────────────────────────────────────────────────────────────────────────

describe("the more-actions menu", () => {
  const trigger = () => q<HTMLButtonElement>('button[aria-label="More actions"]')!;
  const menu = () => q('[role="menu"]');

  it("is a labelled menu button that opens with its first item focused and closes on Escape, returning focus", async () => {
    await mount();
    expect(trigger().getAttribute("aria-haspopup")).toBe("menu");
    expect(trigger().getAttribute("aria-expanded")).toBe("false");
    expect(menu()).toBeNull();
    await click(trigger());
    expect(trigger().getAttribute("aria-expanded")).toBe("true");
    expect(qa('[role="menuitem"]').map((i) => i.textContent)).toEqual(["Restart Extraction"]);
    expect(document.activeElement).toBe(qa('[role="menuitem"]')[0]);
    await key("Escape", document.activeElement!);
    expect(menu()).toBeNull();
    expect(document.activeElement).toBe(trigger());
  });

  it("closes on a click outside, but not on a click inside", async () => {
    await mount();
    await click(trigger());
    await act(async () => { menu()!.dispatchEvent(new Event("pointerdown", { bubbles: true })); });
    expect(menu()).not.toBeNull();
    await act(async () => { q(".rex-card")!.dispatchEvent(new Event("pointerdown", { bubbles: true })); });
    expect(menu()).toBeNull();
  });

  it("closes after the item is used, which asks for the cost confirmation instead of restarting", async () => {
    await mount();
    await click(trigger());
    await click(qa('[role="menuitem"]')[0]);
    expect(menu()).toBeNull();
    expect(q('[role="alertdialog"]')?.textContent).toContain("paid request");
    expect(posts()).toEqual([]);
  });
});

describe("help", () => {
  it("explains the three steps and that unflagged rules are not verified, and closes on Escape", async () => {
    await mount();
    await click(q('button[aria-label="Help"]'));
    const dialog = q('[role="dialog"]')!;
    expect(dialog.textContent).toContain("How reviewing works");
    expect(dialog.textContent).toContain("Rules without that mark are not verified");
    await key("Escape", document.activeElement!);
    expect(q('[role="dialog"]')).toBeNull();
  });
});

describe("reviewer identity", () => {
  it("starts empty: no name is ever supplied for a decision, so none is sent until the reviewer types one", async () => {
    await mount();
    expect(reviewerInput().value).toBe("");
    await click(choice(YES));
    expect(posts()).toEqual([]);
    expect(window.localStorage.getItem("odos.reviewer")).toBeNull();
  });
});
