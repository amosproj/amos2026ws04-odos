import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import { Icon } from "../components/Icon";
import { WorkflowHeader } from "../components/WorkflowHeader";
import type { DemoResult } from "./fixtures";
import {
  ExtractionWaitError, HttpError, UnreachableError, downloadApprovedRules, extractionActive, getRuleExtraction, loadRules, previewRuleExtraction, startRuleExtraction, stopRuleExtraction, watchRuleExtraction,
  type RuleExtractionStatus, type RuleExtractionPreview,
} from "./live";
import type { DocElement } from "../types";
import type { RuleReviewEntry } from "./live";
import { useReviewActions } from "./ReviewControls";
import { RuleQueue } from "./RuleQueue";
import { Dialog, HelpContent, MoreMenu, ReviewMain, ReviewSidebar, STATUS_LABEL, ValidationFooter, ValidationHeader, reviewProgress } from "./RuleReview";
import { RuleContextPanel, type ContextTab } from "./RuleContext";
import { planHighlights, type SourceHighlight } from "./sourceMap";
import { ComponentNavContext, exceptionElements, matchComponent, type ComponentNav, type ComponentSource } from "./componentSource";
import type { HighlightGroup } from "../components/PdfViewer";
import { markOf } from "./reviewMarks";
import {
  applyReview, generatedAt, isPending, isReviewed, matchesCategory, matchesFilter, matchesSearch, overviewOf, provisionOf, queueOrder, toRuleResults,
  type QueueOrder, type ReviewFilter, type RuleCategory, type RuleItem, type RuleResults,
} from "./ruleResults";
import { useReviewerName, useRuleReviews, type ReviewApi } from "./useRuleReviews";
import "./rule-extraction.css";

/** What a failure means for the user and whether trying again can help. Keyed by the backend's stable error code; the
 *  technical reason stays in the server log and the job's status, never on screen. */
interface Explained { message: string; hint: string; retry: boolean }
const UNAVAILABLE: Explained = { message: "Finding rules is not available right now.", hint: "Please ask your administrator to check the ODOS setup, then try again.", retry: true };
const BUSY: Explained = { message: "The rule-finding service is busy or did not answer in time.", hint: "Nothing was saved. Please try again in a few minutes.", retry: true };
const TOO_LARGE: Explained = { message: "This document is too large to find all of its rules in one go.", hint: "Nothing was saved. Please try again; if it keeps happening, contact your administrator.", retry: true };
const EXPLAINED: Record<string, Explained> = {
  not_configured: UNAVAILABLE, bedrock_auth: UNAVAILABLE,
  bedrock_throttled: BUSY, bedrock_unavailable: BUSY, bedrock_timeout: BUSY, bedrock_error: BUSY, bedrock_request: BUSY, model_response: BUSY,
  too_large: TOO_LARGE, output_truncated: TOO_LARGE,
  malformed_output: { message: "Something went wrong while reading the results.", hint: "No rules were saved. Please try again.", retry: true },
  nothing_to_extract: { message: "There are no rules to find in this document.", hint: "ODOS only checks the parts of a document that contain requirements in its scope, and this document has none.", retry: false },
  invalid_scope: { message: "This document could not be prepared for finding rules.", hint: "Go back to the document and try again. If it keeps happening, upload the PDF again.", retry: true },
  result_missing: { message: "The rules were found, but they could not be loaded.", hint: "Please try again.", retry: true },
  not_found: { message: "This document is no longer available.", hint: "Go back to your documents and open it again.", retry: false },
  unreachable: { message: "ODOS could not reach the server.", hint: "Check your connection and try again.", retry: true },
};
const GENERIC: Explained = { message: "Finding rules did not work.", hint: "No rules were saved. Please try again.", retry: true };
const BY_STATUS: Record<number, string> = { 404: "not_found", 413: "too_large", 422: "invalid_scope", 503: "not_configured" };

export function explainFailure(code?: string | null, status?: number): Explained {
  return EXPLAINED[code ?? ""] ?? EXPLAINED[BY_STATUS[status ?? 0] ?? ""] ?? GENERIC;
}

/** The code of a thrown error from the API layer. */
const codeOf = (e: unknown): { code?: string; status?: number } =>
  e instanceof HttpError ? { code: e.code, status: e.status } : e instanceof UnreachableError ? { code: "unreachable" } : {};

/** Where the page is. `results` shows the job's stored `rules.json`; every other stage is about getting one. */
type Stage =
  | { kind: "checking" }
  | { kind: "ready"; notice?: string }
  | { kind: "active"; status: RuleExtractionStatus }
  | { kind: "waiting"; error: ExtractionWaitError }
  | { kind: "failed"; code?: string; status?: number }
  | { kind: "results"; notice?: string };

/** Where the reviewer was on the results: kept by the app while the page is left for Document Review ("Show in PDF") and restored
 *  when it is opened again. Only for the same job; nothing is requested to restore it. */
export interface RulesNav {
  jobId: string;
  filter: ReviewFilter;
  search: string;
  selectedId: string | null;
  /** Order of the rules and "next open rule after a decision"; absent in a place saved before they existed. */
  order?: QueueOrder;
  advance?: boolean;
  /** Rule type or structural facet chosen in the left panel; absent in a place saved before it existed. */
  category?: RuleCategory;
  /** The tab of the right panel. */
  tab?: ContextTab;
  pageScroll: number;
}

interface Props {
  result: DemoResult;
  /** The original PDF (object URL held by the app), shown beside the rules. Absent: the PDF panel says so. */
  pdfUrl?: string;
  onBack: () => void;
  onContinueToValidation?: () => void;
  /** The ODOS logo: back to the document workspace (falls back to `onBack`). */
  onHome?: () => void;
  /** Back to Document Review with this Legal JSON element selected and highlighted in the PDF. */
  onShowInPdf?: (elementId: string) => void;
  /** The job's `rules.json` as just loaded from the backend (after an extraction), so the rest of the app shows the same rules. */
  onRulesLoaded?: (rules: unknown) => void;
  /** Holds the reviewer's place across leaving and re-opening this page (owned by the app, so it outlives this component). */
  nav?: MutableRefObject<RulesNav | null>;
}

/** LLM Rule Extraction & Review: starts the backend's Amazon Bedrock extraction for the processed document, shows its
 *  progress as the backend reports it and then the Rule JSON it stored. Nothing on this page is simulated: a stored
 *  `rules.json` is shown at once without a request to the model, and an extraction only starts on an explicit click. */
export function RuleExtractionView({ result, pdfUrl, onBack, onHome, onShowInPdf, onRulesLoaded, nav, onContinueToValidation }: Props) {
  const live = result.live;
  const [stored, setStored] = useState<unknown>(live?.ruleJson ?? null); // the job's rules.json: from opening, or loaded after an extraction
  const results = useMemo(() => toRuleResults(stored), [stored]);
  const [stage, setStage] = useState<Stage>(results ? { kind: "results" } : live ? { kind: "checking" } : { kind: "ready" });
  const [confirmRestart, setConfirmRestart] = useState(false);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const starting = useRef(false); // set synchronously: a second click must not start a second paid request
  const watching = useRef<AbortController | null>(null);
  const hasStored = results !== null;
  // coming back from "Show in PDF": the rules in hand were loaded by this page before, so they are not fetched again
  const resumed = useRef(!!live && !!nav?.current && nav.current.jobId === live.jobId && results !== null);

  const rulesLoaded = useCallback((rules: unknown) => { setStored(rules); onRulesLoaded?.(rules); }, [onRulesLoaded]);

  /** Follows the extraction until it ends; loads the stored rules when it completed. Never starts anything. */
  const watch = useCallback(async (jobId: string) => {
    watching.current?.abort();
    const ctrl = new AbortController();
    watching.current = ctrl;
    try {
      const final = await watchRuleExtraction(jobId, (status) => { if (!ctrl.signal.aborted) setStage({ kind: "active", status }); }, { signal: ctrl.signal });
      if (ctrl.signal.aborted || !final) return;
      if (final.status === "cancelled") {
        setStage({ kind: "ready", notice: final.message ?? "The extraction was cancelled." });
        return;
      }
      if (final.status !== "completed") {
        setStage({ kind: "failed", code: final.errorCode ?? undefined });
        return;
      }
      const rules = await loadRules(jobId);
      if (ctrl.signal.aborted) return;
      if (rules === null) {
        setStage({ kind: "failed", code: "result_missing" });
        return;
      }
      rulesLoaded(rules);
      setStage({ kind: "results", notice: final.stopRequested ? final.message ?? "Stopped; partial results saved." : undefined });
    } catch (e) {
      if (ctrl.signal.aborted) return;
      if (e instanceof ExtractionWaitError) setStage({ kind: "waiting", error: e });
      else setStage({ kind: "failed", ...codeOf(e) });
    }
  }, [rulesLoaded]);

  // On opening: a stored result is already on screen. Ask the backend only about the state of the last extraction, so that
  // a run that is still going is picked up again and a run that finished while this page was closed is loaded.
  useEffect(() => {
    if (!live) return;
    let dead = false;
    void (async () => {
      try {
        const status = await getRuleExtraction(live.jobId);
        if (dead) return;
        if (extractionActive(status)) {
          setStage({ kind: "active", status: status! });
          void watch(live.jobId);
          return;
        }
        if (status?.status === "completed" && resumed.current && hasStored) { setStage({ kind: "results" }); return; }
        if (status?.status === "completed") {
          const rules = await loadRules(live.jobId);
          if (dead) return;
          if (rules !== null) {
            if (generatedAt(rules) !== generatedAt(live.ruleJson)) rulesLoaded(rules);
            setStage({ kind: "results" });
            return;
          }
        }
        const notice = status?.status === "failed" ? `The last attempt to find rules did not work. ${explainFailure(status.errorCode).message}`
          : status?.status === "cancelled" ? (status.message ?? "The last extraction was cancelled.")
          : undefined;
        setStage(hasStored ? { kind: "results", notice } : { kind: "ready", notice });
      } catch (e) {
        if (dead) return;
        const { code, status } = codeOf(e);
        const notice = explainFailure(code, status).message;
        setStage(hasStored ? { kind: "results", notice } : { kind: "ready", notice });
      }
    })();
    return () => { dead = true; watching.current?.abort(); };
    // only when the page opens: later changes of the rules come from this page itself
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  /** The extraction changed under this page: loads the current `rules.json`; the review state is then loaded for exactly those rules. */
  const reloadRules = useCallback(async () => {
    if (!live) return;
    const rules = await loadRules(live.jobId);
    if (rules === null) throw new Error("The result file of this job is no longer available on the server.");
    rulesLoaded(rules);
  }, [live, rulesLoaded]);

  const start = async (maxModelCalls: 1 | 3, articleIds: string[] | null) => {
    if (!live || starting.current) return;
    starting.current = true;
    setPreviewOpen(false);
    setConfirmRestart(false);
    setStage({ kind: "active", status: { status: "queued" } });
    try {
      let status: RuleExtractionStatus;
      try {
        status = await startRuleExtraction(live.jobId, maxModelCalls, articleIds);
      } catch (e) {
        if (!(e instanceof HttpError && e.status === 409)) throw e;
        status = (await getRuleExtraction(live.jobId)) ?? { status: "queued" }; // one is already queued or running: follow that one
      }
      setStage({ kind: "active", status });
      await watch(live.jobId);
    } catch (e) {
      setStage({ kind: "failed", ...codeOf(e) });
    } finally {
      starting.current = false;
    }
  };

  const cancel = async () => {
    if (!live) return;
    setConfirmCancel(false);
    try {
      const status = await stopRuleExtraction(live.jobId);
      if (stage.kind === "active") setStage({ kind: "active", status });
    } catch {
      // ignore: extraction may have finished between the click and the request
    }
  };

  return (
    <main className="workspace rex">
      <TopBar step={stage.kind === "results" ? 3 : 2} onBack={onBack} onHome={onHome ?? onBack} />

      <div className="rex-body">
        {previewOpen && live && (
          <ExtractionPreview jobId={live.jobId} onCancel={() => setPreviewOpen(false)}
                             onStart={(calls, articleIds) => void start(calls, articleIds)} />
        )}
        <div className="rex-fade" key={stage.kind}>
          {stage.kind === "checking" && <p className="rex-checking" role="status"><span className="spinner" aria-hidden="true" /> Checking for an earlier extraction…</p>}
          {stage.kind === "ready" && !previewOpen && <StartPanel result={result} notice={stage.notice} onStart={() => setPreviewOpen(true)} />}
          {stage.kind === "active" && <ProgressPanel status={stage.status} onCancel={live ? () => setConfirmCancel(true) : undefined} confirmCancel={confirmCancel} onConfirmCancel={() => void cancel()} onDismissCancel={() => setConfirmCancel(false)} />}
          {stage.kind === "waiting" && (
            <StatusPanel tone="warn" title="Still waiting for the extraction" message={stage.error.message}>
              <button type="button" className="btn primary" onClick={() => live && void watch(live.jobId)}><Icon name="refresh" size={16} />Check status</button>
              {hasStored && <button type="button" className="btn" onClick={() => setStage({ kind: "results" })}>Show previous results</button>}
            </StatusPanel>
          )}
          {stage.kind === "failed" && (() => {
            const why = explainFailure(stage.code, stage.status);
            return (
              <StatusPanel tone="error" title="Finding rules did not work" message={why.message} hint={why.hint}>
                {why.retry && <button type="button" className="btn primary" onClick={() => (hasStored ? setConfirmRestart(true) : setPreviewOpen(true))}><Icon name="refresh" size={16} />Try again</button>}
                {!why.retry && <button type="button" className="btn primary" onClick={onBack}><Icon name="back" size={16} />Back to Document</button>}
                {hasStored && <button type="button" className="btn" onClick={() => setStage({ kind: "results" })}>Show previous results</button>}
                {hasStored && confirmRestart && <RestartConfirm onConfirm={() => { setConfirmRestart(false); setPreviewOpen(true); }} onCancel={() => setConfirmRestart(false)} />}
              </StatusPanel>
            );
          })()}
          {stage.kind === "results" && results && (
            <ResultsPanel result={result} results={results} notice={stage.notice} confirmRestart={confirmRestart} canRestart={!!live}
                          onAskRestart={() => setConfirmRestart(true)} onCancelRestart={() => setConfirmRestart(false)} onRestart={() => { setConfirmRestart(false); setPreviewOpen(true); }} onShowInPdf={onShowInPdf}
                          onReloadRules={reloadRules} nav={nav} pdfUrl={pdfUrl} onBack={onBack} onContinueToValidation={onContinueToValidation}
                          ruleDownload={live && stored !== null ? live.ruleDownload : undefined} />
          )}
        </div>
      </div>
    </main>
  );
}

/** The page's header: the logo, the three steps of the workflow and help. "Document" leads back to Document Review. */
function TopBar({ step, onBack, onHome }: { step: 2 | 3; onBack: () => void; onHome: () => void }) {
  const [help, setHelp] = useState(false);
  const steps: Array<{ label: string; state: "done" | "current" | "upcoming" }> = [
    { label: "Document", state: "done" },
    { label: "Rules extracted", state: step === 3 ? "done" : "current" },
    { label: "Rule validation", state: step === 3 ? "current" : "upcoming" },
  ];
  return (
    <WorkflowHeader onHome={onHome} onBack={onBack}
                    end={<>
                      <button type="button" className="rex-icon-btn rex-help-btn" onClick={() => setHelp(true)} aria-label="Help" title="How reviewing works"><Icon name="help" size={26} /></button>
                      {help && <Dialog title="How reviewing works" onClose={() => setHelp(false)} className="small"><HelpContent /></Dialog>}
                    </>}>
      <nav className="rex-steps" aria-label="Rule extraction workflow">
        <ol>
          {steps.map((s, i) => {
            const mark = <span className="rex-step-circle">{s.state === "done" ? <Icon name="check" size={16} /> : i + 1}</span>;
            return (
              <li key={s.label} className={`rex-step ${s.state}`} aria-current={s.state === "current" ? "step" : undefined}>
                {i === 0
                  ? <button type="button" className="rex-step-link" onClick={onBack} aria-label="Back to Document Review" title="Back to Document Review">{mark}<span className="rex-step-label">{s.label}</span></button>
                  : <>{mark}<span className="rex-step-label">{s.label}</span></>}
              </li>
            );
          })}
        </ol>
      </nav>
    </WorkflowHeader>
  );
}

// ── before and during an extraction ──────────────────────────────────────────────────────────────────────────────────────

function ExtractionPreview({ jobId, onCancel, onStart }: {
  jobId: string; onCancel: () => void; onStart: (calls: 1 | 3, articleIds: string[] | null) => void;
}) {
  const [calls, setCalls] = useState<1 | 3>(1);
  const [mode, setMode] = useState<"selected" | "whole">("selected");
  const [selected, setSelected] = useState<string[]>([]);
  const [available, setAvailable] = useState<NonNullable<RuleExtractionPreview["availableArticles"]>>([]);
  const [search, setSearch] = useState("");
  const [preview, setPreview] = useState<RuleExtractionPreview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const scopeKey = JSON.stringify(mode === "selected" ? selected : null);
  useEffect(() => {
    let cancelled = false;
    setPreview(null); setError(null);
    void previewRuleExtraction(jobId, calls, JSON.parse(scopeKey) as string[] | null).then(
      value => {
        if (cancelled) return;
        setPreview(value);
        if (value.availableArticles) setAvailable(value.availableArticles);
      },
      reason => { if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason)); },
    );
    return () => { cancelled = true; };
  }, [jobId, calls, scopeKey]);
  const format = (n: number) => n.toLocaleString();
  const ready = preview && preview.maxModelCalls === calls && JSON.stringify(preview.articleIds ?? null) === scopeKey;
  const invalidate = () => { setPreview(null); setError(null); };
  const query = search.trim().toLocaleLowerCase();
  const visible = available.filter(article => `${article.number} ${article.title}`.toLocaleLowerCase().includes(query));
  const label = (article: { type: string; number: string; title: string }) =>
    `${article.type === "article" ? "Article" : "§"} ${article.number}${article.title ? ` — ${article.title}` : ""}`;
  return (
    <section className="rex-panel rex-start rex-preview" aria-label="Extraction preview">
      <h2>Extraction preview</h2>
      <p className="rex-note">This preview does not call the LLM. Extraction uses the reduced applicability input V2.</p>
      <label htmlFor="rex-scope">Document scope</label>
      <select id="rex-scope" value={mode} onChange={event => {
        invalidate(); setMode(event.target.value as "selected" | "whole");
      }}>
        <option value="selected">Choose articles / § provisions</option>
        <option value="whole">Whole document</option>
      </select>
      {mode === "selected" && <fieldset className="rex-article-picker">
        <legend>Choose articles / § provisions</legend>
        <label htmlFor="rex-article-search">Find by number or title</label>
        <input id="rex-article-search" type="search" value={search} onChange={event => setSearch(event.target.value)} />
        <div className="rex-actions">
          <button className="btn small" type="button" disabled={!available.some(a => a.eligible)} onClick={() => {
            invalidate(); setSelected(available.filter(a => a.eligible).slice(0, 100).map(a => a.id));
          }}>{available.filter(a => a.eligible).length > 100 ? "Select first 100" : "Select all eligible"}</button>
          <button className="btn small" type="button" disabled={!selected.length} onClick={() => { invalidate(); setSelected([]); }}>Clear selection</button>
          <span>{selected.length} selected</span>
        </div>
        <div className="rex-article-list">
          {visible.map(article => <label className="rex-article-option" key={article.id}>
            <input type="checkbox" checked={selected.includes(article.id)}
                   disabled={!article.eligible || (selected.length >= 100 && !selected.includes(article.id))}
                   onChange={event => {
                     const checked = event.target.checked;
                     invalidate();
                     setSelected(previous => checked ? previous.includes(article.id) ? previous : [...previous, article.id] : previous.filter(id => id !== article.id));
                   }} />
            <span>{label(article)}{!article.eligible && <small>Already accepted or manually edited; kept from previous results.</small>}</span>
          </label>)}
          {preview && !available.length && <p>No article or § provisions are available. Use Whole document for other document structures.</p>}
          {!!available.length && !visible.length && <p>No articles match your search.</p>}
        </div>
        <p className="rex-note">Only checked provisions are extraction targets. Separate requests are used when needed. Direct references may be included as context. Choose up to 100, or use Whole document.</p>
      </fieldset>}
      {mode === "whole" && <p className="rex-note">Process the whole V2 document using its normal chunks. Accepted rules and manual edits are kept, and protected parts are skipped.</p>}
      <label htmlFor="rex-call-limit">LLM calls</label>
      <select id="rex-call-limit" value={calls} onChange={event => {
        invalidate(); setCalls(Number(event.target.value) as 1 | 3);
      }}>
        <option value={1}>1 call - no corrections</option>
        <option value={3}>3 calls - up to 2 corrections</option>
      </select>
      {!preview && !error && <p role="status">Preparing preview…</p>}
      {error && <p className="alert error" role="alert">{error}</p>}
      {ready && <>
        <dl className="rex-facts">
          <div><dt>Model</dt><dd>{preview.modelId}</dd></div>
          <div><dt>Estimated initial input tokens</dt><dd>{format(preview.estimatedInitialInputTokens)}</dd></div>
          <div><dt>Previous rules kept</dt><dd>{format(preview.preservedRules ?? 0)}</dd></div>
          <div><dt>Protected targets skipped</dt><dd>{format(preview.protectedChunksSkipped ?? 0)}</dd></div>
          <div><dt>Output token ceiling for this run</dt><dd>{format(preview.maximumOutputTokens)}</dd></div>
        </dl>
        {!!preview.sampleArticles?.length && <div aria-label="Selected extraction articles">
          <h3>Selected articles / § provisions</h3>
          <ul>{preview.sampleArticles.map(article => <li key={article.id}>{label(article)}</li>)}</ul>
          <p className="rex-note">Starting extraction uses these same checked provisions.</p>
        </div>}
        <p className="rex-note">{preview.estimateNote}</p>
        {preview.blockedChunks > 0 && <p className="alert warn" role="status">Some selected text exceeds the model input limit and cannot be extracted in this run.</p>}
        <p className="rex-note">Starting extraction incurs Bedrock usage charges. Previous rules and manual edits are kept; new candidates require human review.</p>
      </>}
      {mode === "selected" && !selected.length && <p role="status">Check at least one article or § provision to start.</p>}
      {ready && !preview.canStart && (mode === "whole" || selected.length > 0) && <p role="status">This selection cannot be processed. Check protected provisions or choose a different scope.</p>}
      <div className="rex-actions">
        <button className="btn primary" type="button" disabled={!ready || !preview.canStart}
                onClick={() => onStart(calls, mode === "selected" ? selected : null)}>Start paid extraction</button>
        <button className="btn" type="button" onClick={onCancel}>Cancel</button>
      </div>
    </section>
  );
}

function StartPanel({ result, notice, onStart }: { result: DemoResult; notice?: string; onStart: () => void }) {
  const filename = result.filename ?? result.title;
  const pages = result.model.source.num_pages;
  const legal = result.live?.legal;
  const legalReady = !!legal && Array.isArray(legal.structure) && legal.structure.length > 0;
  return (
    <section className="rex-panel rex-start" aria-label="Start rule extraction">
      <div className="rex-card-head">
        <Icon name="sparkle" size={20} />
        <div>
          <p className="rex-card-title">Find Rules</p>
          <p className="rex-card-sub">Find requirements and rules in your document.</p>
        </div>
      </div>
      <dl className="rex-facts">
        <div><dt>Document</dt><dd title={filename}>{filename}</dd></div>
        <div><dt>Pages</dt><dd>{pages}</dd></div>
        <div>
          <dt>Document ready</dt>
          <dd>{legalReady ? <span className="rex-status ok"><Icon name="check" size={12} />Ready</span> : <span className="rex-status review">{legal ? "No structure to extract from" : "Not available"}</span>}</dd>
        </div>
      </dl>
      {notice && <div className="alert warn" role="status"><Icon name="info" size={14} />{notice}</div>}
      <p className="rex-note"><Icon name="info" size={14} />The reduced V2 input is split into chunks and sent to Amazon Bedrock. You can preview the size and choose the correction limit before starting this paid extraction. The result is a set of drafts that a person has to review.</p>
      <div>
        <button type="button" className="btn primary rex-start-btn" onClick={onStart} disabled={!legalReady}>
          <Icon name="sparkle" size={18} />Preview Rule Extraction
        </button>
      </div>
      {!result.live && <p className="rex-note"><Icon name="info" size={14} />This document was not processed by the ODOS backend, so rules cannot be extracted from it.</p>}
    </section>
  );
}

const seconds = (ms: number) => Math.max(0, Math.round(ms / 1000));
const clock = (total: number) => {
  const h = Math.floor(total / 3600), m = Math.floor((total % 3600) / 60), sec = total % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
};

/** The backend reports only queued / running, so the indicator is indeterminate and the numbers shown are the ones that are
 *  real: the status as the backend states it and the time since it accepted (queued) or started (running) the extraction.
 *  No stage or percentage is shown because none is reported. */
function ProgressPanel({ status, onCancel, confirmCancel, onConfirmCancel, onDismissCancel }: {
  status: RuleExtractionStatus;
  onCancel?: () => void;
  confirmCancel?: boolean;
  onConfirmCancel?: () => void;
  onDismissCancel?: () => void;
}) {
  const queued = status.status === "queued";
  const stopping = status.cancelRequested === true || status.stopRequested === true;
  const since = Date.parse((queued ? status.requestedAt : status.startedAt) ?? "");
  const known = Number.isFinite(since);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, []);
  return (
    <section className="rex-panel rex-progress" aria-label="AI Rule Extraction in Progress" aria-busy="true">
      <div className="rex-progress-head">
        <span className="rex-orb" aria-hidden="true"><Icon name="sparkle" size={22} /></span>
        <div>
          <h3 className="rex-progress-title">AI Rule Extraction in Progress</h3>
          <p className="rex-card-sub">
            {stopping
              ? "Stopping — waiting for the current model request to finish before the extraction ends."
              : queued
              ? "Your request is queued on the server and will start shortly."
              : "The document's Legal JSON has been sent to the language model, which drafts the rules. Large documents can take several minutes."}
          </p>
        </div>
      </div>
      <div className="rex-indeterminate" role="progressbar" aria-label="AI rule extraction in progress, duration unknown"><span /><span /></div>
      <dl className="rex-progress-facts">
        <div>
          <dt>Status</dt>
          <dd><span className="rex-pulse" aria-hidden="true" />{stopping ? "Stopping…" : queued ? "Queued" : "Running"}</dd>
        </div>
        <div><dt>Elapsed</dt><dd className="rex-elapsed">{known ? clock(seconds(now - since)) : "—"}</dd></div>
        {known && <div><dt>{queued ? "Requested" : "Started"}</dt><dd>{new Date(since).toLocaleTimeString()}</dd></div>}
      </dl>
      <span className="sr-only" role="status">Extraction status: {stopping ? "stopping" : queued ? "queued" : "running"}.</span>
      <p className="rex-note"><Icon name="info" size={14} />The server reports only whether the extraction is queued or running, so no percentage or processing stage is shown. You can leave this page; the extraction keeps running on the server and is picked up again when you return.</p>
      {!stopping && onCancel && (
        <div className="rex-actions">
          <button type="button" className="btn" onClick={onCancel}><Icon name="x" size={16} />Stop extraction</button>
        </div>
      )}
      {confirmCancel && onConfirmCancel && onDismissCancel && (
        <CancelConfirm onConfirm={onConfirmCancel} onCancel={onDismissCancel} />
      )}
    </section>
  );
}

function CancelConfirm({ onConfirm, onCancel }: { onConfirm: () => void; onCancel: () => void }) {
  return (
    <div className="alert warn rex-confirm" role="alertdialog" aria-labelledby="rex-cancel-title" aria-describedby="rex-cancel-text">
      <strong id="rex-cancel-title">Stop the extraction?</strong>
      <p id="rex-cancel-text">The extraction will stop after requests already in progress finish. Completed responses and previous rules are kept as a partial result. No new groups or correction requests will be started. If a request was already sent to Amazon Bedrock, it may still be charged.</p>
      <div className="rex-actions">
        <button type="button" className="btn primary" onClick={onConfirm}>Stop extraction</button>
        <button type="button" className="btn" onClick={onCancel}>Keep running</button>
      </div>
    </div>
  );
}

function StatusPanel({ tone, title, message, hint, children }: { tone: "error" | "warn"; title: string; message: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="rex-panel rex-statuspanel" aria-label={title}>
      <div className={`alert ${tone}`} role="alert">
        <strong>{title}</strong>
        <p>{message}</p>
        {hint && <p>{hint}</p>}
      </div>
      <div className="rex-actions">{children}</div>
    </section>
  );
}

function RestartConfirm({ onConfirm, onCancel }: { onConfirm: () => void; onCancel: () => void }) {
  return (
    <div className="alert warn rex-confirm" role="alertdialog" aria-labelledby="rex-confirm-title" aria-describedby="rex-confirm-text">
      <strong id="rex-confirm-title">Start a new extraction?</strong>
      <p id="rex-confirm-text">This is a paid request for the selected remaining scope. Existing rules, accepted decisions and manual edits are kept. Protected provisions are skipped and novel candidates are added as drafts. The previous results stay in place until this revision is saved.</p>
      <div className="rex-actions">
        <button type="button" className="btn primary" onClick={onConfirm}>Start new extraction</button>
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

// ── results ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

function ResultsPanel({ result, results, notice, confirmRestart, canRestart, onAskRestart, onCancelRestart, onRestart, onShowInPdf, onReloadRules, nav, pdfUrl, onBack, onContinueToValidation, ruleDownload }: {
  result: DemoResult; results: RuleResults; notice?: string; confirmRestart: boolean; canRestart: boolean;
  onAskRestart: () => void; onCancelRestart: () => void; onRestart: () => void; onShowInPdf?: (elementId: string) => void;
  onReloadRules: () => Promise<void>; nav?: MutableRefObject<RulesNav | null>;
  pdfUrl?: string; onBack: () => void; onContinueToValidation?: () => void; ruleDownload?: { href: string; name: string };
}) {
  const jobId = result.live?.jobId;
  const saved = nav?.current && nav.current.jobId === jobId ? nav.current : null; // the place this reviewer left (same job only)
  const [filter, setFilter] = useState<ReviewFilter>(saved?.filter ?? "all");
  const [search, setSearch] = useState(saved?.search ?? "");
  const [order, setOrder] = useState<QueueOrder>(saved?.order ?? "flagged"); // rules with a potential issue first
  const [advance, setAdvance] = useState(saved?.advance ?? true);
  const [overview, setOverview] = useState(false);
  const [category, setCategory] = useState<RuleCategory>(saved?.category ?? "all");
  const [tab, setTab] = useState<ContextTab>(saved?.tab ?? "pdf");
  const [page, setPage] = useState(1); // the PDF panel's page
  const [selectedId, setSelectedId] = useState<string | null>(saved?.selectedId ?? null);
  // a rule that was just decided (with "next open rule" off) or that met a conflict stays in the sequence until the reviewer moves
  // on, so its new state and any message about it do not vanish with it when a filter is on
  const [pinned, setPinned] = useState<string | null>(null);
  const select = useCallback((id: string) => { setPinned(null); setSelectedId(id); }, []);
  const [exportState, setExportState] = useState<{ busy: boolean; error: string | null }>({ busy: false, error: null });
  // the review state is bound to the extraction of the rules on screen (`_generation.generatedAt`), never to rule IDs alone
  const { api, reload, setEntry } = useRuleReviews(jobId, results.generation?.generatedAt ?? null);
  const [reviewer, setReviewer] = useReviewerName();
  // the extracted records stay as they are; the reviewers' decisions (when the backend keeps them) are applied on top
  const view = useMemo<RuleResults>(() => (api.kind === "ready" ? { ...results, items: results.items.map((r) => applyReview(r, api.data.rules[r.id])) } : results), [results, api]);
  const ov = useMemo(() => overviewOf(view), [view]);
  const elements = useMemo(() => new Map(result.model.elements.map((e) => [e.id, e])), [result.model]);
  const provisionById = useMemo(() => new Map(view.items.map((r) => [r.id, provisionOf(r, elements)])), [view.items, elements]);

  const reviewedCount = view.items.filter(isReviewed).length;
  const filters: ReviewFilter[] = api.kind === "ready" ? ["all", "pending", "accepted", "rejected", "edited", "flagged"]
    : reviewedCount ? ["all", "pending", "flagged", "reviewed"] : ["all", "pending", "flagged"];
  const activeFilter = filters.includes(filter) ? filter : "all"; // a filter that is not offered now (e.g. a saved "Accepted") does not hide everything
  // the order in which Previous / Next walk the rules: all rules (or those of the filter chosen in the overview)
  const sequence = useMemo(() => queueOrder(view.items.filter((r) => ((matchesFilter(r, activeFilter) && matchesCategory(r, category)) || r.id === pinned) && matchesSearch(r, search)), order),
                           [view, activeFilter, category, search, order, pinned]);

  // the selection: on opening, the first rule that waits for a decision (once the decisions are known); when the selected rule
  // leaves the sequence (a filter is on), the rule that now stands at its place
  const lastIndex = useRef(-1);
  useEffect(() => {
    const at = sequence.findIndex((r) => r.id === selectedId);
    if (at >= 0) { lastIndex.current = at; return; }
    if (lastIndex.current < 0) {
      if (api.kind === "loading") return;
      lastIndex.current = 0;
      setSelectedId((sequence.find(isPending) ?? sequence[0])?.id ?? null);
      return;
    }
    setSelectedId(sequence[Math.min(lastIndex.current, sequence.length - 1)]?.id ?? null);
  }, [sequence, selectedId, api.kind]);
  const selected = useMemo(() => sequence.find((r) => r.id === selectedId) ?? (lastIndex.current < 0 ? sequence[0] ?? null : null), [sequence, selectedId]);
  const position = selected ? sequence.indexOf(selected) + 1 : 0;
  const move = useCallback((by: number) => {
    const next = sequence[position - 1 + by];
    if (next) select(next.id);
  }, [sequence, position, select]);

  // ← and → go to the previous and next rule, unless the reviewer is typing or a dialog is open
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (overview || e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      const t = e.target as HTMLElement | null;
      if (t?.closest?.("input, textarea, select, [contenteditable], [role='dialog'], [role='menu']")) return;
      e.preventDefault();
      move(e.key === "ArrowLeft" ? -1 : 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [move, overview]);

  /** After an accepted or rejected decision: on to the next rule that still waits for one (when the reviewer wants that). */
  const onDecided = (ruleId: string) => {
    const at = sequence.findIndex((r) => r.id === ruleId);
    const next = advance ? [...sequence.slice(at + 1), ...sequence.slice(0, Math.max(at, 0))].find((r) => r.id !== ruleId && isPending(r)) : undefined;
    if (next) select(next.id);
    else setPinned(ruleId); // staying: the decided rule remains in the sequence with its new state
  };

  // remember the place (the page scroll position is kept by the listener below)
  useEffect(() => {
    if (!nav || !jobId) return;
    nav.current = { pageScroll: 0, ...(nav.current?.jobId === jobId ? nav.current : {}), jobId, filter, search, selectedId, order, advance, category, tab };
  }, [nav, jobId, filter, search, selectedId, order, advance, category, tab]);

  // the PDF panel follows the selected rule: every passage it cites, highlighted by what it means and outlined by the rule's review
  // state, starting on the first page of its primary passage. The viewer stays mounted, so the document is not loaded again; a rule
  // that names no passage of this document leaves the page where it is.
  const numPages = result.model.source.num_pages;
  const plan = useMemo(() => (selected ? planHighlights(selected, result.model) : []), [selected, result.model]);
  const showSource = useCallback((elementId: string) => {
    const h = plan.find((x) => x.elementId === elementId);
    if (h?.page) setPage(h.page);
  }, [plan]);
  const selectedKey = selected?.id ?? null;
  useEffect(() => {
    const first = plan.find((h) => h.role === "primary" && h.element) ?? plan.find((h) => h.element);
    if (first?.page) setPage(first.page);
    // only when another rule is selected: a decision on the same rule must not move the PDF
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedKey]);
  const mark = selected ? markOf(selected) : null;
  // a part of the rule (requirement, exception, definition …) whose wording verifiably matches one cited passage
  const [focused, setFocused] = useState<ComponentSource | null>(null);
  useEffect(() => setFocused(null), [selectedKey]);
  const excIds = useMemo(() => (selected ? exceptionElements(selected, result.model) : new Set<string>()), [selected, result.model]);
  const componentNav = useMemo<ComponentNav>(() => {
    const cache = new Map<string, ComponentSource | null>();
    return {
      resolve: (text) => {
        if (!selected || !text) return null;
        if (!cache.has(text)) cache.set(text, matchComponent(text, selected, result.model));
        return cache.get(text) ?? null;
      },
      go: (src) => { setTab("pdf"); if (src.page) setPage(src.page); setFocused(src); },
      focused,
    };
  }, [selected, result.model, focused]);
  const groups = useMemo<HighlightGroup[]>(() => plan.filter((h) => h.element && h.boxes.length).map((h) => ({
    boxes: h.boxes, tone: h.role === "primary" && excIds.has(h.elementId) ? "exception" : h.tone, focus: focused?.elementId === h.elementId, approximate: h.approximate || h.precision === "fallback", status: h.role === "context" || h.role === "cross_reference" ? undefined : mark?.state,
    edited: !!mark?.edited && h.role === "primary",
    title: `${h.label}${h.sentenceLabel ? ` · ${h.sentenceLabel}` : ""}: ${h.precision === "element" ? "exactly the cited text" : "whole element (the cited sentence's position is not in the document data)"}`,
  })), [plan, mark?.state, mark?.edited, excIds, focused]);
  const goToSource = useCallback((elementId: string) => { setTab("pdf"); setFocused(null); showSource(elementId); }, [showSource]);
  useEffect(() => {
    if (!nav || !jobId) return;
    const onScroll = () => { if (nav.current?.jobId === jobId) nav.current.pageScroll = window.scrollY; };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [nav, jobId]);
  const restored = useRef(false);
  useLayoutEffect(() => { // once the page has its usual height (the review state is in), put the scroll position back
    if (restored.current || api.kind === "loading") return;
    restored.current = true;
    if (saved) window.scrollTo?.(0, saved.pageScroll);
  }, [api.kind, saved]);

  const download = async () => {
    if (!jobId || exportState.busy) return;
    setExportState({ busy: true, error: null });
    try { await downloadApprovedRules(jobId); setExportState({ busy: false, error: null }); }
    catch (e) { setExportState({ busy: false, error: e instanceof Error ? e.message : String(e) }); }
  };

  const countOf = (f: ReviewFilter) => view.items.filter((r) => matchesFilter(r, f) && matchesCategory(r, category)).length;
  const countAll = (f: ReviewFilter) => view.items.filter((r) => matchesFilter(r, f)).length;
  const categoryLabel = category === "all" ? null : category.startsWith("type:") ? category.slice(5).replace(/_/g, " ") : category.slice(4);
  const scope = activeFilter !== "all" || search.trim() || categoryLabel
    ? [categoryLabel, activeFilter !== "all" ? STATUS_LABEL[activeFilter] : null, search.trim() ? `“${search.trim()}”` : null].filter(Boolean).join(", ") : null;
  const filename = result.filename ?? result.title;
  const progress = reviewProgress(ov, api);
  const onFilter = (f: ReviewFilter) => { setPinned(null); setFilter(f); };
  const onCategory = (c: RuleCategory) => { setPinned(null); setCategory(c); };

  return (
    <section className="rex-results rv" aria-label="Extracted rules">
      <ValidationHeader filename={filename} numPages={numPages} total={ov.total} decided={progress.decided} />
      {confirmRestart && <RestartConfirm onConfirm={onRestart} onCancel={onCancelRestart} />}
      {exportState.error && <div className="alert error" role="alert">The approved rules were not downloaded: {exportState.error}</div>}
      {api.kind === "stale" && !api.unidentified && <StaleBanner onReload={onReloadRules} />}
      {notice && <div className="alert warn" role="status"><Icon name="info" size={14} />{notice}</div>}
      {results.skipped > 0 && <div className="alert warn" role="status"><Icon name="info" size={14} />{results.skipped} record{results.skipped === 1 ? " in the result file is" : "s in the result file are"} not valid Rule JSON 2.0 and cannot be shown.</div>}

      {ov.total === 0 ? (
        <div className="rex-empty-detail rex-noresults" role="status">
          <Icon name="info" size={20} /><span>The extraction completed but produced no rules for this document.</span>
        </div>
      ) : (
        <div className="rex-layout rv-layout">
          <ReviewSidebar ov={ov} api={api} items={view.items} category={category} onCategory={onCategory} filters={filters} filter={activeFilter} onFilter={onFilter} countOf={countOf}
                         onOverview={() => setOverview(true)} exporting={exportState.busy} onDownload={() => void download()} ruleDownload={ruleDownload}
                         menu={(
                           <MoreMenu>
                             {(close) => (
                               <button type="button" role="menuitem" disabled={!canRestart || confirmRestart} onClick={() => { close(); onAskRestart(); }}
                                       title={canRestart ? "Run the extraction again (paid request, asks for confirmation)" : "Needs the ODOS backend"}>
                                 <Icon name="refresh" size={14} />Restart Extraction
                               </button>
                             )}
                           </MoreMenu>
                         )} />
          {selected ? (
            <ComponentNavContext.Provider value={componentNav}>
            <RuleView key={selected.id} rule={selected} position={position} count={sequence.length} scope={scope} onPrevious={() => move(-1)} onNext={() => move(1)}
                      elements={elements} numPages={numPages} onShowInPdf={onShowInPdf} onGoToSource={goToSource} jobId={jobId} api={api} reviewer={reviewer} onReviewer={setReviewer}
                      onEntry={setEntry} onReload={reload} onDecided={onDecided} onConflict={setPinned} highlights={plan} />
            </ComponentNavContext.Provider>
          ) : (
            <div className="rex-main rex-empty-detail" role="status">
              <Icon name="info" size={20} /><span>No rules match the chosen filter. <button type="button" className="btn small" onClick={() => { setFilter("all"); setCategory("all"); setSearch(""); }}>Show all rules</button></span>
            </div>
          )}
          <RuleContextPanel tab={tab} onTab={setTab} pdfUrl={pdfUrl} page={page} onPage={setPage} groups={groups} plan={plan} mark={mark} rule={selected} exceptionIds={excIds} focused={focused} />
        </div>
      )}
      <ValidationFooter decided={progress.decided} total={progress.total} percent={progress.percent} onBack={onBack} onContinue={onContinueToValidation} />

      {overview && (
        <Dialog title="Rule list" onClose={() => setOverview(false)} className="wide">
          <RuleQueue items={sequence} selectedId={selected?.id ?? null} onSelect={(id) => { select(id); setOverview(false); }} filters={filters} activeFilter={activeFilter}
                     onFilter={onFilter} countOf={countAll} search={search} onSearch={(q) => { setPinned(null); setSearch(q); }}
                     order={order} onOrder={setOrder} advance={advance} onAdvance={setAdvance} canAdvance={api.kind === "ready"} provisionOf={(r) => provisionById.get(r.id) ?? null} />
        </Dialog>
      )}
    </section>
  );
}

/** One rule on screen: its review state (the hook belongs to the rule, so nothing typed for one rule reaches another). */
function RuleView({ rule, jobId, api, reviewer, onEntry, onReload, onDecided, onConflict, ...card }: {
  rule: RuleItem; position: number; count: number; scope: string | null; onPrevious: () => void; onNext: () => void;
  elements: Map<string, DocElement>; numPages: number; onShowInPdf?: (elementId: string) => void; onGoToSource?: (elementId: string) => void;
  highlights: SourceHighlight[];
  jobId: string | undefined; api: ReviewApi; reviewer: string; onReviewer: (name: string) => void;
  onEntry: (ruleId: string, entry: RuleReviewEntry) => void; onReload: () => Promise<void>; onDecided: (ruleId: string) => void; onConflict: (ruleId: string) => void;
}) {
  const review = useReviewActions({ jobId: jobId ?? "", rule, api: jobId ? api : { kind: "unavailable", reason: null }, reviewer: jobId ? reviewer : "", onEntry, onReload, onDecided, onConflict });
  return <ReviewMain rule={rule} review={review} reviewer={reviewer} {...card} />;
}

/** The rules on screen are not the job's current extraction (another run replaced `rules.json`): review is off until they are reloaded. */
function StaleBanner({ onReload }: { onReload: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const reload = async () => {
    setBusy(true);
    setError(null);
    try { await onReload(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };
  return (
    <div className="alert warn rex-stale" role="alert">
      <Icon name="info" size={14} />
      <div>
        <strong>The extraction has changed.</strong>
        <p>Another extraction has replaced the rules of this job since this page loaded them. Review actions are disabled until the current results are loaded; nothing on this page can be accepted, rejected or edited.</p>
        {error && <p>{error}</p>}
        <button type="button" className="btn primary small" disabled={busy} onClick={() => void reload()}><Icon name="refresh" size={14} />Reload results</button>
      </div>
    </div>
  );
}
