import { useState } from "react";
import { DOCUMENT_STEPS, documentStep, stageLabel } from "../demo/live";
import { StopConfirm } from "./StopConfirm";

/** What the backend is doing. The bar stays indeterminate: the backend reports stages, not a percentage. */
export function ProcessingStatus({ stage, onCancel }: { stage: string; onCancel?: () => void }) {
  const [confirm, setConfirm] = useState(false);
  const waiting = stage === "queued";
  const current = waiting ? -1 : documentStep(stage);
  const label = stageLabel(stage);
  const stopping = stage === "cancelling";
  return (
    <div className="demo-processing">
      <p className="demo-processing-label" role="status" aria-live="polite">{label}</p>
      <ol className="flow" aria-label="Document processing">
        {DOCUMENT_STEPS.map((step, index) => {
          const state = waiting ? (index === 0 ? "done" : "") : current < 0 ? "" : index < current ? "done" : index === current ? "current" : "";
          return (
            <li key={step} className={state} aria-current={state === "current" ? "step" : undefined}>
              <i aria-hidden="true" />
              {step}
            </li>
          );
        })}
      </ol>
      <div className="demo-bar" role="progressbar" aria-label="Processing document" aria-valuetext={label}><span /></div>
      <p className="muted small demo-hint">{stopping
        ? "The current step finishes, then processing stops. Nothing is saved as a result."
        : "This can take a few minutes. You can leave this page; processing continues."}</p>
      {onCancel && !stopping && (
        <div className="flow-actions">
          <button type="button" className="btn" onClick={() => setConfirm(true)}>Cancel</button>
        </div>
      )}
      {confirm && <StopConfirm onKeep={() => setConfirm(false)} onStop={() => { setConfirm(false); onCancel?.(); }} />}
    </div>
  );
}
