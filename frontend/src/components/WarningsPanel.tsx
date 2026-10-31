import { useState } from "react";
import type { DocumentModel } from "../types";

interface Props {
  model: DocumentModel;
  onSelect: (id: string) => void;
  summary: Record<string, unknown>;
}

export function WarningsPanel({ model, onSelect, summary }: Props) {
  const [sev, setSev] = useState<"all" | "warning" | "info">("all");
  const uncertain = model.elements.filter((e) => e.uncertain);
  const list = model.warnings.filter((w) => sev === "all" || w.severity === sev);
  const counts = model.warnings.reduce<Record<string, number>>((a, w) => ({ ...a, [w.code]: (a[w.code] ?? 0) + 1 }), {});

  return (
    <div className="warnings pad">
      <div className="cards">
        <div className="card"><b>{uncertain.length}</b><span>uncertain elements</span></div>
        <div className="card"><b>{model.warnings.length}</b><span>parser warnings</span></div>
        {"akn_xsd_valid" in summary && <div className={`card ${summary.akn_xsd_valid ? "ok" : "bad"}`}><b>{summary.akn_xsd_valid ? "valid" : "invalid"}</b><span>Akoma Ntoso XSD</span></div>}
      </div>
      <p className="muted">{Object.entries(counts).map(([k, v]) => `${k}: ${v}`).join(" · ") || "No warnings."}</p>

      <h4>Uncertain elements</h4>
      <ul className="warnlist">
        {uncertain.map((e) => (
          <li key={e.id}><button className="link" onClick={() => onSelect(e.id)}>{e.id.split("/").slice(-3).join("/")}</button> <span className="muted">{e.uncertainty_reasons.join(", ")}</span></li>
        ))}
        {!uncertain.length && <li className="muted">None.</li>}
      </ul>

      <h4>Warnings
        <select value={sev} onChange={(e) => setSev(e.target.value as typeof sev)} aria-label="Filter severity">
          <option value="all">all</option><option value="warning">warning</option><option value="info">info</option>
        </select>
      </h4>
      <ul className="warnlist">
        {list.map((w, i) => (
          <li key={i}>
            <span className={`sev ${w.severity}`}>{w.severity}</span> <code>{w.code}</code> {w.message}
            {w.element_id && <> <button className="link" onClick={() => onSelect(w.element_id!)}>show</button></>}
          </li>
        ))}
      </ul>
    </div>
  );
}
