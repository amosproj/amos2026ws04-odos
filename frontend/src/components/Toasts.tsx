import { Icon } from "./Icon";

export interface Toast { id: number; kind: "success" | "error"; text: string }

/** Feedback for real API results. Success messages dismiss themselves (the page does that); errors stay until closed. */
export function Toasts({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: number) => void }) {
  if (!toasts.length) return null;
  return (
    <div className="toasts" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast ${t.kind}`} role={t.kind === "error" ? "alert" : "status"}>
          <Icon name={t.kind === "success" ? "check" : "alert"} size={16} />
          <span>{t.text}</span>
          <button className="icon-btn" aria-label="Dismiss message" onClick={() => onDismiss(t.id)}><Icon name="x" size={14} /></button>
        </div>
      ))}
    </div>
  );
}
