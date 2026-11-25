// The review state of a rule as the pages show it, and how rules sharing a source are summarised. The state is the persisted
// decision of the backend's review storage (accepted / rejected, or still pending); "needs review" is only the way a pending rule is
// presented (amber), never a stored status. Without review storage nothing is known and nothing is shown.
import type { DocElement } from "../types";
import { invalidIssues, type RuleItem } from "./ruleResults";

export type ReviewState = "accepted" | "pending" | "rejected";
export interface ReviewMark { state: ReviewState; edited: boolean; /** The record in force is not valid Rule JSON 2.0 (a fact apart from the decision). */ invalid: boolean }

export const STATE_LABEL: Record<ReviewState, string> = { accepted: "Accepted", pending: "Pending", rejected: "Rejected" };

/** The persisted decision of a rule (with the review state applied), or null when the backend keeps none for it. Edited is an
 *  additional attribute: an edited, accepted rule is accepted. */
export function markOf(rule: RuleItem): ReviewMark | null {
  return rule.human ? { state: rule.human, edited: rule.edited, invalid: invalidIssues(rule) !== null } : null;
}

export interface Counts { accepted: number; pending: number; rejected: number; edited: number; invalid: number }
const empty = (): Counts => ({ accepted: 0, pending: 0, rejected: 0, edited: 0, invalid: 0 });
const add = (c: Counts, m: ReviewMark) => { c[m.state] += 1; if (m.edited) c.edited += 1; if (m.invalid) c.invalid += 1; };

/** What the rules say about one element: its own rules (one entry per rule, never merged) and the counts of the rules of the
 *  element and, separately, of everything below it. Two rules on one sentence with different decisions both stay visible. */
export interface ElementMarks {
  rules: Array<{ rule: RuleItem; mark: ReviewMark; sentenceIds: string[]; role: string }>;
  own: Counts;
  below: Counts;
}

export function marksByElement(items: RuleItem[], elements: Map<string, DocElement>): Map<string, ElementMarks> {
  const out = new Map<string, ElementMarks>();
  const at = (id: string) => { let m = out.get(id); if (!m) { m = { rules: [], own: empty(), below: empty() }; out.set(id, m); } return m; };
  for (const rule of items) {
    const mark = markOf(rule);
    if (!mark) continue;
    const seen = new Set<string>();
    for (const s of rule.sources) {
      if (!elements.has(s.elementId)) continue;
      const m = at(s.elementId);
      const same = m.rules.find((r) => r.rule.id === rule.id);
      if (same) { if (s.sentenceId && !same.sentenceIds.includes(s.sentenceId)) same.sentenceIds.push(s.sentenceId); continue; }
      m.rules.push({ rule, mark, sentenceIds: s.sentenceId ? [s.sentenceId] : [], role: s.role ?? "primary" });
      add(m.own, mark);
      // everything above gets the rule once in its `below` counts
      for (let p = elements.get(s.elementId)?.parent_id; p; p = elements.get(p)?.parent_id) {
        if (seen.has(p)) continue;
        seen.add(p);
        add(at(p).below, mark);
      }
    }
  }
  return out;
}
