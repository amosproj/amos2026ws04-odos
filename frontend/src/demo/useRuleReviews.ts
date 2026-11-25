import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { HttpError, getRuleReviews, type RuleReviewEntry, type RuleReviews } from "./live";

/** Where the backend's review storage stands for the rules that are on screen. `unavailable` keeps the Human Review controls
 *  disabled with the backend's explanation (no database, table not created, old backend, not reachable); `ready` enables them.
 *  `stale`: the review state belongs to another extraction than the rules on screen (another run replaced `rules.json`), or the
 *  rules on screen carry no extraction identity; no decision may be made until the current rules are loaded. */
export type ReviewApi =
  | { kind: "loading" }
  | { kind: "unavailable"; reason: string | null }
  | { kind: "stale"; unidentified: boolean }
  | { kind: "ready"; data: RuleReviews };

/** The reason worth showing: the backend's own message about its storage (503) or a conflict, never a generic transport error. */
const reasonOf = (e: unknown): string | null => (e instanceof HttpError && (e.status === 503 || e.status === 409) ? e.message : null);

interface Loaded {
  /** The extraction the rules on screen came from when this was requested. */
  forId: string | null;
  api: ReviewApi;
}

/** Loads the review state of the job's rules. `shownId` is the extraction identity (`_generation.generatedAt`) of the rules on
 *  screen: the state is `ready` only when the backend's state is of that very extraction. Rule IDs alone never tie a decision to a
 *  displayed rule, because a new extraction keeps the IDs. It is reloaded when `shownId` changes. */
export function useRuleReviews(jobId: string | undefined, shownId: string | null) {
  const [loaded, setLoaded] = useState<Loaded>({ forId: shownId, api: jobId ? { kind: "loading" } : { kind: "unavailable", reason: null } });
  const alive = useRef(true);
  const latest = useRef(0); // an older answer never overwrites a newer one
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);

  const reload = useCallback(async () => {
    const n = ++latest.current;
    const settle = (api: ReviewApi) => { if (alive.current && n === latest.current) setLoaded({ forId: shownId, api }); };
    if (!jobId) { settle({ kind: "unavailable", reason: null }); return; }
    try {
      settle({ kind: "ready", data: await getRuleReviews(jobId) });
    } catch (e) {
      settle({ kind: "unavailable", reason: reasonOf(e) });
    }
  }, [jobId, shownId]);

  useEffect(() => { void reload(); }, [reload]);

  // What the page may use: a state requested for other rules than those on screen is not shown (loading), and a state of another
  // extraction than the one on screen is stale. This is derived on every render, so there is no render in which a decision could
  // be made on rules that are not the ones the reviewer is looking at.
  const api = useMemo<ReviewApi>(() => {
    if (loaded.forId !== shownId) return jobId ? { kind: "loading" } : { kind: "unavailable", reason: null };
    if (loaded.api.kind === "ready" && loaded.api.data.extractionId !== shownId) return { kind: "stale", unidentified: shownId === null };
    return loaded.api;
  }, [loaded, shownId, jobId]);

  /** Puts one rule's new entry (the answer to a review action) into the state without a second request. */
  const setEntry = useCallback((ruleId: string, entry: RuleReviewEntry) => {
    setLoaded((cur) => {
      if (cur.api.kind !== "ready") return cur;
      const rules = { ...cur.api.data.rules, [ruleId]: entry };
      const states = Object.values(rules);
      const counts = { pending: states.filter((e) => e.state === "pending").length, accepted: states.filter((e) => e.state === "accepted").length,
                       rejected: states.filter((e) => e.state === "rejected").length, edited: states.filter((e) => e.edited).length };
      const accepted = Object.entries(rules).filter(([, e]) => e.state === "accepted");
      const blockedBy = accepted.filter(([, e]) => e.validity && !e.validity.valid).map(([id]) => id);
      const exportState = { accepted: accepted.length, invalid: states.filter((e) => e.validity && !e.validity.valid).length, blockedBy, ready: accepted.length > 0 && blockedBy.length === 0 };
      return { ...cur, api: { kind: "ready", data: { ...cur.api.data, rules, counts, ...(cur.api.data.export ? { export: exportState } : {}) } } };
    });
  }, []);

  return { api, reload, setEntry };
}

const NAME_KEY = "odos.reviewer";

/** The reviewer's self-declared name, remembered in this browser only (not authenticated, not sent anywhere but with a decision). */
export function useReviewerName(): [string, (name: string) => void] {
  const [name, setName] = useState(() => { try { return window.localStorage.getItem(NAME_KEY) ?? ""; } catch { return ""; } });
  const set = useCallback((value: string) => {
    setName(value);
    try { window.localStorage.setItem(NAME_KEY, value); } catch { /* the name is then only kept for this page */ }
  }, []);
  return [name, set];
}
