import { useEffect, useState } from "react";
import { api, ApiError } from "../api";
import { akn4euHeadline, akn4euLayers } from "../exports";
import { fmtBytes } from "../format";
import type { Akn4euReport } from "../types";

const PREVIEW_LIMIT = 200_000;
const DOWNLOADS: { kind: "package" | "report" | "traceability" | "text_report"; label: string }[] = [
  { kind: "package", label: "All XML files (ZIP)" },
  { kind: "report", label: "Validation report" },
  { kind: "traceability", label: "Traceability (provenance, uncertainty)" },
  { kind: "text_report", label: "Text preservation report" },
];

/** Presentational part: everything shown for an existing export (also used by the tests). */
export function Akn4euReportView({ docId, report, selected, onView }: { docId: string; report: Akn4euReport; selected: string | null; onView: (name: string) => void }) {
  const head = akn4euHeadline(report);
  const warn = report.generator_warnings.reduce<Record<string, number>>((m, w) => ({ ...m, [w.code]: (m[w.code] ?? 0) + 1 }), {});
  return (
    <>
      <div className={`alert ${head.kind}`} role="status" data-testid="akn4eu-status"><strong>{head.title}</strong></div>
      <table className="layers" data-testid="akn4eu-layers">
        <thead><tr><th>Check</th><th>Result</th><th>What it shows</th></tr></thead>
        <tbody>
          {akn4euLayers(report).map((l) => (
            <tr key={l.name} className={`layer-${l.tone}`}>
              <td>{l.name}</td>
              <td><span className={`badge ${l.tone === "ok" ? "ok" : l.tone === "fail" ? "warn" : "uncertain"}`}>{l.result}</span></td>
              <td className="muted">{l.meaning}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted pad">
        {report.identifiers.resource_type} · {report.scope.articles} articles, {report.scope.recitals} recitals, {report.scope.annexes} annexes ·
        language {report.identifiers.language} · AKN4EU {report.identifiers.akn4eu_version} layout ·{" "}
        {report.identifiers.eli ? <>ELI {report.identifiers.eli} (supplied, checked)</> : <>no ELI (not printed in the PDF, none supplied — FRBR identifiers left empty, nothing invented)</>}
      </p>
      {Object.keys(warn).length > 0 && (
        <p className="muted pad" data-testid="akn4eu-warnings">Generator notes: {Object.entries(warn).map(([c, n]) => `${c} ×${n}`).join(", ")}</p>
      )}
      <div className="downloads">
        {DOWNLOADS.map((d) => <a key={d.kind} className="btn small" href={api.akn4euUrl(docId, d.kind)} download>{d.label}</a>)}
      </div>
      <ul className="artlist" data-testid="akn4eu-files">
        {Object.entries(report.files).map(([name, f]) => (
          <li key={name} className={name === selected ? "active" : ""}>
            <button className="artname" onClick={() => onView(name)}>
              {name === report.act_file ? "Act" : "Annex"} · {name}<span className="muted"> · {fmtBytes(f.bytes)}</span>
            </button>
            <span className={`badge ${f.valid_akn_3_1 ? "ok" : "warn"}`}>{f.valid_akn_3_1 ? "XSD valid" : `${f.errors.length} XSD errors`}</span>
            <span className={`badge ${f.sample_checks.passed ? "ok" : "warn"}`}>{f.sample_checks.passed ? "sample rules ok" : `${f.sample_checks.findings.length} rule findings`}</span>
            <a className="btn small" href={api.akn4euFileUrl(docId, name)} download>Download</a>
          </li>
        ))}
      </ul>
    </>
  );
}

export function Akn4euPanel({ docId }: { docId: string }) {
  const [report, setReport] = useState<Akn4euReport | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [eli, setEli] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [xml, setXml] = useState<string | null>(null);

  useEffect(() => {
    api.akn4eu(docId).then(setReport, (e: ApiError) => { if (e.status !== 404) setError(e.message); }).finally(() => setLoaded(true));
  }, [docId]);

  useEffect(() => {
    setXml(null);
    if (!selected) return;
    let dead = false;
    api.artifactText(api.akn4euFileUrl(docId, selected)).then((t) => { if (!dead) setXml(t); }, (e: ApiError) => { if (!dead) setError(e.message); });
    return () => { dead = true; };
  }, [docId, selected, report?.files[selected ?? ""]?.xml_sha256]); // eslint-disable-line react-hooks/exhaustive-deps

  const generate = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.generateAkn4eu(docId, eli.trim() || undefined);
      setReport(r);
      setSelected(r.act_file);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  if (!loaded) return <p className="muted pad">Loading…</p>;
  const truncated = xml !== null && xml.length > PREVIEW_LIMIT;
  return (
    <div className="akn4eu">
      <div className="pad">
        <p className="muted">
          AKN4EU export profile: Akoma Ntoso in the layout of the official AKN4EU 5.0.1.0 samples of the EU Publications Office
          (act + one file per annex), validated against the OASIS Akoma Ntoso 3.1 schema. Provenance and uncertainty are not put into the XML;
          they are in the traceability report.
        </p>
        <div className="startbox">
          <input value={eli} onChange={(e) => setEli(e.target.value)} placeholder="ELI, only if verified (optional)" aria-label="ELI (optional)" size={44} disabled={busy} />
          <button className="btn primary" onClick={() => void generate()} disabled={busy}>
            {busy ? "Generating and validating…" : report ? "Regenerate AKN4EU export" : "Generate AKN4EU export"}
          </button>
        </div>
      </div>
      {error && <div className="alert error" role="alert">{error}</div>}
      {report && <Akn4euReportView docId={docId} report={report} selected={selected} onView={setSelected} />}
      {selected && xml === null && !error && <p className="muted pad">Loading {selected}…</p>}
      {xml !== null && (
        <>
          {truncated && <p className="muted pad">Preview limited to the first {fmtBytes(PREVIEW_LIMIT)} of {fmtBytes(xml.length)}. Download for the full file.</p>}
          <pre className="preview" tabIndex={0} aria-label={`XML of ${selected}`}>{truncated ? xml.slice(0, PREVIEW_LIMIT) : xml}</pre>
        </>
      )}
    </div>
  );
}
