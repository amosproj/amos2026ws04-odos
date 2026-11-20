// The rule-extraction client (live.ts) and the mapping of a stored rules.json (ruleResults.ts), without any UI.
import { afterEach, describe, expect, it, vi } from "vitest";
import { type RuleReviewEntry, EXTRACTION_TIMEOUT_MS, ExtractionWaitError, HttpError, getRuleExtraction, loadRules, startRuleExtraction, watchRuleExtraction, type RuleExtractionStatus } from "./live";
import { CHECK_FLAG_PREFIX, applyReview, generatedAt, matchesFilter, matchesSearch, overviewOf, pagesLabel, toRuleResults, validPages } from "./ruleResults";
import { RULE_DOOR, RULE_FIRE, RULE_FOREIGN, STORED, rule, rulesFile, status } from "./ruleTestData";

const json = (body: unknown, code = 200) => new Response(JSON.stringify(body), { status: code, headers: { "Content-Type": "application/json" } });
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("rule extraction client", () => {
  it("starts with POST, reads the status and the stored rules with GET, and treats 404 as 'none'", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(json(status("queued"), 202))
      .mockResolvedValueOnce(json({ detail: "none" }, 404))
      .mockResolvedValueOnce(json({ detail: "none" }, 404))
      .mockResolvedValueOnce(json(STORED));
    vi.stubGlobal("fetch", fetchMock);
    expect((await startRuleExtraction("j1")).status).toBe("queued");
    expect(await getRuleExtraction("j1")).toBeNull();
    expect(await loadRules("j1")).toBeNull();
    expect(await loadRules("j1")).toEqual(STORED);
    expect(fetchMock.mock.calls.map(([url, init]) => `${init?.method ?? "GET"} ${url}`)).toEqual([
      "POST /api/jobs/j1/rule-extraction", "GET /api/jobs/j1/rule-extraction", "GET /api/jobs/j1/files/rules.json", "GET /api/jobs/j1/files/rules.json",
    ]);
  });

  it("keeps the HTTP status and the backend's explanation of a refusal", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ detail: "A rule extraction of this job is already queued or running." }, 409)));
    const error = await startRuleExtraction("j1").catch((e) => e);
    expect(error).toBeInstanceOf(HttpError);
    expect(error.status).toBe(409);
    expect(error.message).toBe("A rule extraction of this job is already queued or running.");
  });

  it("watches until the backend reports a final status and passes every status on", async () => {
    vi.useFakeTimers();
    const seen: RuleExtractionStatus[] = [status("queued"), status("running"), status("running"), status("completed")];
    vi.stubGlobal("fetch", vi.fn(async () => json(seen.shift())));
    const onStatus = vi.fn();
    const done = watchRuleExtraction("j1", onStatus, { intervalMs: 1000 });
    await vi.advanceTimersByTimeAsync(3000);
    expect((await done)?.status).toBe("completed");
    expect(onStatus.mock.calls.map(([s]) => s.status)).toEqual(["queued", "running", "running", "completed"]);
  });

  it("gives up with a timeout error after the allowed time while the extraction goes on", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn(async () => json(status("running"))));
    const result = watchRuleExtraction("j1", () => {}, { intervalMs: 1000, timeoutMs: 5000 }).catch((e) => e);
    await vi.advanceTimersByTimeAsync(6000);
    const error = await result;
    expect(error).toBeInstanceOf(ExtractionWaitError);
    expect(error.kind).toBe("timeout");
    expect(EXTRACTION_TIMEOUT_MS).toBeGreaterThan(10 * 60 * 1000); // longer than one Bedrock attempt may take
  });

  it("reports a lost connection only after repeated failures, and recovers from a single one", async () => {
    vi.useFakeTimers();
    const answers: Array<"down" | RuleExtractionStatus> = ["down", status("running"), "down", "down", "down"];
    vi.stubGlobal("fetch", vi.fn(async () => { const a = answers.shift(); if (a === "down" || !a) throw new TypeError("offline"); return json(a); }));
    const result = watchRuleExtraction("j1", () => {}, { intervalMs: 1000 }).catch((e) => e);
    await vi.advanceTimersByTimeAsync(10000);
    const error = await result;
    expect(error).toBeInstanceOf(ExtractionWaitError);
    expect(error.kind).toBe("connection");
  });

  it("stops quietly when the caller leaves", async () => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn(async () => json(status("running"))));
    const ctrl = new AbortController();
    const result = watchRuleExtraction("j1", () => {}, { signal: ctrl.signal, intervalMs: 1000 });
    await vi.advanceTimersByTimeAsync(1500);
    ctrl.abort();
    await vi.advanceTimersByTimeAsync(1000);
    expect((await result)?.status).toBe("running");
  });
});

describe("mapping a stored rules.json", () => {
  it("keeps each record unchanged and derives only what the record states", () => {
    const r = toRuleResults(STORED)!;
    expect(r.items.map((i) => i.rule)).toEqual([RULE_DOOR, RULE_FIRE, RULE_FOREIGN]);
    const door = r.items[0];
    expect(door).toMatchObject({ id: "tuer-breite", title: RULE_DOOR.classification.summary, citation: "§ 1 tuer-breite", type: "obligation", reviewStatus: "draft", machineCheckable: true });
    expect(door.checkFlags).toEqual(["unit of 'tuer.lichte_breite' is not stated in the source text"]);
    expect(door.ambiguities).toEqual(["Der Begriff 'Tür' ist nicht definiert."]);
    expect(door.sources).toEqual([{ elementId: "doc/par-1/abs-1", sentenceId: "doc/par-1/abs-1/satz-1", role: "primary", pdfPages: [3] }]);
    expect(CHECK_FLAG_PREFIX).toBe("ODOS check: "); // the backend's FLAG_PREFIX (backend/src/odos/llm/rule_checks.py)
    expect(r.generation).toMatchObject({ modelId: "eu.anthropic.claude-sonnet-4-6", promptVersion: "3", proposed: 4 });
  });

  it("returns null without a file, accepts a bare array, and old files without counts", () => {
    expect(toRuleResults(null)).toBeNull();
    expect(toRuleResults([RULE_FIRE])!.items).toHaveLength(1);
    expect(toRuleResults(rulesFile([RULE_FIRE], { rulesProposed: 7 }))!.generation?.proposed).toBe(7);
  });

  it("counts only well-defined review statuses", () => {
    const approved = rule("a", "A", "doc/par-1/abs-1", { status: "approved" });
    const r = toRuleResults(rulesFile([RULE_DOOR, RULE_FIRE, RULE_FOREIGN, approved]))!;
    expect(overviewOf(r)).toEqual({ total: 4, pending: 2, reviewed: 1, approved: 1, accepted: 0, rejected: 0, edited: 0, flagged: 1, autoRejected: 1 });
  });

  it("filters and searches", () => {
    const [door, fire, foreign] = toRuleResults(STORED)!.items;
    expect([door, fire, foreign].map((i) => matchesFilter(i, "pending"))).toEqual([true, true, false]);
    expect([door, fire, foreign].map((i) => matchesFilter(i, "flagged"))).toEqual([true, false, false]);
    expect(matchesSearch(fire, "  BRAND ")).toBe(true);
    expect(matchesSearch(fire, "tür")).toBe(false);
    expect(matchesSearch(door, "obligation")).toBe(true);
  });

  it("identifies an extraction by its generation time", () => {
    expect(generatedAt(STORED)).toBe("2026-11-18T19:19:20+00:00");
    expect(generatedAt([RULE_FIRE])).toBeNull();
    expect(generatedAt(null)).toBeNull();
  });
});

describe("generation facts and page helpers", () => {
  it("reads the coverage and repair counts the backend stored, and leaves out what it did not", () => {
    expect(toRuleResults(STORED)!.generation).toMatchObject({ repaired: 0, coverage: { sentences: 10, sentencesCited: 8, elements: 5, elementsCited: 5 } });
    const old = toRuleResults(rulesFile([RULE_FIRE], { modelId: "m", rulesProposed: 1 }))!.generation!;
    expect(old.coverage).toBeUndefined();
    expect(old.repaired).toBeUndefined();
    expect(toRuleResults(rulesFile([RULE_FIRE], { coverage: { sentences: "10" } }))!.generation!.coverage).toBeUndefined();
    expect(toRuleResults(rulesFile([RULE_FIRE], { schemaRepairs: [{}, {}] }))!.generation!.repaired).toBe(2);
  });

  it("keeps only page numbers that can be pages of the document", () => {
    expect(validPages([1, 9, 10, 11, 0, -2, 3.5, 83], 10)).toEqual([1, 9, 10]);
    expect(validPages([], 5)).toEqual([]);
  });

  it("writes page numbers as a person reads them", () => {
    expect(pagesLabel([])).toBe("");
    expect(pagesLabel([9])).toBe("p. 9");
    expect(pagesLabel([10, 9])).toBe("p. 9–10");
    expect(pagesLabel([3, 7])).toBe("pp. 3, 7");
    expect(pagesLabel([4, 4, 5])).toBe("p. 4–5");
  });
});

describe("applying the reviewers' decisions", () => {
  const entry = (over: Partial<RuleReviewEntry> = {}): RuleReviewEntry => ({
    ruleSha256: "a".repeat(64), state: "pending", edited: false, verification: "unverified", lastEventId: 0, reviewer: null, reason: null, at: null, effectiveRule: null, ...over,
  });

  it("leaves the item as extracted without a review entry", () => {
    const [door] = toRuleResults(STORED)!.items;
    expect(applyReview(door, undefined)).toBe(door);
    expect(door.human).toBeNull();
  });

  it("takes the decision and keeps the extracted record, the sources and the citation", () => {
    const [door] = toRuleResults(STORED)!.items;
    const decided = applyReview(door, entry({ state: "accepted", reviewer: "Dana" }));
    expect(decided).toMatchObject({ human: "accepted", edited: false, id: "tuer-breite", citation: door.citation });
    expect(decided.rule).toBe(door.rule);
    expect(decided.sources).toEqual(door.sources);
    expect(decided.effective).toBe(door.rule);
  });

  it("shows the edited record in force with its own notes, while the extracted record stays", () => {
    const [door] = toRuleResults(STORED)!.items;
    const fixed = { ...RULE_DOOR, classification: { ...RULE_DOOR.classification, summary: "Neu formuliert." }, review: { ...RULE_DOOR.review, ambiguities: [] } };
    const edited = applyReview(door, entry({ edited: true, effectiveRule: fixed, verification: "unverified" }));
    expect(edited).toMatchObject({ title: "Neu formuliert.", edited: true, checkFlags: [], human: "pending" });
    expect(edited.rule).toBe(door.rule);
    expect(edited.effective).toBe(fixed);
    expect(door.checkFlags).toHaveLength(1); // the extracted record is still flagged
  });

  it("counts and filters by the reviewers' decisions once there are some", () => {
    const items = toRuleResults(STORED)!.items;
    const [a, b, c] = [applyReview(items[0], entry({ state: "accepted" })), applyReview(items[1], entry({ state: "rejected" })), applyReview(items[2], entry({ edited: true, effectiveRule: items[2].rule }))];
    expect(overviewOf({ ...toRuleResults(STORED)!, items: [a, b, c] })).toMatchObject({ pending: 1, accepted: 1, rejected: 1, edited: 1, reviewed: 0, approved: 0 });
    expect([a, b, c].map((i) => matchesFilter(i, "accepted"))).toEqual([true, false, false]);
    expect([a, b, c].map((i) => matchesFilter(i, "rejected"))).toEqual([false, true, false]);
    expect([a, b, c].map((i) => matchesFilter(i, "pending"))).toEqual([false, false, true]);
    expect(matchesFilter(c, "reviewed")).toBe(false); // the file's own "reviewed" status is not used once decisions are stored
  });
});
