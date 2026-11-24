import { useEffect, useMemo, useState } from "react";
import { Icon } from "./Icon";
import { TYPE_LABELS, buildTree, clickAction, visibleKeys, type TreeNode } from "../structure";
import type { DocumentModel } from "../types";
import { STATE_LABEL, type Counts, type ElementMarks, type ReviewState } from "../demo/reviewMarks";

interface Props {
  model: DocumentModel;
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** Persisted review decisions of the rules that cite each element (Document Review); absent when none are known. */
  marks?: Map<string, ElementMarks>;
}

const STATES: ReviewState[] = ["accepted", "pending", "rejected"];

/** The review state of the rules citing an element: one coloured count per state (never merged into one colour), a blue dot when some
 *  were edited. Rules of sub-elements are shown fainter, so a collapsed § still tells where decisions are open. */
function MarkDots({ id, m }: { id: string; m: ElementMarks }) {
  const part = (c: Counts, below: boolean) => (
    <>
      {STATES.filter((st) => c[st] > 0).map((st) => (
        <span key={st} className={`rm ${st}${below ? " below" : ""}`} title={`${c[st]} ${STATE_LABEL[st].toLowerCase()}${below ? " in sub-elements" : ""}`} aria-label={`${c[st]} rule${c[st] === 1 ? "" : "s"} ${STATE_LABEL[st].toLowerCase()}${below ? " in sub-elements" : ""}`}>{c[st]}</span>
      ))}
      {c.edited > 0 && <span className={`rm edited${below ? " below" : ""}`} title={`${c.edited} edited${below ? " in sub-elements" : ""}`} aria-label={`${c.edited} edited`} />}
    </>
  );
  return <span className="marks" data-element={id}>{part(m.own, false)}{part(m.below, true)}</span>;
}

export function StructureTree({ model, selectedId, onSelect, marks }: Props) {
  const { roots, byKey, parentOf } = useMemo(() => buildTree(model), [model]);
  const [open, setOpen] = useState<Set<string>>(() => new Set(roots.filter((r) => r.element?.region === "body").map((r) => r.key)));
  const [query, setQuery] = useState("");
  const visible = useMemo(() => visibleKeys(byKey, parentOf, query), [byKey, parentOf, query]);

  // reveal the selected element (e.g. when it is selected from the PDF side or the artifacts tab)
  useEffect(() => {
    if (!selectedId) return;
    const add: string[] = [];
    for (let k = parentOf.get(selectedId); k; k = parentOf.get(k)) add.push(k);
    if (add.length) setOpen((o) => new Set([...o, ...add]));
    document.getElementById(`node-${selectedId}`)?.scrollIntoView({ block: "nearest" });
  }, [selectedId, parentOf]);

  const toggle = (k: string) => setOpen((o) => { const n = new Set(o); if (n.has(k)) n.delete(k); else n.add(k); return n; });
  const filtering = visible !== null;

  const row = (n: TreeNode, depth: number) => {
    if (visible && !visible.has(n.key)) return null;
    const e = n.element;
    const kids = n.children.filter((c) => !visible || visible.has(c.key));
    const expanded = filtering || open.has(n.key);
    return (
      <li key={n.key} role="treeitem" aria-expanded={kids.length ? expanded : undefined}>
        <div
          id={`node-${n.key}`}
          className={`node${selectedId === n.key ? " selected" : ""}`}
          style={{ paddingLeft: 10 + depth * 22 }}
          onClick={() => { const a = clickAction(n); if (a && "select" in a) onSelect(a.select); else if (a) toggle(a.toggle); }}
          data-toc-entry={n.toc ? n.toc.id : undefined}
          title={n.toc ? (n.toc.target_id ? `Open ${n.toc.target_id}` : `Not linked (${n.toc.status}): ${n.toc.evidence}`) : undefined}
        >
          <button className={`twisty${kids.length && expanded ? " open" : ""}`} aria-label={expanded ? "Collapse" : "Expand"} disabled={!kids.length}
                  onClick={(ev) => { ev.stopPropagation(); toggle(n.key); }}>
            {kids.length ? <Icon name="chevron-right" size={16} /> : null}
          </button>
          {e && <span className={`kind kind-${e.type}`}>{TYPE_LABELS[e.type] ?? e.type}</span>}
          {n.toc && <span className="kind kind-toc_entry">TOC</span>}
          <span className="label">{n.label}</span>
          {e && marks?.get(e.id) && <MarkDots id={e.id} m={marks.get(e.id)!} />}
          {e?.pages[0] != null && <span className="pg" title="Source page">p.{e.pages[0]}</span>}
        </div>
        {kids.length > 0 && expanded && <ul role="group">{kids.map((c) => row(c, depth + 1))}</ul>}
      </li>
    );
  };

  return (
    <div className="tree">
      <div className="tree-tools">
        <label className="tree-search">
          <Icon name="search" size={18} />
          <input type="search" placeholder="Search text…" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search structure" />
        </label>
        <button onClick={() => setOpen(new Set(byKey.keys()))}>Expand all</button>
        <button onClick={() => setOpen(new Set())}>Collapse all</button>
      </div>
      <ul className="tree-list" role="tree">{roots.map((r) => row(r, 0))}</ul>
      {visible && visible.size === 0 && <p className="muted pad">No matching elements.</p>}
    </div>
  );
}
