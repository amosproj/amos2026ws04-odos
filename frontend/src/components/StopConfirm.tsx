import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

/** Compact confirmation for stopping a running document or rule extraction. "Keep processing" only closes it. */
export function StopConfirm({ onKeep, onStop }: { onKeep: () => void; onStop: () => void }) {
  const keep = useRef<HTMLButtonElement>(null);
  useEffect(() => { keep.current?.focus(); }, []);
  return createPortal(
    <div className="stop-overlay" onPointerDown={(e) => { if (e.target === e.currentTarget) onKeep(); }}>
      <div className="stop-dialog" role="alertdialog" aria-modal="true" aria-labelledby="stop-title" aria-describedby="stop-text"
           onKeyDown={(e) => { if (e.key === "Escape") { e.stopPropagation(); onKeep(); } }}>
        <strong id="stop-title">Stop processing?</strong>
        <p id="stop-text">Your current progress won't be saved.</p>
        <div className="stop-actions">
          <button type="button" className="btn" ref={keep} onClick={onKeep}>Keep processing</button>
          <button type="button" className="btn primary" onClick={onStop}>Stop</button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
