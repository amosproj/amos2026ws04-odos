import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { fmtBytes } from "../format";
import type { ArtifactInfo } from "../types";

const LABELS: Record<string, string> = {
  akn_xml: "Akoma Ntoso XML",
  akn_validation_report: "AKN validation report",
  akn_traceability: "AKN traceability",
  akn_text_report: "AKN text preservation",
  legal_json: "Legal document (JSON)",
  legal_json_validation_report: "JSON validation report",
  document_model: "Internal document model (JSON)",
  validation_report: "Parser validation report",
  docling_raw: "Docling raw JSON",
  extracted_md: "Extracted Markdown",
  reading_order_evidence: "Reading-order evidence (PDF text layer)",
};
const PREVIEW_LIMIT = 200_000;

export function ArtifactsPanel({ artifacts }: { artifacts: ArtifactInfo[] }) {
  const [sel, setSel] = useState<string | null>(artifacts[0]?.type ?? null);
  const [text, setText] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const current = artifacts.find((a) => a.type === sel);

  useEffect(() => {
    if (!current) return;
    let dead = false;
    setText(null);
    setError(null);
    api.artifactText(current.url).then(
      (t) => { if (!dead) setText(t); },
      (e: ApiError) => { if (!dead) setError(e.message); },
    );
    return () => { dead = true; };
  }, [current]);

  if (!artifacts.length) return <p className="muted pad">No artifacts yet.</p>;
  const truncated = text !== null && text.length > PREVIEW_LIMIT;

  return (
    <div className="artifacts">
      <ul className="artlist">
        {artifacts.map((a) => (
          <li key={a.type} className={a.type === sel ? "active" : ""}>
            <button className="artname" onClick={() => setSel(a.type)}>
              {LABELS[a.type] ?? a.type}<span className="muted"> · {fmtBytes(a.size_bytes)}</span>
            </button>
            <a className="btn small" href={api.artifactUrl(a.url)} download>Download</a>
          </li>
        ))}
      </ul>
      {error && <div className="alert error">{error}</div>}
      {text === null && !error && <p className="muted pad">Loading preview…</p>}
      {text !== null && (
        <>
          {truncated && <p className="muted pad">Preview limited to the first {fmtBytes(PREVIEW_LIMIT)} of {fmtBytes(text.length)}. Download for the full file.</p>}
          <pre className="preview" tabIndex={0}>{truncated ? text.slice(0, PREVIEW_LIMIT) : text}</pre>
        </>
      )}
    </div>
  );
}
