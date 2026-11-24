import { Fragment, type RefObject } from "react";
import { Icon } from "../components/Icon";
import { type Provision, type QueueOrder, type ReviewFilter, type RuleItem } from "./ruleResults";
import { isReviewed } from "./ruleResults";

export const FILTER_LABEL: Record<ReviewFilter, string> = { all: "All", pending: "Pending", accepted: "Accepted", rejected: "Rejected", flagged: "Potential issues", reviewed: "Reviewed", edited: "Edited" };

/** The reviewer's decision (or, without stored decisions, the status written in the file) as one word. */
export function stateOf(rule: RuleItem): { key: "pending" | "accepted" | "rejected" | "reviewed"; label: string } {
  if (rule.human) return { key: rule.human === "pending" ? "pending" : rule.human, label: ({ pending: "Pending", accepted: "Accepted", rejected: "Rejected" } as const)[rule.human] };
  return isReviewed(rule) ? { key: "reviewed", label: rule.reviewStatus === "approved" ? "Approved" : "Reviewed" } : { key: "pending", label: "Pending" };
}

/** Status of one rule: the decision as a labelled dot, plus "Edited" and "Flagged" when they apply. Not colour alone: every state has a text. */
export function RuleStatus({ rule, compact = false }: { rule: RuleItem; compact?: boolean }) {
  const { key, label } = stateOf(rule);
  return (
    <span className="rex-chips">
      <span className={`rex-state ${key}`} title={label}>
        <span className="rex-dot" aria-hidden="true" />
        <span className={compact ? "sr-only" : undefined}>{label}</span>
      </span>
      {rule.edited && <span className="rex-tag edited" title="A reviewer edited this rule; the extracted record is kept unchanged">Edited</span>}
      {rule.checkFlags.length > 0 && <span className="rex-tag flag" title="ODOS's automatic checks noticed a potential issue">Potential issue</span>}
    </span>
  );
}

interface Props {
  items: RuleItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  filters: ReviewFilter[];
  activeFilter: ReviewFilter;
  onFilter: (f: ReviewFilter) => void;
  countOf: (f: ReviewFilter) => number;
  search: string;
  onSearch: (q: string) => void;
  order: QueueOrder;
  onOrder: (o: QueueOrder) => void;
  advance: boolean;
  onAdvance: (on: boolean) => void;
  canAdvance: boolean;
  provisionOf: (r: RuleItem) => Provision | null;
  listRef?: RefObject<HTMLDivElement | null>;
  onListScroll?: (top: number) => void;
}

/** The review queue: filter, search and order on top, then the rules with their readable title, citation and status. In
 *  document order the rules are grouped under their provision. */
export function RuleQueue({ items, selectedId, onSelect, filters, activeFilter, onFilter, countOf, search, onSearch, order, onOrder, advance, onAdvance, canAdvance, provisionOf, listRef, onListScroll }: Props) {
  let lastGroup: string | null | undefined;
  return (
    <div className="rex-queue" aria-label="Review queue">
      <div className="rex-queue-tools">
        <div className="rex-tabs" role="group" aria-label="Filter rules">
          {filters.map((f) => (
            <button key={f} type="button" className="btn small" aria-pressed={activeFilter === f} onClick={() => onFilter(f)}>{FILTER_LABEL[f]} ({countOf(f)})</button>
          ))}
        </div>
        <label className="rex-search">
          <Icon name="search" size={14} />
          <input type="search" placeholder="Search title, citation…" value={search} onChange={(e) => onSearch(e.target.value)} aria-label="Search rules" />
        </label>
        <div className="rex-queue-opts">
          <label>Order
            <select value={order} onChange={(e) => onOrder(e.target.value as QueueOrder)} aria-label="Order of the rules">
              <option value="flagged">Potential issues first</option>
              <option value="document">By provision</option>
            </select>
          </label>
          {canAdvance && (
            <label className="rex-check"><input type="checkbox" checked={advance} onChange={(e) => onAdvance(e.target.checked)} />Go to the next open rule after a decision</label>
          )}
        </div>
      </div>
      <div className="rex-list" role="listbox" aria-label="Extracted rules" ref={listRef} onScroll={(e) => onListScroll?.(e.currentTarget.scrollTop)}>
        {items.length === 0 && <p className="rex-empty">No rules match this filter.</p>}
        {items.map((r) => {
          const group = order === "document" ? (provisionOf(r)?.label ?? "Other provisions") : null;
          const header = group !== null && group !== lastGroup;
          lastGroup = group;
          return (
            <Fragment key={r.id}>
              {header && <div className="rex-group-h" role="presentation">{group}</div>}
              <button type="button" role="option" aria-selected={r.id === selectedId} className={`rex-rule${r.id === selectedId ? " selected" : ""}`} onClick={() => onSelect(r.id)}>
                <span className="rex-rule-main">
                  <span className="rex-rule-title">{r.title}</span>
                  <span className="rex-rule-sub">{r.citation ?? "No citation"}</span>
                </span>
                <RuleStatus rule={r} compact />
              </button>
            </Fragment>
          );
        })}
      </div>
    </div>
  );
}
