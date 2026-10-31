import { useEffect, useRef } from "react";
import { fmtBytes } from "../format";
import type { DeleteState } from "../documentLibrary";
import { Icon } from "./Icon";

interface Props { state: DeleteState; onCancel: () => void; onConfirm: () => void }

/** Confirmation before a permanent deletion: names the file, lists exactly what is removed, defaults to Cancel. */
export function DeleteDialog({ state, onCancel, onConfirm }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const cancelBtn = useRef<HTMLButtonElement>(null);
  const open = state.phase !== "idle";
  const docId = state.phase === "idle" ? "" : state.doc.id;
  const deleting = state.phase === "deleting";

  useEffect(() => {
    if (!open) return;
    const before = document.activeElement as HTMLElement | null;
    cancelBtn.current?.focus();
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !deleting) { e.stopPropagation(); onCancel(); }
      if (e.key !== "Tab" || !ref.current) return;
      const f = [...ref.current.querySelectorAll<HTMLElement>("button:not(:disabled)")];
      if (!f.length) return;
      const first = f[0], last = f[f.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    document.addEventListener("keydown", key, true);
    return () => {
      document.removeEventListener("keydown", key, true);
      // the row menu that opened the dialog is gone: return focus to that row's action button
      const back = before?.isConnected ? before : document.querySelector<HTMLElement>(`tr[data-doc-id="${docId}"] .icon-btn`);
      back?.focus?.();
    };
  }, [open, deleting]); // eslint-disable-line react-hooks/exhaustive-deps

  if (state.phase === "idle") return null;
  const doc = state.doc;
  const preview = state.phase === "confirm" || state.phase === "deleting" ? state.preview : null;
  const error = state.phase === "confirm" ? state.error : null;
  const canDelete = state.phase === "confirm" && !!preview?.can_delete;

  return (
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget && !deleting) onCancel(); }}>
      <div ref={ref} className="modal" role="dialog" aria-modal="true" aria-labelledby="del-title" aria-describedby="del-desc" data-testid="delete-dialog">
        <div className="modal-head">
          <span className="modal-icon danger" aria-hidden="true"><Icon name="trash" size={18} /></span>
          <h2 id="del-title">Delete document?</h2>
        </div>
        <div className="modal-body">
          <p id="del-desc">
            You are about to permanently delete <strong className="fname" data-testid="delete-filename">{doc.filename}</strong>.
            This cannot be undone: the file and everything ODOS stored for it are removed from this machine.
          </p>
          <h3 className="modal-sub">Will be deleted</h3>
          {state.phase === "loading" && <p className="muted" role="status"><span className="spinner" aria-hidden="true" /> Checking what is stored for this document…</p>}
          {preview && (
            <ul className="del-list" data-testid="delete-items">
              {preview.items.map((it) => (
                <li key={it.category}>
                  <span className="del-label">{it.label}</span>
                  <span className="del-meta">{it.files} {it.files === 1 ? "file" : "files"} · {fmtBytes(it.size_bytes)}</span>
                  {it.details.length > 0 && <span className="del-details">{it.category === "generated_artifacts" ? it.details.join(", ") : it.details.join(" · ")}</span>}
                </li>
              ))}
            </ul>
          )}
          {preview && <p className="muted small" data-testid="delete-total">Total: {preview.total_files} files, {fmtBytes(preview.total_bytes)}. Other documents, source code, schemas and shared settings are not affected.</p>}
          {preview && !preview.can_delete && <div className="alert warn" role="alert">{preview.blocked_reason}</div>}
          {error && <div className="alert error" role="alert" data-testid="delete-error"><Icon name="alert" size={15} /> {error}</div>}
        </div>
        <div className="modal-foot">
          <button ref={cancelBtn} className="btn" onClick={onCancel} disabled={deleting}>Cancel</button>
          <button className="btn danger" onClick={onConfirm} disabled={!canDelete} data-testid="delete-confirm">
            {deleting ? <><span className="spinner" aria-hidden="true" /> Deleting…</> : "Delete permanently"}
          </button>
        </div>
      </div>
    </div>
  );
}
