import { stageLabel } from "../demo/live";

/** What the backend is doing right now. The bar is indeterminate on purpose: the backend reports stages, not progress. */
export function ProcessingStatus({ stage }: { stage: string }) {
  const label = stageLabel(stage);
  return (
    <div className="demo-processing">
      <p className="demo-processing-label" role="status" aria-live="polite">{label}</p>
      <div className="demo-bar" role="progressbar" aria-label="Processing document" aria-valuetext={label}><span /></div>
      <p className="muted small demo-hint">Large documents can take a few minutes. Please keep this page open.</p>
    </div>
  );
}
