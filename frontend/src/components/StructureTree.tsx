import { useEffect, useMemo, useState } from "react";
import { AKN_HINT, TYPE_LABELS, buildTree, clickAction, visibleKeys, type TreeNode } from "../structure";
import type { DocumentModel } from "../types";

interface Props {
  model: DocumentModel;
  selectedId: string | null;
  onSelect: (id: string) => void;
  warningIds: Set<string>;
  editedIds?: Set<string>;
}

export function StructureTree({ model, selectedId, onSelect, warningIds, editedIds }: Props) {
  const { roots, byKey, parentOf } = useMemo(() => buildTree(model), [model]);
  const [open, setOpen] = useState<Set<string>>(() => new Set(roots.filter((r) => r.element?.region === "body").map((r) => r.key)));
  const [query, setQuery] = useState("");
  const [onlyFlagged, setOnlyFlagged] = useState(false);
  const visible = useMemo(() => visibleKeys(byKey, parentOf, query, onlyFlagged, (id) => warningIds.has(id)), [byKey, parentOf, query, onlyFlagged, warningIds]);

  // reveal the selected element (e.g. when selected from the warnings list)
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
    const own = e ? (e.uncertain ? 1 : 0) : 0;
    return (
      <li key={n.key} role="treeitem" aria-expanded={kids.length ? expanded : undefined}>
        <div
          id={`node-${n.key}`}
          className={`node${selectedId === n.key ? " selected" : ""}${e?.uncertain ? " uncertain" : ""}`}
          style={{ paddingLeft: 8 + depth * 16 }}
          onClick={() => { const a = clickAction(n); if (a && "select" in a) onSelect(a.select); else if (a) toggle(a.toggle); }}
          data-toc-entry={n.toc ? n.toc.id : undefined}
          title={n.toc ? (n.toc.target_id ? `Open ${n.toc.target_id}` : `Not linked (${n.toc.status}): ${n.toc.evidence}`) : undefined}
        >
          <button className="twisty" aria-label={expanded ? "Collapse" : "Expand"} disabled={!kids.length}
                  onClick={(ev) => { ev.stopPropagation(); toggle(n.key); }}>
            {kids.length ? (expanded ? "▾" : "▸") : ""}
          </button>
          {e && <span className={`kind kind-${e.type}`} title={AKN_HINT[e.type] ? `Closest Akoma Ntoso element: ${AKN_HINT[e.type]}` : undefined}>{TYPE_LABELS[e.type] ?? e.type}</span>}
          {n.toc && <span className="kind kind-toc_entry">TOC</span>}
          <span className="label">{n.label}</span>
          {n.toc && !n.toc.target_id && <span className="badge uncertain" title={n.toc.evidence}>{n.toc.status}</span>}
          {e?.pages[0] != null && <span className="pg" title="Source page">p.{e.pages[0]}</span>}
          {n.uncertain > 0 && <span className="badge uncertain" title={`${n.uncertain} uncertain element(s)${own ? " (incl. this one)" : ""}`}>? {n.uncertain}</span>}
          {n.warnings > 0 && <span className="badge warn" title={`${n.warnings} parser warning(s)`}>⚠ {n.warnings}</span>}
          {editedIds?.has(n.key) && <span className="badge edited" title="Corrected by a reviewer">edited</span>}
        </div>
        {kids.length > 0 && expanded && <ul role="group">{kids.map((c) => row(c, depth + 1))}</ul>}
      </li>
    );
  };

  return (
    <div className="tree">
      <div className="tree-tools">
        <input type="search" placeholder="Search text…" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search structure" />
        <label className="check"><input type="checkbox" checked={onlyFlagged} onChange={(e) => setOnlyFlagged(e.target.checked)} /> flagged only</label>
        <button onClick={() => setOpen(new Set(byKey.keys()))}>Expand all</button>
        <button onClick={() => setOpen(new Set())}>Collapse</button>
      </div>
      <ul className="tree-list" role="tree">{roots.map((r) => row(r, 0))}</ul>
      {visible && visible.size === 0 && <p className="muted pad">No matching elements.</p>}
    </div>
  );
}
