import { useEffect, useRef } from "react";
import { fmtBytes } from "../format";
import { docTypeLabel, reviewLabel, statusLabel, type SortDir, type SortKey, type View } from "../documentLibrary";
import { fmtDateTime } from "../format";
import type { DocumentStatus } from "../types";
import { Icon } from "./Icon";

export interface MenuState { doc: DocumentStatus; top: number; right: number }

interface Props {
  docs: DocumentStatus[];
  view: View;
  sort: { key: SortKey; dir: SortDir };
  onSort: (key: SortKey) => void;
  menu: MenuState | null;
  onMenu: (doc: DocumentStatus, anchor: DOMRect | null) => void;
  onOpen: (doc: DocumentStatus) => void;
  onDelete: (doc: DocumentStatus) => void;
}

function Th({ label, k, sort, onSort, className }: { label: string; k: SortKey; sort: Props["sort"]; onSort: Props["onSort"]; className?: string }) {
  const active = sort.key === k;
  return (
    <th scope="col" className={className} aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}>
      <button className="th-sort" onClick={() => onSort(k)} title={`Sort by ${label.toLowerCase()}`}>
        {label}
        {active && <Icon name={sort.dir === "asc" ? "up" : "down"} size={12} />}
      </button>
    </th>
  );
}

export function StatusChip({ doc }: { doc: DocumentStatus }) {
  const unsupported = doc.status === "completed" && doc.outcome === "unsupported";
  const tone = unsupported ? "unsupported" : doc.status;
  return (
    <span className={`chip ${tone}`}>
      {statusLabel(doc)}
      {doc.status === "processing" && doc.stage ? ` · ${doc.stage.replace(/_/g, " ")}` : ""}
    </span>
  );
}

export function DocumentTable({ docs, view, sort, onSort, menu, onMenu, onOpen, onDelete }: Props) {
  const showReview = view === "reviews";
  return (
    <>
      <div className="table-wrap">
        <table className="doc-table" data-testid="document-table">
          <thead>
            <tr>
              <Th label="Document Name" k="name" sort={sort} onSort={onSort} className="col-name" />
              <th scope="col" className="col-type">Document Type</th>
              <Th label="Uploaded" k="uploaded" sort={sort} onSort={onSort} className="col-date" />
              <Th label="Status" k="status" sort={sort} onSort={onSort} className="col-status" />
              {showReview && <th scope="col" className="col-review">Review</th>}
              <th scope="col" className="col-actions"><span className="sr-only">Actions</span></th>
            </tr>
          </thead>
          <tbody>
            {docs.map((d) => {
              const type = docTypeLabel(d);
              const rev = reviewLabel(d);
              return (
                <tr key={d.id} data-doc-id={d.id} className={menu?.doc.id === d.id ? "menu-open" : ""}
                  onClick={(e) => { if (!(e.target as HTMLElement).closest("a,button")) onOpen(d); }}>
                  <td className="col-name">
                    <a href={`#/doc/${d.id}`} className="doc-link" title={d.filename}>
                      <Icon name="file" size={16} />
                      <span className="doc-name">{d.filename}</span>
                    </a>
                    <span className="doc-sub">{fmtBytes(d.size_bytes)}</span>
                  </td>
                  <td className="col-type">{type ?? <span className="muted">Not classified</span>}</td>
                  <td className="col-date">{fmtDateTime(d.uploaded_at)}</td>
                  <td className="col-status"><StatusChip doc={d} /></td>
                  {showReview && <td className="col-review">{rev ?? "—"}</td>}
                  <td className="col-actions">
                    <button className="icon-btn" aria-label={`Actions for ${d.filename}`} aria-haspopup="menu" aria-expanded={menu?.doc.id === d.id}
                      onClick={(e) => onMenu(d, menu?.doc.id === d.id ? null : e.currentTarget.getBoundingClientRect())}>
                      <Icon name="more" size={18} />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {menu && <RowMenu menu={menu} onClose={() => onMenu(menu.doc, null)} onOpen={() => onOpen(menu.doc)} onDelete={() => onDelete(menu.doc)} />}
    </>
  );
}

/** Menu of one row. Fixed position (the table scrolls horizontally on small screens and would clip it). */
export function RowMenu({ menu, onClose, onOpen, onDelete }: { menu: MenuState; onClose: () => void; onOpen: () => void; onDelete: () => void }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    ref.current?.querySelector<HTMLElement>("[role=menuitem]")?.focus();
    const down = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node) && !(e.target as HTMLElement).closest(".icon-btn")) onClose(); };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        document.querySelector<HTMLElement>(`tr[data-doc-id="${menu.doc.id}"] .icon-btn`)?.focus();
      } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        const items = [...(ref.current?.querySelectorAll<HTMLElement>("[role=menuitem]") ?? [])];
        const i = items.indexOf(document.activeElement as HTMLElement);
        items[(i + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length]?.focus();
      } else if (e.key === "Tab") onClose();
    };
    document.addEventListener("mousedown", down);
    document.addEventListener("keydown", key);
    window.addEventListener("resize", onClose);
    window.addEventListener("scroll", onClose, true);
    return () => {
      document.removeEventListener("mousedown", down);
      document.removeEventListener("keydown", key);
      window.removeEventListener("resize", onClose);
      window.removeEventListener("scroll", onClose, true);
    };
  }, [menu.doc.id]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div ref={ref} className="menu" role="menu" aria-label={`Actions for ${menu.doc.filename}`} style={{ top: menu.top, right: menu.right }}>
      <button role="menuitem" className="menu-item" onClick={onOpen}><Icon name="open" size={15} />Open Document</button>
      <button role="menuitem" className="menu-item danger" onClick={onDelete}><Icon name="trash" size={15} />Delete Document</button>
    </div>
  );
}
