import { useEffect, useMemo, useState } from "react";
import { Icon } from "../components/Icon";
import { Logo } from "../components/Logo";
import type { DemoResult } from "./fixtures";
import { AUTO_ACCEPTED_COUNT, MOCK_RULES, NEEDS_REVIEW_COUNT, type MockRule } from "./ruleExtractionMock";
import "./rule-extraction.css";

type RuleFilter = "all" | "auto" | "review";
type DetailTab = "json" | "source";
type Source = "ontology" | "digitalTwin";

const TAB_LABEL: Record<RuleFilter, string> = { all: "All Rules", auto: "Auto-Accepted", review: "Needs Review" };
const COMING_SOON = "Coming soon — not available in this preview";

/** The LLM Rule Extraction & Mapping preview: a frontend-only mock-up of the next step after Document Review. Nothing
 *  here calls an LLM or a backend; `MOCK_RULES` stands in for the real extraction until that pipeline exists. */
export function RuleExtractionView({ result, onBack }: { result: DemoResult; onBack: () => void }) {
  const [filter, setFilter] = useState<RuleFilter>("all");
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(MOCK_RULES[0]?.id ?? null);
  const [detailTab, setDetailTab] = useState<DetailTab>("json");
  const [source, setSource] = useState<Source>("ontology");

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return MOCK_RULES.filter((r) => (filter === "all" || r.status === filter) && (!q || r.id.toLowerCase().includes(q) || r.title.toLowerCase().includes(q)));
  }, [filter, search]);

  useEffect(() => {
    if (!filtered.some((r) => r.id === selectedId)) setSelectedId(filtered[0]?.id ?? null);
  }, [filtered, selectedId]);

  const selected = useMemo(() => MOCK_RULES.find((r) => r.id === selectedId) ?? null, [selectedId]);
  const total = MOCK_RULES.length;
  const filename = result.filename ?? result.title;
  const pages = result.model.source.num_pages;

  return (
    <main className="workspace rex">
      <div className="docbar">
        <Logo compact />
        <span className="docbar-sep" aria-hidden="true" />
        <h2 title={filename}>{filename}</h2>
        <span className="demo-status ok">Completed</span>
        <span className="spacer" />
        <button className="btn" onClick={onBack}><Icon name="back" size={16} />Back to Document Review</button>
      </div>

      <WorkflowSteps />

      <div className="rex-body">
        <aside aria-label="Extraction input">
          <div className="rex-panel">
            <div className="rex-card-head">
              <Icon name="file" size={20} />
              <div>
                <p className="rex-card-title">Extraction Input</p>
                <p className="rex-card-sub">Provide optional context for semantic mapping.</p>
              </div>
            </div>
            <div className="rex-doc">
              <Icon name="file" size={20} />
              <div className="rex-doc-text">
                <div className="rex-doc-name">{filename}</div>
                <div className="rex-doc-meta">{pages} page{pages === 1 ? "" : "s"}</div>
              </div>
              <Icon name="check" size={18} />
            </div>
          </div>

          <div className="rex-panel">
            <div className="rex-card-head">
              <Icon name="network" size={20} />
              <div>
                <p className="rex-card-title">Ontology / Digital Twin <span className="chip">Coming Soon</span></p>
                <p className="rex-card-sub">Select one data source for rule mapping.</p>
              </div>
            </div>
            <div className="rex-source-toggle" role="group" aria-label="Mapping data source">
              <button type="button" aria-pressed={source === "ontology"} onClick={() => setSource("ontology")}>
                <Icon name="network" size={20} />Ontology
              </button>
              <button type="button" aria-pressed={source === "digitalTwin"} onClick={() => setSource("digitalTwin")}>
                <Icon name="cube" size={20} />Digital Twin
              </button>
            </div>
            <div className="rex-upload" aria-disabled="true">
              <Icon name="upload" />
              <span className="rex-upload-title">Upload {source === "ontology" ? "ontology" : "digital twin"} file (JSON)</span>
              <span className="rex-upload-hint">or drag &amp; drop here</span>
              <button type="button" className="btn small" disabled title={COMING_SOON}>Coming Soon</button>
            </div>
            <p className="rex-note"><Icon name="info" size={14} />Supported format: JSON (e.g. TerminusDB schema, digital twin)</p>
          </div>
        </aside>

        <section className="rex-panel" aria-label="LLM Rule Extraction &amp; Mapping">
          <div className="rex-main-head">
            <div>
              <div className="rex-main-title"><Icon name="sparkle" size={20} />LLM Rule Extraction &amp; Mapping<span className="chip">UI Preview · Coming Soon</span></div>
              <p className="rex-main-sub">Extract compliance rules from the legal document and (optionally) map them to an ontology or digital twin.</p>
            </div>
            <button type="button" className="btn" disabled title={COMING_SOON}><Icon name="refresh" size={16} />Restart Extraction</button>
          </div>

          <div className="rex-overview">
            <div>
              <p className="rex-card-title">Extraction Overview</p>
              <p className="rex-card-sub">Summary of the extracted rules (mock data).</p>
            </div>
            <div className="rex-overview-stats">
              <div className="rex-stat"><span className="rex-stat-value">{total}</span><span className="rex-stat-label">Extracted Rules</span></div>
              <div className="rex-stat"><span className="rex-stat-value accent">80%</span><span className="rex-stat-label">Auto-Accepted ({AUTO_ACCEPTED_COUNT} rules)</span></div>
              <div className="rex-stat"><span className="rex-stat-value warn">20%</span><span className="rex-stat-label">Needs Review ({NEEDS_REVIEW_COUNT} rules)</span></div>
            </div>
            <div className="rex-bar" role="img" aria-label={`${AUTO_ACCEPTED_COUNT} of ${total} rules auto-accepted, ${NEEDS_REVIEW_COUNT} need review (mock data)`}>
              <span className="rex-bar-auto" style={{ width: "80%" }} />
              <span className="rex-bar-review" style={{ width: "20%" }} />
            </div>
          </div>

          <div className="rex-filters">
            <div className="rex-tabs" role="group" aria-label="Filter rules">
              {(["all", "auto", "review"] as const).map((f) => (
                <button key={f} type="button" className="btn small" aria-pressed={filter === f} onClick={() => setFilter(f)}>
                  {TAB_LABEL[f]} ({f === "all" ? total : f === "auto" ? AUTO_ACCEPTED_COUNT : NEEDS_REVIEW_COUNT})
                </button>
              ))}
            </div>
            <label className="rex-search">
              <Icon name="search" size={14} />
              <input type="search" placeholder="Search rules…" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search rules" />
            </label>
          </div>

          <div className="rex-split">
            <div className="rex-list" role="listbox" aria-label="Extracted rules">
              {filtered.length === 0 && <p className="rex-empty">No mock rules match this filter.</p>}
              {filtered.map((r) => (
                <button key={r.id} type="button" role="option" aria-selected={r.id === selectedId}
                        className={`rex-rule${r.id === selectedId ? " selected" : ""}`}
                        onClick={() => { setSelectedId(r.id); setDetailTab("json"); }}>
                  <span className="rex-rule-id">{r.id}</span>
                  <span className="rex-rule-title">{r.title}</span>
                  <StatusChip status={r.status} />
                </button>
              ))}
            </div>
            <RuleDetail rule={selected} tab={detailTab} onTab={setDetailTab} />
          </div>
        </section>
      </div>
    </main>
  );
}

function WorkflowSteps() {
  return (
    <nav className="rex-steps" aria-label="Rule extraction workflow">
      <ol>
        <li className="rex-step done"><span className="rex-step-circle"><Icon name="check" size={18} /></span><span className="rex-step-label">Document Review</span></li>
        <li className="rex-step current" aria-current="step"><span className="rex-step-circle">2</span><span className="rex-step-label">LLM Rule Extraction &amp; Review</span></li>
        <li className="rex-step upcoming"><span className="rex-step-circle">3</span><span className="rex-step-label">Validation<small>Coming Soon</small></span></li>
      </ol>
    </nav>
  );
}

function StatusChip({ status }: { status: MockRule["status"] }) {
  return status === "auto"
    ? <span className="rex-status auto"><Icon name="check" size={12} />Auto-Accepted</span>
    : <span className="rex-status review"><Icon name="user" size={12} />Needs Review</span>;
}

function RuleDetail({ rule, tab, onTab }: { rule: MockRule | null; tab: DetailTab; onTab: (t: DetailTab) => void }) {
  if (!rule) return <div className="rex-detail rex-empty-detail"><Icon name="info" size={20} /><span>Select a rule to see its details.</span></div>;
  const jsonText = JSON.stringify(rule.json, null, 2);
  return (
    <div className="rex-detail">
      <div className="rex-detail-head">
        <div className="rex-detail-title">
          <span className="rex-detail-id">{rule.id}</span>
          <strong>{rule.title}</strong>
          <StatusChip status={rule.status} />
        </div>
        <span className="rex-confidence">Confidence: {rule.confidence.toFixed(2)}</span>
      </div>
      <div className="rex-detail-tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "json"} onClick={() => onTab("json")}>Rule JSON</button>
        <button type="button" role="tab" aria-selected={tab === "source"} onClick={() => onTab("source")}>Source Text</button>
      </div>
      {tab === "json"
        ? <pre className="preview demo-code" tabIndex={0}>{jsonText}</pre>
        : <blockquote className="rex-sourcetext">{rule.sourceText}</blockquote>}
      <div className="rex-detail-source">
        <span>Source: <code>{rule.sourceRef}</code></span>
        <button type="button" className="btn small" disabled title={COMING_SOON}><Icon name="open" size={14} />Show in PDF</button>
      </div>
      <div className="rex-detail-actions">
        <button type="button" className="btn primary" disabled title={COMING_SOON}><Icon name="check" size={14} />Accept Rule</button>
        <button type="button" className="btn danger-outline" disabled title={COMING_SOON}>Reject</button>
        <button type="button" className="btn" disabled title={COMING_SOON}><Icon name="edit" size={14} />Edit JSON</button>
      </div>
    </div>
  );
}
