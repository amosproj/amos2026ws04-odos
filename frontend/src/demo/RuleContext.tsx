// The right panel of Rule Validation: the document context of the selected rule, as two tabs. "PDF Preview" is the existing PDF
// viewer with the rule's source passage highlighted (element-level highlighting, as in Document Review); it stays mounted while
// rules change or the other tab is open, so the document is loaded once. "Rule JSON" is the selected rule's Rule JSON 2.0
// record exactly as stored (an instance, not the schema), with the extracted version beside an edited one.
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Icon, type IconName } from "../components/Icon";
import { JsonViewer } from "../components/JsonViewer";
import { PdfViewer, type HighlightGroup } from "../components/PdfViewer";
import { STATE_LABEL, type ReviewMark } from "./reviewMarks";
import { TONE_LABEL, type SourceHighlight, type Tone } from "./sourceMap";
import type { RuleItem } from "./ruleResults";
import type { ComponentSource } from "./componentSource";

export type ContextTab = "pdf" | "json";
const TABS: Array<{ id: ContextTab; label: string; icon: IconName }> = [
  { id: "pdf", label: "PDF Preview", icon: "file" },
  { id: "json", label: "Rule JSON", icon: "braces" },
];

interface Props {
  tab: ContextTab;
  onTab: (tab: ContextTab) => void;
  pdfUrl?: string;
  page: number;
  onPage: (page: number) => void;
  groups: HighlightGroup[];
  /** The rule's cited passages (what the highlights are and how precisely they can be drawn). */
  plan: SourceHighlight[];
  /** The rule's persisted review state, or null when the backend keeps none. */
  mark: ReviewMark | null;
  rule: RuleItem | null;
  /** Cited elements whose whole text is one of the rule's exceptions (coloured as exceptions). */
  exceptionIds?: Set<string>;
  /** The part of the rule the reviewer navigated to. */
  focused?: ComponentSource | null;
}

export function RuleContextPanel({ tab, onTab, pdfUrl, page, onPage, groups, plan, mark, rule, exceptionIds, focused }: Props) {
  const tabRefs = useRef<Record<ContextTab, HTMLButtonElement | null>>({ pdf: null, json: null });
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight" && e.key !== "Home" && e.key !== "End") return;
    e.preventDefault();
    e.stopPropagation(); // the page's ←/→ (previous / next rule) must not fire while the tabs have focus
    const at = TABS.findIndex((t) => t.id === tab);
    const next = e.key === "Home" ? 0 : e.key === "End" ? TABS.length - 1 : (at + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length;
    onTab(TABS[next].id);
    tabRefs.current[TABS[next].id]?.focus();
  };
  return (
    <aside className="rv-context" aria-label="Document context">
      <div className="rv-tabs" role="tablist" aria-label="Document context" onKeyDown={onKey}>
        {TABS.map((t) => (
          <button key={t.id} ref={(el) => { tabRefs.current[t.id] = el; }} type="button" role="tab" id={`rv-tab-${t.id}`} aria-controls={`rv-panel-${t.id}`}
                  aria-selected={tab === t.id} tabIndex={tab === t.id ? 0 : -1} className={tab === t.id ? "active" : undefined} onClick={() => onTab(t.id)}>
            <Icon name={t.icon} size={18} />{t.label}
          </button>
        ))}
      </div>
      <div className="rv-panels">
        {/* kept mounted (only made invisible) so the PDF is not loaded again and keeps its width, page and zoom */}
        <div role="tabpanel" id="rv-panel-pdf" aria-labelledby="rv-tab-pdf" className={`rv-panel rv-pdf${tab === "pdf" ? "" : " rv-panel-off"}`} inert={tab !== "pdf"} aria-hidden={tab !== "pdf" || undefined}>
          {pdfUrl ? (
            <>
              <PdfViewer url={pdfUrl} page={page} onPageChange={onPage} highlights={[]} groups={groups} />
              <HighlightLegend plan={plan} mark={mark} exceptionIds={exceptionIds} focused={focused ?? null} />
            </>
          ) : (
            <p className="rv-empty"><Icon name="info" size={16} />The original PDF is not available on this page. “View in document” opens the passage in Document Review.</p>
          )}
        </div>
        <div role="tabpanel" id="rv-panel-json" aria-labelledby="rv-tab-json" className="rv-panel rv-json" hidden={tab !== "json"}>
          {/* rendered only while open: the JSON is not part of the default view */}
          {tab === "json" && (rule ? <RuleJson key={rule.id} rule={rule} /> : <p className="rv-empty"><Icon name="info" size={16} />No rule is selected.</p>)}
        </div>
      </div>
    </aside>
  );
}

/** The record of the selected rule as stored. With an edit: the edited record (in force) or the extracted one, never a mix. */
function RuleJson({ rule }: { rule: RuleItem }) {
  const [version, setVersion] = useState<"effective" | "original">("effective");
  useEffect(() => setVersion("effective"), [rule.id]);
  return (
    <div className="rv-json-body">
      <p className="rex-muted rex-small">The Rule JSON 2.0 record of this rule exactly as stored: an instance of the schema, not the schema itself.</p>
      {rule.edited && (
        <div className="rex-jsonview" role="group" aria-label="Which version of the rule to show">
          <button type="button" className="btn small" aria-pressed={version === "effective"} onClick={() => setVersion("effective")}>Edited (in force)</button>
          <button type="button" className="btn small" aria-pressed={version === "original"} onClick={() => setVersion("original")}>Extracted (original)</button>
        </div>
      )}
      <JsonViewer value={version === "original" ? rule.rule : rule.effective} label={rule.edited ? (version === "original" ? "Extracted Rule JSON" : "Edited Rule JSON") : "Rule JSON"} />
    </div>
  );
}

/** What the highlights on the page are: their meaning (fill), how precisely each is drawn, and the rule's review state (outline). */
function HighlightLegend({ plan, mark, exceptionIds, focused }: { plan: SourceHighlight[]; mark: ReviewMark | null; exceptionIds?: Set<string>; focused: ComponentSource | null }) {
  const shown = plan.filter((h) => h.element);
  if (shown.length === 0) return <p className="rv-pdf-note">This rule names no passage of the opened document, so nothing is highlighted.</p>;
  const tones = [...new Set(shown.map((h) => (h.role === "primary" && exceptionIds?.has(h.elementId) ? "exception" : h.tone)))] as Tone[];
  const fallback = shown.filter((h) => h.precision === "fallback");
  const direct = shown.filter((h) => h.tone !== "context").length;
  const related = shown.length - direct;
  return (
    <div className="rv-pdf-note rv-legend">
      <ul aria-label="Highlight colours">
        {tones.map((t) => <li key={t}><span className={`rv-tonedot tone-${t}`} aria-hidden="true" />{TONE_LABEL[t]}</li>)}
        {mark && mark.state !== "pending" && <li className={`rv-legend-status ${mark.state}`}><span className="rv-statusdot" aria-hidden="true" />{STATE_LABEL[mark.state]} (side bar)</li>}
        {mark?.edited && <li className="rv-legend-edited"><span className="rv-editline" aria-hidden="true" />Edited (underline)</li>}
      </ul>
      {related > 0 && <p className="rv-legend-precision">{direct} direct source{direct === 1 ? "" : "s"} (solid) · {related} related passage{related === 1 ? "" : "s"} the rule cites as context (dashed, fainter).</p>}
      {focused && (
        <p className="rv-legend-precision rv-legend-focus"><span className="rv-focusdot" aria-hidden="true" />Selected: {focused.citation} —{" "}
          {focused.precision === "exact" ? "exactly this passage." : "its whole element is ringed; the sentence's position on the page is not in the document data."}</p>
      )}
      <p className="rv-legend-precision">
        {fallback.length === 0
          ? "Highlighted: exactly the cited text."
          : `Highlighted: whole element${fallback.length > 1 ? "s" : ""} (${fallback.map((h) => `${h.label}${h.sentenceLabel ? `, ${h.sentenceLabel}` : ""}`).join("; ")}) — not sentence-precise: ${fallback[0].reason}.`}
      </p>
    </div>
  );
}
