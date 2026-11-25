import { useEffect, useMemo, useRef, useState } from "react";
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

const STATE_ICON = { accepted: "check", pending: "clock", rejected: "x" } as const;

/** The review state of the rules citing an element: one compact chip per state (icon + count, never merged into one colour), a pencil
 *  chip when some were edited. A solid chip counts the element's own rules; a dashed, fainter chip counts the rules of its sub-elements,
 *  so a collapsed § still tells where decisions are open. */
function MarkDots({ id, m }: { id: string; m: ElementMarks }) {
  const part = (c: Counts, below: boolean) => (
    <>
      {STATES.filter((st) => c[st] > 0).map((st) => {
        const text = `${c[st]} rule${c[st] === 1 ? "" : "s"} ${STATE_LABEL[st].toLowerCase()}${below ? " in sub-elements" : ""}`;
        return <span key={st} className={`rm ${st}${below ? " below" : ""}`} title={text} aria-label={text}><Icon name={STATE_ICON[st]} size={12} />{c[st]}</span>;
      })}
      {c.invalid > 0 && <span className={`rm invalid${below ? " below" : ""}`} title={`${c.invalid} not valid Rule JSON${below ? " in sub-elements" : ""}`} aria-label={`${c.invalid} not valid Rule JSON${below ? " in sub-elements" : ""}`}><Icon name="braces" size={12} />{c.invalid}</span>}
      {c.edited > 0 && <span className={`rm edited${below ? " below" : ""}`} title={`${c.edited} edited${below ? " in sub-elements" : ""}`} aria-label={`${c.edited} edited${below ? " in sub-elements" : ""}`}><Icon name="edit" size={11} /></span>}
    </>
  );
  return <span className="marks" data-element={id}>{part(m.own, false)}{part(m.below, true)}</span>;
}

/** Explains the review marks; shown only when review decisions are known. Words and icons carry the meaning, colour only supports it. */
function MarksLegend({ invalid }: { invalid: boolean }) {
  return (
    <ul className="marks-legend" aria-label="Review status legend">
      {STATES.map((st) => <li key={st} className={`st ${st}`}><span className={`rm-dot ${st}`} aria-hidden="true"><Icon name={STATE_ICON[st]} size={11} /></span>{STATE_LABEL[st]}</li>)}
      {invalid && <li className="st invalidkey" title="The rule's record is not valid Rule JSON 2.0: it cannot be accepted until it is edited into shape (or it is rejected)"><span className="rm-dot invalid" aria-hidden="true"><Icon name="braces" size={11} /></span>Invalid Rule JSON</li>}
      <li className="scope" title="A solid chip counts the rules of this element itself"><span className="rm-sample" aria-hidden="true" />This element</li>
      <li className="scope" title="A dashed chip counts the rules of the elements below it"><span className="rm-sample below" aria-hidden="true" />Sub-elements</li>
    </ul>
  );
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

  // the tree is resized when the detail panel opens or the divider moves: the selected row stays in view
  const box = useRef<HTMLDivElement>(null);
  const selectedRef = useRef(selectedId);
  selectedRef.current = selectedId;
  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const reveal = () => { if (selectedRef.current) document.getElementById(`node-${selectedRef.current}`)?.scrollIntoView({ block: "nearest" }); };
    const panel = el.closest(".structure"); // the panel animates when the details open or close
    panel?.addEventListener("transitionend", reveal);
    let last = el.clientHeight;
    const ro = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => { if (el.clientHeight !== last) { last = el.clientHeight; reveal(); } });
    ro?.observe(el);
    return () => { panel?.removeEventListener("transitionend", reveal); ro?.disconnect(); };
  }, []);

  /** Keyboard use of the tree: Enter/Space select (or open a branch), ↑/↓ move between visible rows, → expands and ← collapses. */
  const onNodeKey = (ev: React.KeyboardEvent<HTMLDivElement>, n: TreeNode, hasKids: boolean, isOpen: boolean) => {
    if (ev.target !== ev.currentTarget) return; // the twisty button has its own keys
    if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); ev.currentTarget.click(); return; }
    if (ev.key === "ArrowRight" && hasKids && !isOpen) { ev.preventDefault(); toggle(n.key); return; }
    if (ev.key === "ArrowLeft" && hasKids && isOpen && !filtering) { ev.preventDefault(); toggle(n.key); return; }
    if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
      ev.preventDefault();
      const rows = [...(box.current?.querySelectorAll<HTMLElement>(".node") ?? [])];
      rows[rows.indexOf(ev.currentTarget) + (ev.key === "ArrowDown" ? 1 : -1)]?.focus();
    }
  };

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
          style={{ "--depth": depth } as React.CSSProperties}
          tabIndex={selectedId === n.key || (!selectedId && n === roots[0]) ? 0 : -1} aria-current={selectedId === n.key ? "true" : undefined}
          onClick={() => { const a = clickAction(n); if (a && "select" in a) onSelect(a.select); else if (a) toggle(a.toggle); }}
          onKeyDown={(ev) => onNodeKey(ev, n, kids.length > 0, expanded)}
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
    <div className="tree" ref={box}>
      <div className="tree-tools">
        <label className="tree-search">
          <Icon name="search" size={18} />
          <input type="search" placeholder="Search text…" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search structure" />
        </label>
        <button onClick={() => setOpen(new Set(byKey.keys()))}>Expand all</button>
        <button onClick={() => setOpen(new Set())}>Collapse all</button>
        {marks && <MarksLegend invalid={[...marks.values()].some((m) => m.own.invalid + m.below.invalid > 0)} />}
      </div>
      <ul className="tree-list" role="tree">{roots.map((r) => row(r, 0))}</ul>
      {visible && visible.size === 0 && <p className="muted pad">No matching elements.</p>}
    </div>
  );
}
