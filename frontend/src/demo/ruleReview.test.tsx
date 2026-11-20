// @vitest-environment jsdom
// Human Review on the Rule Extraction page against a faked backend that keeps decisions like the real one does
// (events with a last-event ID, validation answers 409/422). Fixtures: ruleTestData.ts (test-only).
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RuleExtractionView, type RulesNav } from "./RuleExtraction";
import type { RuleHistoryEvent, RuleReviewEntry } from "./live";
import { RULE_DOOR, RULE_FIRE, STORED, demoResult, generation, rulesFile, status } from "./ruleTestData";

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
const q = <T extends Element = HTMLElement>(sel: string) => host.querySelector<T>(sel);
const qa = <T extends Element = HTMLElement>(sel: string) => [...host.querySelectorAll<T>(sel)];
const button = (name: string | RegExp) => qa<HTMLButtonElement>("button").find((b) => { const t = (b.textContent ?? "").trim(); return typeof name === "string" ? t === name : name.test(t); });
const click = async (target: Element | null | undefined) => { if (!target) throw new Error("nothing to click"); await act(async () => { (target as HTMLElement).click(); }); await flush(); };
const fill = async (el: HTMLInputElement | HTMLTextAreaElement, value: string) => {
  const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  await act(async () => { Object.getOwnPropertyDescriptor(proto, "value")!.set!.call(el, value); el.dispatchEvent(new Event("input", { bubbles: true })); });
  await flush();
};
const reviewerInput = () => q<HTMLInputElement>('.rex-review input[type="text"]')!;

beforeEach(() => { vi.useFakeTimers(); Element.prototype.scrollIntoView = () => {}; window.scrollTo = () => {}; });
afterEach(() => { close(); vi.useRealTimers(); vi.unstubAllGlobals(); });

describe("without review storage", () => {
  it("keeps Accept, Reject and Edit disabled and passes on the backend's reason", async () => {
    await mount({ enabled: false });
    for (const name of ["Accept Rule", "Reject", "Edit JSON"]) expect(button(new RegExp(`^${name}$`))?.disabled, name).toBe(true);
    expect(q(".rex-detail")?.textContent).toContain("Review decisions cannot be saved right now");
    expect(q(".rex-detail")?.textContent).toContain("002_rule_reviews.sql");
    expect(q('[aria-label="Human review"].rex-group')?.textContent).toContain("Review decisions are not stored yet");
    expect(button(/Download approved rules/)).toBeUndefined();
    expect(posts()).toEqual([]);
  });
});

describe("with review storage", () => {
  it("shows real counts, enables the controls and offers the approved export only once something is accepted", async () => {
    await mount();
    const group = q('[aria-label="Human review"].rex-group')!;
    expect([...group.querySelectorAll(".rex-stat")].map((s) => [s.querySelector(".rex-stat-label")?.textContent, s.querySelector(".rex-stat-value")?.textContent]))
      .toEqual([["Pending Review", "3"], ["Accepted", "0"], ["Rejected", "0"], ["Edited", "0"]]);
    expect(group.textContent).toContain("The extracted rules are never changed");
    expect(button("Accept Rule")?.disabled).toBe(false);
    expect(button(/Download approved rules/)?.disabled).toBe(true);
    expect(qa(".rex-tabs button").map((b) => b.textContent)).toEqual(["All Rules (3)", "Pending Review (3)", "Accepted (0)", "Rejected (0)", "Flagged by Checks (1)"]);
  });

  it("needs a reviewer name before it sends anything, and remembers the name in this browser", async () => {
    await mount();
    await click(button("Accept Rule"));
    expect(q('.rex-review [role="alert"]')?.textContent).toContain("Enter your reviewer name first");
    expect(posts()).toEqual([]);
    await fill(reviewerInput(), "Dana Prüfer");
    expect(window.localStorage.getItem("odos.reviewer")).toBe("Dana Prüfer");
  });

  it("accepts a rule with the exact identifiers the backend gave, updates the chip, the counts and the filter", async () => {
    await mount({}, { name: "Dana Prüfer" });
    await click(button("Accept Rule"));
    expect(fake.bodies).toEqual([{ ruleId: "tuer-breite", extractionId: EXTRACTION, expectedRuleSha256: sha(RULE_DOOR), expectedLastEventId: 0, action: "accept", reviewer: "Dana Prüfer" }]);
    expect(q(".rex-review-state")?.textContent).toContain("Accepted by Dana Prüfer");
    expect(qa(".rex-rule .rex-status")[0].textContent).toBe("Accepted");
    expect(button("Accept Rule")?.disabled).toBe(true); // already accepted
    expect(qa(".rex-tabs button").map((b) => b.textContent)).toContain("Accepted (1)");
    expect(button(/Download approved rules/)?.textContent).toContain("Download approved rules (1)");
    expect(button(/Download approved rules/)?.disabled).toBe(false);
    await click(button(/^Accepted \(1\)/));
    expect(qa(".rex-rule-id").map((t) => t.textContent)).toEqual(["tuer-breite"]);
  });

  it("sends one event even when clicked twice", async () => {
    await mount({}, { name: "Dana" });
    const accept = button("Accept Rule")!;
    await act(async () => { accept.click(); accept.click(); });
    await flush();
    expect(posts()).toHaveLength(1);
  });

  it("rejects only with a reason and keeps the rejected rule listed and counted", async () => {
    await mount({}, { name: "Dana" });
    await click(button("Reject"));
    const confirm = button("Confirm rejection")!;
    expect(confirm.disabled).toBe(true);
    await fill(q<HTMLTextAreaElement>(".rex-form textarea")!, "Wrong threshold");
    await click(button("Confirm rejection"));
    expect(fake.bodies[0]).toMatchObject({ action: "reject", reason: "Wrong threshold" });
    expect(qa(".rex-rule .rex-status")[0].textContent).toBe("Rejected");
    expect(qa(".rex-rule")).toHaveLength(3);
    expect(q('[aria-label="Human review"].rex-group')?.textContent).toMatch(/1Rejected/);
    expect(q(".rex-review")?.textContent).toContain("Reason: Wrong threshold");
  });

  it("edits a rule: validates the JSON locally, stores the edit beside the original and returns the rule to pending", async () => {
    await mount({}, { name: "Dana" });
    await click(button("Edit JSON"));
    const editor = q<HTMLTextAreaElement>(".rex-editor")!;
    expect(JSON.parse(editor.value)).toEqual(RULE_DOOR); // starts from the rule in force
    await fill(editor, "{ not json");
    await click(button("Save edit"));
    expect(q('.rex-review [role="alert"]')?.textContent).toContain("not valid JSON");
    await fill(editor, "[1]");
    await click(button("Save edit"));
    expect(q('.rex-review [role="alert"]')?.textContent).toContain("must be a JSON object");
    expect(posts()).toEqual([]);

    const edited = { ...RULE_DOOR, classification: { ...RULE_DOOR.classification, summary: "Türen: mindestens 1,00 m." } };
    await fill(editor, JSON.stringify(edited));
    await click(button("Save edit"));
    expect(fake.bodies[0]).toMatchObject({ action: "edit", editedRule: edited });
    expect(qa(".rex-rule .rex-status").map((s) => s.textContent).slice(0, 2)).toEqual(["Pending Review", "Edited"]);
    expect(q(".rex-detail-title strong")?.textContent).toBe("Türen: mindestens 1,00 m.");
    expect(JSON.parse(q(".jsonv-code")!.textContent!)).toEqual(edited);
    await click(button("Extracted (original)")); // the extracted record is untouched and still viewable
    expect(JSON.parse(q(".jsonv-code")!.textContent!)).toEqual(RULE_DOOR);
    expect(q(".jsonv-label")?.textContent).toContain("Extracted Rule JSON");
    expect(q('[aria-label="Human review"].rex-group')?.textContent).toMatch(/1Edited/);
  });

  it("shows the backend's validation message for an invalid edit and keeps the editor open", async () => {
    await mount({}, { name: "Dana" });
    await click(button("Edit JSON"));
    fake.fail = { status: 422, detail: "The edited rule is not valid Rule JSON 2.0: classification: 'classification' is a required property" };
    await click(button("Save edit"));
    expect(q('.rex-review [role="alert"]')?.textContent).toContain("is a required property");
    expect(q(".rex-editor")).not.toBeNull();
    expect(qa(".rex-rule .rex-status")[0].textContent).toBe("Pending Review");
  });

  it("resets an edit", async () => {
    await mount({}, { name: "Dana" });
    await click(button("Edit JSON"));
    await click(button("Save edit"));
    expect(button("Reset edit")).not.toBeUndefined();
    await click(button("Reset edit"));
    expect(fake.bodies.map((b) => b.action)).toEqual(["edit", "reset"]);
    expect(button("Reset edit")).toBeUndefined();
    expect(qa(".rex-rule .rex-status").map((s) => s.textContent)).not.toContain("Edited");
  });

  it("on a conflict says so and reloads the current state instead of applying anything", async () => {
    await mount({}, { name: "Dana" });
    fake.entries["tuer-breite"] = { ...fake.entries["tuer-breite"], state: "rejected", lastEventId: 7, reviewer: "Alex", reason: "no" }; // somebody else decided
    const before = fake.calls.filter((c) => c.startsWith("GET") && c.endsWith("/rule-reviews")).length;
    await click(button("Accept Rule"));
    expect(q('.rex-review [role="alert"]')?.textContent).toContain("Someone else changed this rule's review");
    expect(fake.calls.filter((c) => c.startsWith("GET") && c.endsWith("/rule-reviews")).length).toBe(before + 1);
    expect(qa(".rex-rule .rex-status")[0].textContent).toBe("Rejected"); // the other reviewer's decision is now shown
  });

  it("lists the audit trail of the selected rule", async () => {
    await mount({}, { name: "Dana" });
    await click(button("Accept Rule"));
    await click(button("Reject"));
    await fill(q<HTMLTextAreaElement>(".rex-form textarea")!, "On second thought");
    await click(button("Confirm rejection"));
    const details = q<HTMLDetailsElement>(".rex-audit")!;
    await act(async () => { details.open = true; details.dispatchEvent(new Event("toggle")); });
    await flush();
    expect(qa(".rex-audit-list li").map((li) => li.textContent)).toEqual([expect.stringContaining("Accepted by Dana"), expect.stringContaining("Rejected by Dana — On second thought")]);
    await click(qa(".rex-rule")[1]); // another rule has no events
    await act(async () => { q<HTMLDetailsElement>(".rex-audit")!.open = true; q(".rex-audit")!.dispatchEvent(new Event("toggle")); });
    await flush();
    expect(q(".rex-audit")?.textContent).toContain("No review events yet");
  });

  it("notes decisions that belong to earlier extractions and are not applied", async () => {
    await mount({ earlier: 4 });
    expect(q('[aria-label="Human review"].rex-group')?.textContent).toContain("4 decision events from earlier extractions are kept in the history and not applied to these rules.");
  });

  it("keeps the flagged verdict apart from the human decision", async () => {
    await mount({}, { name: "Dana" });
    expect(qa(".rex-rule .rex-status").map((s) => s.textContent)).toEqual(["Pending Review", "Flagged", "Pending Review", "Pending Review"]);
    await click(button("Accept Rule")); // accepting a flagged rule does not clear its flag
    expect(qa(".rex-rule .rex-status").map((s) => s.textContent).slice(0, 2)).toEqual(["Accepted", "Flagged"]);
    expect(q(".rex-reviewinfo")?.textContent).toContain("Flagged by ODOS checks");
    void RULE_FIRE;
  });
});

// ── extraction identity (H1): a decision is only ever made on the rules of the extraction the reviewer is looking at ──────────

const stateOf = (state: RuleReviewEntry["state"] = "pending", lastEventId = 0): Record<string, RuleReviewEntry> =>
  Object.fromEntries((STORED.rules as Array<{ id: string }>).map((r) => [r.id, { ruleSha256: sha(r), state, edited: false, verification: "unverified" as const, lastEventId,
    reviewer: state === "pending" ? null : "Alex", reason: null, at: state === "pending" ? null : "2026-11-21T09:00:00+00:00", effectiveRule: null }]));
const chips = () => qa(".rex-rule > .rex-chips .rex-status:first-child, .rex-rule .rex-chips > .rex-status:first-child").map((c) => c.textContent);
const disabledAll = () => ["Accept Rule", "Reject", "Edit JSON"].every((n) => button(new RegExp(`^${n}$`))?.disabled === true);

describe("extraction identity", () => {
  it("two tabs: after another extraction replaced the rules, nothing displayed can be decided, and reloading shows consistent rules and decisions", async () => {
    await mount({}, { name: "Dana" });
    // tab B ran a new extraction (same rule IDs, new identity); somebody already accepted a rule of it
    fake.extraction = NEWER;
    fake.file = NEWER_FILE;
    fake.entries = stateOf("accepted", 5);
    fake.entries["brandabschnitt"] = { ...fake.entries["brandabschnitt"], state: "pending", lastEventId: 0, reviewer: null, at: null };

    await click(button("Accept Rule")); // tab A still shows the old extraction: the backend refuses it (409) ...
    expect(posts()).toHaveLength(1);
    expect(fake.bodies[0]).toMatchObject({ extractionId: EXTRACTION });
    // ... and the page now knows the review state belongs to another extraction
    expect(q(".rex-stale")?.textContent).toContain("The extraction has changed");
    expect(disabledAll()).toBe(true);
    expect(chips()).not.toContain("Accepted"); // the other extraction's decisions are not applied to the displayed rules by ID
    expect(qa(".rex-tabs button").map((b) => b.textContent?.replace(/ \(\d+\)/, ""))).toEqual(["All Rules", "Pending Review", "Flagged by Checks", "Reviewed"]); // no Accepted / Rejected filters
    expect(button(/Download approved rules/)).toBeUndefined();
    for (const name of ["Accept Rule", "Reject", "Edit JSON"]) await click(button(new RegExp(`^${name}$`)));
    expect(posts()).toHaveLength(1); // disabled buttons send nothing

    const rulesGets = () => fake.calls.filter((c) => c === "GET /api/jobs/j1/files/rules.json").length;
    const before = rulesGets();
    await click(button("Reload results"));
    expect(rulesGets()).toBe(before + 1); // the current rules.json, then the review state of those very rules
    expect(q(".rex-stale")).toBeNull();
    expect(chips()).toContain("Accepted"); // Alex's decision on the new extraction, now on the new rules
    // a decision made now carries the new identity
    await click(qa(".rex-rule")[1]);
    await click(button("Accept Rule"));
    expect(fake.bodies[1]).toMatchObject({ extractionId: NEWER, ruleId: "brandabschnitt" });
    expect(posts()).toHaveLength(2);
  });

  it("the same extraction is not stale: identical identity means decisions are applied and possible", async () => {
    await mount({}, { name: "Dana" });
    expect(q(".rex-stale")).toBeNull();
    expect(button("Accept Rule")?.disabled).toBe(false);
  });

  it("review state of another extraction than the displayed rules: controls are disabled at once and no decision of it is shown", async () => {
    await mount({ extraction: NEWER, entries: stateOf("rejected", 9) });
    expect(q(".rex-stale")?.textContent).toContain("The extraction has changed");
    expect(q(".rex-detail")?.textContent).toContain("not the current extraction");
    expect(disabledAll()).toBe(true);
    expect(chips()).not.toContain("Rejected");
    expect(q('[aria-label="Human review"].rex-group')?.textContent).toContain("belong to a newer extraction");
    expect(posts()).toEqual([]);
  });

  it("rules without an extraction identifier cannot be reviewed", async () => {
    const bare = { rules: STORED.rules }; // no _generation.generatedAt
    await mount({ file: bare });
    expect(disabledAll()).toBe(true);
    expect(q(".rex-detail")?.textContent).toContain("carry no extraction identifier");
    expect(button("Reload results")).toBeUndefined(); // reloading would not help
    expect(posts()).toEqual([]);
  });

  it("a review action cannot be started while the review state is still loading", async () => {
    let release!: () => void;
    await mount({ reviewsGate: new Promise<void>((r) => { release = r; }) });
    expect(disabledAll()).toBe(true);
    expect(q(".rex-detail")?.textContent).toContain("Loading the review state");
    await act(async () => { release(); });
    await flush();
    expect(button("Accept Rule")?.disabled).toBe(false);
    expect(posts()).toEqual([]);
  });

  it("a backend that cannot be reached leaves the controls disabled and sends nothing", async () => {
    await mount({ unreachable: true });
    expect(disabledAll()).toBe(true);
    expect(q(".rex-detail")?.textContent).toContain("Review decisions cannot be saved right now");
    expect(q(".rex-detail")?.textContent).toContain("This rule stays “Pending Review”");
    expect(posts()).toEqual([]);
  });

  it("a record that changed under the same page is refused by the backend and the fresh state is shown", async () => {
    await mount({}, { name: "Dana" });
    fake.entries["tuer-breite"] = { ...fake.entries["tuer-breite"], ruleSha256: "b".repeat(64) };
    fake.fail = { status: 409, detail: "The rules of this job changed since they were loaded. Reload the page." };
    await click(button("Accept Rule"));
    expect(q('.rex-review [role="alert"]')?.textContent).toContain("changed since they were loaded");
    expect(qa(".rex-rule .rex-status")[0].textContent).toBe("Pending Review"); // nothing was applied
  });
});

// ── audit trail across extractions (M1) ──────────────────────────────────────────────────────────────────────────────────────

const openAudit = async () => {
  await act(async () => { const d = q<HTMLDetailsElement>(".rex-audit")!; d.open = true; d.dispatchEvent(new Event("toggle")); });
  await flush();
};
const earlierEvent = (over: Partial<RuleHistoryEvent> = {}): RuleHistoryEvent => ({ id: 3, extractionId: "2026-11-01T08:00:00+00:00", action: "accept", decision: "accepted", reviewer: "Alex",
  reason: null, at: "2026-11-01T09:00:00+00:00", edited: false, ruleSha256: sha(RULE_DOOR), ...over });

describe("audit trail across extractions", () => {
  it("lists events of earlier extractions apart, labelled as history that does not apply to these rules", async () => {
    await mount({ events: [earlierEvent()], earlier: 1 }, { name: "Dana" });
    expect(q(".rex-review-state")?.textContent).toContain("Pending review"); // the earlier acceptance is not carried over
    await openAudit();
    const current = qa('.rex-audit-list[aria-label="Events of this extraction"] li');
    const earlier = qa(".rex-audit-earlier li");
    expect(current).toHaveLength(0);
    expect(q(".rex-audit")?.textContent).toContain("No review events yet for these rules");
    expect(q(".rex-audit-earlier-h")?.textContent).toContain("history only, not applied to these rules");
    expect(earlier).toHaveLength(1);
    expect(earlier[0].textContent).toContain("Accepted by Alex");
    expect(earlier[0].textContent).toContain("earlier extraction");
  });

  it("keeps the current extraction's events and the earlier ones in separate lists", async () => {
    await mount({ events: [earlierEvent()], nextId: 10 }, { name: "Dana" });
    await click(button("Accept Rule"));
    await openAudit();
    const current = qa('.rex-audit-list[aria-label="Events of this extraction"] li').map((li) => li.textContent);
    expect(current).toHaveLength(1);
    expect(current[0]).toContain("Accepted by Dana");
    expect(current[0]).not.toContain("earlier extraction");
    expect(qa(".rex-audit-earlier li")).toHaveLength(1);
    expect(q(".rex-review-state")?.textContent).toContain("Accepted by Dana"); // the state comes from the current extraction's event only
  });
});

describe("small review form fixes", () => {
  it("L1: the reason typed for a rejection is not carried into an edit", async () => {
    await mount({}, { name: "Dana" });
    await click(button("Reject"));
    await fill(q<HTMLTextAreaElement>(".rex-form textarea")!, "Wrong threshold");
    await click(button("Cancel"));
    await click(button("Edit JSON"));
    expect(q<HTMLInputElement>('.rex-form input[type="text"]')!.value).toBe("");
    await click(button("Save edit"));
    expect(fake.bodies[0]).toMatchObject({ action: "edit" });
    expect(fake.bodies[0]).not.toHaveProperty("reason");
  });

  it("L2: a slow audit trail of the previous rule never shows under the selected one", async () => {
    let release!: () => void;
    await mount({ events: [earlierEvent({ extractionId: EXTRACTION, reviewer: "Previous" })], historyGate: { "tuer-breite": new Promise<void>((r) => { release = r; }) } }, { name: "Dana" });
    await openAudit(); // asks for tuer-breite, which is still on its way
    await click(qa(".rex-rule")[1]); // another rule is selected meanwhile
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
    await click(button("Accept Rule"));
    await click(button(/Download approved rules/));
    expect(fake.calls).toContain("GET /api/jobs/j1/rule-reviews/approved-export?download=true");
    expect(created).toHaveLength(1);
    expect(saved).toEqual([{ name: "MusterBauVerordnung.approved.rules.json", href: "blob:approved" }]);
    expect(q('[role="alert"]')).toBeNull();
  });

  it("does not save anything when the backend answers with an error, and says why", async () => {
    await mount({ exportFail: { status: 409, detail: "A rule extraction of this job is running; rules can be reviewed when it has finished." } }, { name: "Dana" });
    await click(button("Accept Rule"));
    await click(button(/Download approved rules/));
    expect(created).toHaveLength(0);
    expect(saved).toEqual([]);
    expect(q('.rex-results > [role="alert"]')?.textContent).toContain("The approved rules were not downloaded: A rule extraction of this job is running");
  });

  it("does not save an error when the backend cannot be reached", async () => {
    await mount({}, { name: "Dana" });
    await click(button("Accept Rule"));
    fake.unreachable = true;
    await click(button(/Download approved rules/));
    expect(created).toHaveLength(0);
    expect(q('.rex-results > [role="alert"]')?.textContent).toContain("not reachable");
  });
});

// ── navigation state across "Show in PDF" (M3) ───────────────────────────────────────────────────────────────────────────────

describe("navigation state", () => {
  it("restores the selected rule, filter, search, detail tab and list position when the page is opened again, without new extraction requests", async () => {
    const nav: { current: RulesNav | null } = { current: null };
    await mount({}, { name: "Dana", nav });
    await click(button(/^Pending Review \(/));
    await fill(q<HTMLInputElement>('input[type="search"]')!, "brand");
    await click(qa(".rex-rule")[0]); // the only match: brandabschnitt
    await click(qa('[role="tab"]').find((t) => t.textContent === "Source Text"));
    const list = q(".rex-list")!;
    list.scrollTop = 120;
    await act(async () => { list.dispatchEvent(new Event("scroll")); });
    expect(nav.current).toMatchObject({ jobId: "j1", filter: "pending", search: "brand", selectedId: "brandabschnitt", tab: "source", listScroll: 120 });

    close(); // "Show in PDF" leaves the page ...
    const callsBefore = fake.calls.length;
    await open(nav); // ... and "Continue to Rule Extraction" opens it again
    expect(q<HTMLInputElement>('input[type="search"]')!.value).toBe("brand");
    expect(qa(".rex-tabs button").find((b) => b.getAttribute("aria-pressed") === "true")?.textContent).toContain("Pending Review");
    expect(q(".rex-rule.selected .rex-rule-id")?.textContent).toBe("brandabschnitt");
    expect(q('[role="tab"][aria-selected="true"]')?.textContent).toBe("Source Text");
    expect(q(".rex-list")!.scrollTop).toBe(120);
    const again = fake.calls.slice(callsBefore);
    expect(again.filter((c) => c.startsWith("POST"))).toEqual([]); // nothing was started
    expect(again.filter((c) => c.endsWith("/files/rules.json"))).toEqual([]); // the rules in hand are not fetched again
  });

  it("starts clean for another document", async () => {
    const nav: { current: RulesNav | null } = { current: { jobId: "other", filter: "flagged", search: "x", selectedId: "fremd", tab: "source", listScroll: 5, pageScroll: 5 } };
    await mount({}, { name: "Dana", nav });
    expect(q<HTMLInputElement>('input[type="search"]')!.value).toBe("");
    expect(q(".rex-rule.selected .rex-rule-id")?.textContent).toBe("tuer-breite");
    expect(nav.current?.jobId).toBe("j1");
  });

  it("a saved filter that is not offered any more falls back to all rules", async () => {
    const nav: { current: RulesNav | null } = { current: { jobId: "j1", filter: "accepted", search: "", selectedId: null, tab: "json", listScroll: 0, pageScroll: 0 } };
    await mount({ enabled: false }, { nav }); // no review storage: there is no "Accepted" filter
    expect(qa(".rex-rule")).toHaveLength(3);
  });
});
