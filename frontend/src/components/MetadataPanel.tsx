import type { DocumentModel } from "../types";

const LABELS: [string, string][] = [
  ["title", "Title"], ["document_type", "Type"], ["document_number", "Number"], ["issuing_bodies", "Issued by"],
  ["adoption_date_text", "Adoption (as printed)"], ["adoption_date", "Adoption date (ISO)"], ["subject", "Subject"],
  ["eea_relevance", "EEA relevance"], ["publication_journal", "Journal"], ["publication_reference", "Reference"],
  ["publication_date_text", "Published (as printed)"], ["publication_date", "Published (ISO)"],
  ["short_title", "Short title"], ["ausfertigungsdatum", "Ausfertigungsdatum"], ["stand", "Stand"],
];

/** Document metadata read from the source text; each value shows the element(s) it came from. */
export function MetadataPanel({ model, onSelect }: { model: DocumentModel; onSelect: (id: string) => void }) {
  const md = model.metadata as unknown as Record<string, unknown>;
  const prov = model.metadata.metadata_provenance ?? {};
  const rows = LABELS.filter(([k]) => md[k] !== null && md[k] !== undefined && md[k] !== "");
  const byId = new Set(model.elements.map((e) => e.id));
  return (
    <div className="pad">
      <p className="muted">
        Values are copied from the document text; nothing is inferred. {model.profile === "eu_legislation" ? "Profile: EU legislation (prototype)." : "Profile: German law (prototype)."}
      </p>
      {rows.length === 0 && <p className="muted">No metadata found.</p>}
      <dl className="kv">
        {rows.map(([k, label]) => (
          <div key={k} style={{ display: "contents" }}>
            <dt>{label}</dt>
            <dd>
              {String(md[k])}
              {(prov[k] ?? []).map((id) =>
                byId.has(id) ? <button key={id} className="link" onClick={() => onSelect(id)}>source</button> : <span key={id} className="muted" title={id}> (page header)</span>,
              )}
            </dd>
          </div>
        ))}
      </dl>
      <p className="muted">Source: {model.source.filename ?? "?"} · {model.source.num_pages} pages · Docling {model.source.docling_version ?? "?"}</p>
    </div>
  );
}
