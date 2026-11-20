import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import { Icon } from "../components/Icon";
import { JsonViewer } from "../components/JsonViewer";
import { Logo } from "../components/Logo";
import { TYPE_LABELS, fullText } from "../structure";
import type { DocElement } from "../types";
import type { DemoResult } from "./fixtures";
import {
  ExtractionWaitError, HttpError, downloadApprovedRules, extractionActive, getRuleExtraction, loadRules, startRuleExtraction, watchRuleExtraction,
  type RuleExtractionStatus, type RuleReviewEntry,
} from "./live";
import { ReviewControls } from "./ReviewControls";
import {
  applyReview, generatedAt, isReviewed, matchesFilter, matchesSearch, overviewOf, pagesLabel, reviewLabel, toRuleResults, validPages,
  type ReviewFilter, type RuleItem, type RuleResults,
} from "./ruleResults";
import { useReviewerName, useRuleReviews, type ReviewApi } from "./useRuleReviews";
import "./rule-extraction.css";

type DetailTab = "json" | "source";

const FILTER_LABEL: Record<ReviewFilter, string> = { all: "All Rules", pending: "Pending Review", accepted: "Accepted", rejected: "Rejected", flagged: "Flagged by Checks", reviewed: "Reviewed" };
const TOO_LARGE_CODES = new Set(["too_large", "output_truncated"]);

/** Where the page is. `results` shows the job's stored `rules.json`; every other stage is about getting one. */
type Stage =
  | { kind: "checking" }
  | { kind: "ready"; notice?: string }
  | { kind: "active"; status: RuleExtractionStatus }
  | { kind: "waiting"; error: ExtractionWaitError }
  | { kind: "failed"; message: string; code?: string }
  | { kind: "results"; notice?: string };

/** Where the reviewer was on the results: kept by the app while the page is left for Document Review ("Show in PDF") and restored
 *  when it is opened again. Only for the same job; nothing is requested to restore it. */
export interface RulesNav {
  jobId: string;
  filter: ReviewFilter;
  search: string;
  selectedId: string | null;
  tab: DetailTab;
  listScroll: number;
  pageScroll: number;
}

interface Props {
  result: DemoResult;
  onBack: () => void;
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
export function RuleExtractionView({ result, onBack, onShowInPdf, onRulesLoaded, nav }: Props) {
  const live = result.live;
  const [stored, setStored] = useState<unknown>(live?.ruleJson ?? null); // the job's rules.json: from opening, or loaded after an extraction
  const results = useMemo(() => toRuleResults(stored), [stored]);
  const [stage, setStage] = useState<Stage>(results ? { kind: "results" } : live ? { kind: "checking" } : { kind: "ready" });
  const [confirmRestart, setConfirmRestart] = useState(false);
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
      if (final.status !== "completed") {
        setStage({ kind: "failed", message: final.message ?? "The rule extraction failed.", code: final.errorCode ?? undefined });
        return;
      }
      const rules = await loadRules(jobId);
      if (ctrl.signal.aborted) return;
      if (rules === null) {
        setStage({ kind: "failed", message: "The extraction finished, but its result file is not available on the server." });
        return;
      }
      rulesLoaded(rules);
      setStage({ kind: "results" });
    } catch (e) {
      if (ctrl.signal.aborted) return;
      if (e instanceof ExtractionWaitError) setStage({ kind: "waiting", error: e });
      else setStage({ kind: "failed", message: e instanceof Error ? e.message : String(e) });
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
        const notice = status?.status === "failed" ? `The last extraction failed: ${status.message ?? "no reason reported."}` : undefined;
        setStage(hasStored ? { kind: "results", notice } : { kind: "ready", notice });
      } catch (e) {
        if (dead) return;
        const notice = e instanceof Error ? e.message : undefined;
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

  const start = async () => {
    if (!live || starting.current) return;
    starting.current = true;
    setConfirmRestart(false);
    setStage({ kind: "active", status: { status: "queued" } });
    try {
      let status: RuleExtractionStatus;
      try {
        status = await startRuleExtraction(live.jobId);
      } catch (e) {
        if (!(e instanceof HttpError && e.status === 409)) throw e;
        status = (await getRuleExtraction(live.jobId)) ?? { status: "queued" }; // one is already queued or running: follow that one
      }
      setStage({ kind: "active", status });
      await watch(live.jobId);
    } catch (e) {
      setStage({ kind: "failed", message: e instanceof Error ? e.message : String(e) });
    } finally {
      starting.current = false;
    }
  };

  const filename = result.filename ?? result.title;
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
        <div className="rex-fade" key={stage.kind}>
          {stage.kind === "checking" && <p className="rex-checking" role="status"><span className="spinner" aria-hidden="true" /> Checking for an earlier extraction…</p>}
          {stage.kind === "ready" && <StartPanel result={result} notice={stage.notice} onStart={() => void start()} />}
          {stage.kind === "active" && <ProgressPanel status={stage.status} />}
          {stage.kind === "waiting" && (
            <StatusPanel tone="warn" title="Still waiting for the extraction" message={stage.error.message}>
              <button type="button" className="btn primary" onClick={() => live && void watch(live.jobId)}><Icon name="refresh" size={16} />Check status</button>
              {hasStored && <button type="button" className="btn" onClick={() => setStage({ kind: "results" })}>Show previous results</button>}
            </StatusPanel>
          )}
          {stage.kind === "failed" && (
            <StatusPanel tone="error" title="Rule extraction failed" message={stage.message} code={stage.code}
                         hint={stage.code && TOO_LARGE_CODES.has(stage.code) ? "The whole document is sent in one request. Choosing individual provisions is not available in this interface yet." : undefined}>
              <button type="button" className="btn primary" onClick={() => (hasStored ? setConfirmRestart(true) : void start())}><Icon name="refresh" size={16} />Try again</button>
              {hasStored && <button type="button" className="btn" onClick={() => setStage({ kind: "results" })}>Show previous results</button>}
              {hasStored && confirmRestart && <RestartConfirm onConfirm={() => void start()} onCancel={() => setConfirmRestart(false)} />}
            </StatusPanel>
          )}
          {stage.kind === "results" && results && (
            <ResultsPanel result={result} results={results} notice={stage.notice} confirmRestart={confirmRestart} canRestart={!!live}
                          onAskRestart={() => setConfirmRestart(true)} onCancelRestart={() => setConfirmRestart(false)} onRestart={() => void start()} onShowInPdf={onShowInPdf}
                          onReloadRules={reloadRules} nav={nav} />
          )}
        </div>
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
      </ol>
    </nav>
  );
}

// ── before and during an extraction ──────────────────────────────────────────────────────────────────────────────────────

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
          <p className="rex-card-title">LLM Rule Extraction</p>
          <p className="rex-card-sub">Extract draft compliance rules from this document with Amazon Bedrock.</p>
        </div>
      </div>
      <dl className="rex-facts">
        <div><dt>Document</dt><dd title={filename}>{filename}</dd></div>
        <div><dt>Pages</dt><dd>{pages}</dd></div>
        <div>
          <dt>Legal JSON</dt>
          <dd>{legalReady ? <span className="rex-status ok"><Icon name="check" size={12} />Ready</span> : <span className="rex-status review">{legal ? "No structure to extract from" : "Not available"}</span>}</dd>
        </div>
      </dl>
      {notice && <div className="alert warn" role="status"><Icon name="info" size={14} />{notice}</div>}
      <p className="rex-note"><Icon name="info" size={14} />The Legal JSON of the whole document is sent to Amazon Bedrock. This is a paid request and can take several minutes. The result is a set of drafts that a person has to review.</p>
      <div>
        <button type="button" className="btn primary rex-start-btn" onClick={onStart} disabled={!legalReady}>
          <Icon name="sparkle" size={18} />Start Rule Extraction
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
function ProgressPanel({ status }: { status: RuleExtractionStatus }) {
  const queued = status.status === "queued";
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
            {queued
              ? "Your request is queued on the server and will start shortly."
              : "The document's Legal JSON has been sent to the language model, which drafts the rules. Large documents can take several minutes."}
          </p>
        </div>
      </div>
      <div className="rex-indeterminate" role="progressbar" aria-label="AI rule extraction in progress, duration unknown"><span /><span /></div>
      <dl className="rex-progress-facts">
        <div>
          <dt>Status</dt>
          <dd><span className="rex-pulse" aria-hidden="true" />{queued ? "Queued" : "Running"}</dd>
        </div>
        <div><dt>Elapsed</dt><dd className="rex-elapsed">{known ? clock(seconds(now - since)) : "—"}</dd></div>
        {known && <div><dt>{queued ? "Requested" : "Started"}</dt><dd>{new Date(since).toLocaleTimeString()}</dd></div>}
      </dl>
      <span className="sr-only" role="status">Extraction status: {queued ? "queued" : "running"}.</span>
      <p className="rex-note"><Icon name="info" size={14} />The server reports only whether the extraction is queued or running, so no percentage or processing stage is shown. You can leave this page; the extraction keeps running on the server and is picked up again when you return.</p>
      <p className="rex-note"><Icon name="lock" size={14} />A running extraction cannot be cancelled yet: the backend has no safe way to stop a request that is already with the model.</p>
    </section>
  );
}

function StatusPanel({ tone, title, message, code, hint, children }: { tone: "error" | "warn"; title: string; message: string; code?: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="rex-panel rex-statuspanel" aria-label={title}>
      <div className={`alert ${tone}`} role="alert">
        <strong>{title}</strong>
        <p>{message}</p>
        {hint && <p>{hint}</p>}
        {code && <p className="rex-code">Code: <code>{code}</code></p>}
      </div>
      <div className="rex-actions">{children}</div>
    </section>
  );
}

function RestartConfirm({ onConfirm, onCancel }: { onConfirm: () => void; onCancel: () => void }) {
  return (
    <div className="alert warn rex-confirm" role="alertdialog" aria-labelledby="rex-confirm-title" aria-describedby="rex-confirm-text">
      <strong id="rex-confirm-title">Start a new extraction?</strong>
      <p id="rex-confirm-text">The document is sent to Amazon Bedrock again, which is a paid request. The results below stay in place until the new extraction has succeeded; a failed one does not replace them.</p>
      <div className="rex-actions">
        <button type="button" className="btn primary" onClick={onConfirm}>Start new extraction</button>
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

// ── results ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

function ResultsPanel({ result, results, notice, confirmRestart, canRestart, onAskRestart, onCancelRestart, onRestart, onShowInPdf, onReloadRules, nav }: {
  result: DemoResult; results: RuleResults; notice?: string; confirmRestart: boolean; canRestart: boolean;
  onAskRestart: () => void; onCancelRestart: () => void; onRestart: () => void; onShowInPdf?: (elementId: string) => void;
  onReloadRules: () => Promise<void>; nav?: MutableRefObject<RulesNav | null>;
}) {
  const jobId = result.live?.jobId;
  const saved = nav?.current && nav.current.jobId === jobId ? nav.current : null; // the place this reviewer left (same job only)
  const [filter, setFilter] = useState<ReviewFilter>(saved?.filter ?? "all");
  const [search, setSearch] = useState(saved?.search ?? "");
  const [selectedId, setSelectedId] = useState<string | null>(saved?.selectedId ?? results.items[0]?.id ?? null);
  const [detailTab, setDetailTab] = useState<DetailTab>(saved?.tab ?? "json");
  const listRef = useRef<HTMLDivElement>(null);
  const [exportState, setExportState] = useState<{ busy: boolean; error: string | null }>({ busy: false, error: null });
  // the review state is bound to the extraction of the rules on screen (`_generation.generatedAt`), never to rule IDs alone
  const { api, reload, setEntry } = useRuleReviews(jobId, results.generation?.generatedAt ?? null);
  const [reviewer, setReviewer] = useReviewerName();
  // the extracted records stay as they are; the reviewers' decisions (when the backend keeps them) are applied on top
  const view = useMemo<RuleResults>(() => (api.kind === "ready" ? { ...results, items: results.items.map((r) => applyReview(r, api.data.rules[r.id])) } : results), [results, api]);
  const ov = useMemo(() => overviewOf(view), [view]);
  const elements = useMemo(() => new Map(result.model.elements.map((e) => [e.id, e])), [result.model]);

  const reviewedCount = view.items.filter(isReviewed).length;
  const filters: ReviewFilter[] = api.kind === "ready" ? ["all", "pending", "accepted", "rejected", "flagged"]
    : reviewedCount ? ["all", "pending", "flagged", "reviewed"] : ["all", "pending", "flagged"];
  const activeFilter = filters.includes(filter) ? filter : "all"; // a filter that is not offered now (e.g. a saved "Accepted") does not hide everything
  const filtered = useMemo(() => view.items.filter((r) => matchesFilter(r, activeFilter) && matchesSearch(r, search)), [view, activeFilter, search]);
  useEffect(() => {
    if (!filtered.some((r) => r.id === selectedId)) setSelectedId(filtered[0]?.id ?? null);
  }, [filtered, selectedId]);
  const selected = useMemo(() => view.items.find((r) => r.id === selectedId) ?? null, [view, selectedId]);

  // remember the place (the scroll positions are kept by the listeners below)
  useEffect(() => {
    if (!nav || !jobId) return;
    nav.current = { listScroll: 0, pageScroll: 0, ...(nav.current?.jobId === jobId ? nav.current : {}), jobId, filter, search, selectedId, tab: detailTab };
  }, [nav, jobId, filter, search, selectedId, detailTab]);
  useEffect(() => {
    if (!nav || !jobId) return;
    const onScroll = () => { if (nav.current?.jobId === jobId) nav.current.pageScroll = window.scrollY; };
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [nav, jobId]);
  const restored = useRef(false);
  useLayoutEffect(() => { // once the page has its usual height (the review state is in), put the scroll positions back
    if (restored.current || api.kind === "loading") return;
    restored.current = true;
    if (!saved) return;
    if (listRef.current) listRef.current.scrollTop = saved.listScroll;
    window.scrollTo?.(0, saved.pageScroll);
  }, [api.kind, saved]);

  const download = async () => {
    if (!jobId || exportState.busy) return;
    setExportState({ busy: true, error: null });
    try { await downloadApprovedRules(jobId); setExportState({ busy: false, error: null }); }
    catch (e) { setExportState({ busy: false, error: e instanceof Error ? e.message : String(e) }); }
  };

  const countOf = (f: ReviewFilter) => view.items.filter((r) => matchesFilter(r, f)).length;
  const { generation } = results;

  return (
    <section className="rex-panel rex-results" aria-label="Extracted rules">
      <div className="rex-main-head">
        <div>
          <div className="rex-main-title"><Icon name="sparkle" size={20} />Extracted Rules</div>
          <p className="rex-main-sub">
            Draft Rule JSON extracted by an LLM; none of it is a legal compliance decision until a person has reviewed it.
            {generation?.modelId && <> Model: <code>{generation.modelId}</code>{generation.generatedAt ? ` · ${new Date(generation.generatedAt).toLocaleString()}` : ""}.</>}
          </p>
        </div>
        <div className="rex-main-actions">
          {api.kind === "ready" && jobId && (
            <button type="button" className="btn" disabled={api.data.counts.accepted === 0 || exportState.busy} onClick={() => void download()}
                    title={api.data.counts.accepted > 0 ? "The accepted rules as Rule JSON 2.0 (status approved); rejected and pending rules are not included" : "No rule has been accepted yet"}>
              <Icon name="open" size={16} />Download approved rules{api.data.counts.accepted > 0 ? ` (${api.data.counts.accepted})` : ""}
            </button>
          )}
          <button type="button" className="btn" onClick={onAskRestart} disabled={!canRestart || confirmRestart} title={canRestart ? "Run the extraction again (paid request, asks for confirmation)" : "Needs the ODOS backend"}>
            <Icon name="refresh" size={16} />Restart Extraction
          </button>
        </div>
      </div>
      {confirmRestart && <RestartConfirm onConfirm={onRestart} onCancel={onCancelRestart} />}
      {exportState.error && <div className="alert error" role="alert">The approved rules were not downloaded: {exportState.error}</div>}
      {api.kind === "stale" && !api.unidentified && <StaleBanner onReload={onReloadRules} />}
      {notice && <div className="alert warn" role="status"><Icon name="info" size={14} />{notice}</div>}
      {results.skipped > 0 && <div className="alert warn" role="status"><Icon name="info" size={14} />{results.skipped} record{results.skipped === 1 ? " in the result file is" : "s in the result file are"} not valid Rule JSON 2.0 and cannot be shown.</div>}

      <Overview ov={ov} results={view} api={api} />

      {ov.total === 0 ? (
        <div className="rex-empty-detail rex-noresults" role="status">
          <Icon name="info" size={20} /><span>The extraction completed but produced no rules for this document.</span>
        </div>
      ) : (
        <>
          <div className="rex-filters">
            <div className="rex-tabs" role="group" aria-label="Filter rules">
              {filters.map((f) => (
                <button key={f} type="button" className="btn small" aria-pressed={activeFilter === f} onClick={() => setFilter(f)}>{FILTER_LABEL[f]} ({countOf(f)})</button>
              ))}
            </div>
            <label className="rex-search">
              <Icon name="search" size={14} />
              <input type="search" placeholder="Search rules…" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Search rules" />
            </label>
          </div>

          <div className="rex-split">
            <div className="rex-list" role="listbox" aria-label="Extracted rules" ref={listRef}
                 onScroll={(e) => { if (nav?.current && nav.current.jobId === jobId) nav.current.listScroll = e.currentTarget.scrollTop; }}>
              {filtered.length === 0 && <p className="rex-empty">No rules match this filter.</p>}
              {filtered.map((r) => (
                <button key={r.id} type="button" role="option" aria-selected={r.id === selectedId}
                        className={`rex-rule${r.id === selectedId ? " selected" : ""}`}
                        onClick={() => { setSelectedId(r.id); setDetailTab("json"); }}>
                  <span className="rex-rule-main">
                    <span className="rex-rule-title">{r.title}</span>
                    <span className="rex-rule-id">{r.id}</span>
                  </span>
                  <StatusChip rule={r} />
                </button>
              ))}
            </div>
            <RuleDetail rule={selected} tab={detailTab} onTab={setDetailTab} elements={elements} numPages={result.model.source.num_pages} onShowInPdf={onShowInPdf}
                        jobId={jobId} api={api} reviewer={reviewer} onReviewer={setReviewer} onEntry={setEntry} onReload={reload} />
          </div>
        </>
      )}
    </section>
  );
}

/** The counts of the stored result, in two groups that are never mixed: what people have decided (nothing yet: the backend
 *  stores no decisions) and what ODOS's automated checks found. A rule without a flag is not "verified". */
function Overview({ ov, results, api }: { ov: ReturnType<typeof overviewOf>; results: RuleResults; api: ReviewApi }) {
  const g = results.generation;
  const reviewed = ov.reviewed + ov.approved;
  const ready = api.kind === "ready";
  return (
    <div className="rex-overview">
      <div className="rex-overview-head">
        <div>
          <p className="rex-card-title">Extraction Overview</p>
          <p className="rex-card-sub">Counts from the stored result. No score or percentage is estimated.</p>
        </div>
        <Stat value={ov.total} label="Extracted Rules" />
      </div>
      <div className="rex-groups">
        <section className="rex-group" aria-label="Human review">
          <p className="rex-group-title"><Icon name="user" size={14} />Human review</p>
          {ready ? (
            <>
              <div className="rex-stats">
                <Stat value={ov.pending} label="Pending Review" tone="warn" />
                <Stat value={ov.accepted} label="Accepted" tone="accent" />
                <Stat value={ov.rejected} label="Rejected" tone="danger" />
                <Stat value={ov.edited} label="Edited" />
              </div>
              {ov.total > 0 && (
                <div className="rex-bar" role="img" aria-label={`${ov.accepted} accepted, ${ov.rejected} rejected and ${ov.pending} pending of ${ov.total} rules`}>
                  <span className="rex-bar-auto" style={{ flexGrow: ov.accepted }} />
                  <span className="rex-bar-rejected" style={{ flexGrow: ov.rejected }} />
                  <span className="rex-bar-review" style={{ flexGrow: ov.pending }} />
                </div>
              )}
              <p className="rex-note"><Icon name="info" size={14} />Decisions are saved in the ODOS database with the reviewer's name and kept in an audit trail. The extracted rules are never changed.</p>
              {api.data.earlierExtractionEvents > 0 && <p className="rex-note"><Icon name="info" size={14} />{api.data.earlierExtractionEvents} decision event{api.data.earlierExtractionEvents === 1 ? "" : "s"} from earlier extractions {api.data.earlierExtractionEvents === 1 ? "is" : "are"} kept in the history and not applied to these rules.</p>}
            </>
          ) : api.kind === "stale" ? (
            <>
              <div className="rex-stats"><Stat value={ov.total} label="Rules on this page" /></div>
              <p className="rex-note"><Icon name="lock" size={14} />{api.unidentified
                ? "These rules carry no extraction identifier, so no review decisions are shown or accepted for them."
                : "The review decisions on the server belong to a newer extraction than the rules on this page, so none are shown here. Reload the results."}</p>
            </>
          ) : (
            <>
              <div className="rex-stats">
                <Stat value={ov.pending} label="Pending Review" tone="warn" />
                <Stat value={reviewed} label={`Reviewed or Approved${ov.approved ? ` (${ov.approved} approved)` : ""}`} tone="accent" />
              </div>
              {ov.total > 0 && (
                <div className="rex-bar" role="img" aria-label={`${ov.pending} of ${ov.total} rules pending review, ${reviewed} reviewed or approved`}>
                  <span className="rex-bar-auto" style={{ flexGrow: reviewed }} />
                  <span className="rex-bar-review" style={{ flexGrow: ov.total - reviewed }} />
                </div>
              )}
              <p className="rex-note"><Icon name="lock" size={14} />Review decisions are not stored yet, so human rejections cannot be counted.</p>
            </>
          )}
        </section>
        <section className="rex-group" aria-label="Automated ODOS checks">
          <p className="rex-group-title"><Icon name="info" size={14} />Automated ODOS checks</p>
          <div className="rex-stats">
            <Stat value={ov.flagged} label="Flagged by ODOS Checks" hint="Rules kept as drafts with a note from an automated check" />
            <Stat value={ov.autoRejected} label="Refused by ODOS Checks" hint="Candidates the checks refused; they are not in the rule list" />
            {g?.repaired !== undefined && <Stat value={g.repaired} label="Repaired by Schema Repair" hint="Records whose form was repaired along the schema" />}
            {g?.coverage && <Stat value={`${g.coverage.sentencesCited} of ${g.coverage.sentences}`} label="Sentences Cited by a Rule" hint="Normative sentences that some rule cites as its primary source" />}
          </div>
          <p className="rex-note"><Icon name="info" size={14} />The checks cover form, units, numbers and sources. A rule without a flag is not verified as correct, and a refused or flagged one is not a human decision.</p>
          {ov.autoRejected > 0 && (
            <details className="rex-rejected">
              <summary>Show candidates refused by automated checks</summary>
              <ul>{results.autoRejected.map((r, i) => <li key={`${r.id}-${i}`}><code>{r.id}</code>{r.reasons.map((reason, j) => <span key={j} className="rex-reason">{reason}</span>)}</li>)}</ul>
            </details>
          )}
        </section>
      </div>
    </div>
  );
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

function Stat({ value, label, tone, hint }: { value: number | string; label: string; tone?: "accent" | "warn" | "danger"; hint?: string }) {
  return (
    <div className="rex-stat" title={hint}>
      <span className="rex-stat-value">{typeof value === "number" ? <span className={tone}>{value}</span> : value}</span>
      <span className="rex-stat-label">{label}</span>
    </div>
  );
}

function StatusChip({ rule }: { rule: RuleItem }) {
  // with stored decisions the chip shows the reviewer's decision; without them, the status written in the file
  const label = rule.human ? ({ pending: "Pending Review", accepted: "Accepted", rejected: "Rejected" } as const)[rule.human] : reviewLabel(rule.reviewStatus);
  const tone = rule.human === "accepted" || isReviewed(rule) ? "auto" : rule.human === "rejected" ? "flag" : "review";
  return (
    <span className="rex-chips">
      <span className={`rex-status ${tone}`}>{tone === "auto" ? <Icon name="check" size={12} /> : <Icon name="user" size={12} />}{label}</span>
      {rule.edited && <span className="rex-status ok" title="A reviewer edited this rule; the extracted record is kept unchanged">Edited</span>}
      {rule.checkFlags.length > 0 && <span className="rex-status flag" title="ODOS's automated checks flagged this rule">Flagged</span>}
    </span>
  );
}

/** How a source reference of a rule reads: the document element it names (null when the opened document has none with that
 *  ID) and its pages. Pages come from the rule itself, else from the element; invalid ones are dropped, never guessed. */
function describeSource(s: RuleItem["sources"][number], elements: Map<string, DocElement>, numPages: number) {
  const e = elements.get(s.elementId) ?? null;
  const own = validPages(s.pdfPages, numPages);
  const pages = own.length ? own : e ? validPages(e.pages, numPages) : [];
  const name = e ? `${TYPE_LABELS[e.type] ?? e.type} ${e.marker ?? ""}`.trim() : s.elementId;
  return { e, pages, name, pagesText: pagesLabel(pages) };
}

function RuleDetail({ rule, tab, onTab, elements, numPages, onShowInPdf, jobId, api, reviewer, onReviewer, onEntry, onReload }: {
  rule: RuleItem | null; tab: DetailTab; onTab: (t: DetailTab) => void; elements: Map<string, DocElement>; numPages: number; onShowInPdf?: (elementId: string) => void;
  jobId: string | undefined; api: ReviewApi; reviewer: string; onReviewer: (name: string) => void; onEntry: (ruleId: string, entry: RuleReviewEntry) => void; onReload: () => Promise<void>;
}) {
  const [jsonView, setJsonView] = useState<"effective" | "original">("effective");
  useEffect(() => setJsonView("effective"), [rule?.id]);
  if (!rule) return <div className="rex-detail rex-empty-detail"><Icon name="info" size={20} /><span>Select a rule to see its details.</span></div>;
  const refs = rule.sources.map((s) => ({ s, ...describeSource(s, elements, numPages) }));
  const first = refs.find((r) => r.e);
  const canShow = !!first && !!onShowInPdf;
  const showTitle = canShow ? "Open this source in Document Review, highlighted in the PDF" : "This rule names no source element that is part of this document";
  return (
    <div className="rex-detail">
      <div className="rex-detail-head">
        <div className="rex-detail-title">
          <strong>{rule.title}</strong>
          <StatusChip rule={rule} />
        </div>
        <span className="rex-detail-id">{rule.id}</span>
      </div>
      <div className="rex-detail-tabs" role="tablist">
        <button type="button" role="tab" aria-selected={tab === "json"} onClick={() => onTab("json")}>Rule JSON</button>
        <button type="button" role="tab" aria-selected={tab === "source"} onClick={() => onTab("source")}>Source Text</button>
      </div>
      {tab === "json" && rule.edited && (
        <div className="rex-jsonview" role="group" aria-label="Which version of the rule to show">
          <button type="button" className="btn small" aria-pressed={jsonView === "effective"} onClick={() => setJsonView("effective")}>Edited (in force)</button>
          <button type="button" className="btn small" aria-pressed={jsonView === "original"} onClick={() => setJsonView("original")}>Extracted (original)</button>
        </div>
      )}
      {tab === "json"
        ? <JsonViewer value={jsonView === "original" ? rule.rule : rule.effective} label={rule.edited ? (jsonView === "original" ? "Extracted Rule JSON" : "Edited Rule JSON") : "Rule JSON"} />
        : <SourceTexts rule={rule} elements={elements} numPages={numPages} onShowInPdf={onShowInPdf} />}
      <div className="rex-refs" aria-label="Source references">
        <div className="rex-detail-source">
          <span className="rex-refs-citation">Source:{" "}
            {rule.citation
              ? (canShow
                ? <button type="button" className="rex-citation" onClick={() => first && onShowInPdf?.(first.s.elementId)} title={`Show ${rule.citation} in the PDF`}>{rule.citation}</button>
                : <code>{rule.citation}</code>)
              : "—"}
          </span>
          <button type="button" className="btn small" disabled={!canShow} onClick={() => first && onShowInPdf?.(first.s.elementId)} title={showTitle}>
            <Icon name="open" size={14} />Show in PDF
          </button>
        </div>
        {refs.length > 0 && (
          <ul className="rex-ref-list">
            {refs.map(({ s, e, name, pagesText }) => (
              <li key={`${s.elementId}-${s.sentenceId ?? ""}`}>
                <button type="button" className="rex-ref" disabled={!e || !onShowInPdf} onClick={() => onShowInPdf?.(s.elementId)}
                        title={e ? `Show ${name} in the PDF` : "This element is not part of the opened document"}>
                  <Icon name={e ? "open" : "info"} size={12} />{name}{pagesText ? ` · ${pagesText}` : ""}
                </button>
              </li>
            ))}
          </ul>
        )}
        {refs.length === 0 && <p className="rex-note"><Icon name="info" size={14} />This rule names no source element, so it cannot be shown in the PDF.</p>}
        {refs.length > 0 && !first && <p className="rex-note"><Icon name="info" size={14} />None of this rule's source elements is part of the opened document, so it cannot be shown in the PDF.</p>}
      </div>
      <ReviewInfo rule={rule} />
      {jobId
        ? <ReviewControls jobId={jobId} rule={rule} api={api} reviewer={reviewer} onReviewer={onReviewer} onEntry={onEntry} onReload={onReload} />
        : <ReviewControls jobId="" rule={rule} api={{ kind: "unavailable", reason: null }} reviewer="" onReviewer={() => {}} onEntry={() => {}} onReload={async () => {}} />}
    </div>
  );
}

function SourceTexts({ rule, elements, numPages, onShowInPdf }: { rule: RuleItem; elements: Map<string, DocElement>; numPages: number; onShowInPdf?: (elementId: string) => void }) {
  if (!rule.sources.length) return <p className="rex-empty">This rule names no source element.</p>;
  return (
    <ul className="rex-sources">
      {rule.sources.map((s) => {
        const { e, pagesText, name } = describeSource(s, elements, numPages);
        return (
          <li key={`${s.elementId}-${s.sentenceId ?? ""}`}>
            <div className="rex-source-head">
              <span>{e ? name : "Unknown element"}{s.role ? ` · ${s.role}` : ""}</span>
              <span className="rex-source-pages">{pagesText}</span>
            </div>
            {e
              ? <blockquote className="rex-sourcetext">{fullText(e) || <em>(no text)</em>}</blockquote>
              : <p className="rex-empty">This element is not part of the opened document.</p>}
            <div className="rex-source-foot">
              <code>{s.elementId}{s.sentenceId ? ` · ${s.sentenceId}` : ""}</code>
              {e && onShowInPdf && <button type="button" className="btn small" onClick={() => onShowInPdf(s.elementId)}><Icon name="open" size={14} />Show in PDF</button>}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function ReviewInfo({ rule }: { rule: RuleItem }) {
  const any = rule.checkFlags.length || rule.ambiguities.length || rule.notes.length || rule.machineCheckable !== null;
  if (!any) return null;
  return (
    <div className="rex-reviewinfo">
      <p className="rex-card-title">Review information</p>
      {rule.machineCheckable !== null && <p className="rex-note">Machine-checkable: {rule.machineCheckable ? "yes" : "no"}</p>}
      {rule.checkFlags.length > 0 && <><p className="rex-reviewinfo-h">Flagged by ODOS checks</p><ul>{rule.checkFlags.map((f, i) => <li key={i}>{f}</li>)}</ul></>}
      {rule.ambiguities.length > 0 && <><p className="rex-reviewinfo-h">Ambiguities noted by the model</p><ul>{rule.ambiguities.map((f, i) => <li key={i}>{f}</li>)}</ul></>}
      {rule.notes.length > 0 && <><p className="rex-reviewinfo-h">Notes</p><ul>{rule.notes.map((f, i) => <li key={i}>{f}</li>)}</ul></>}
    </div>
  );
}
