import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type MutableRefObject } from "react";
import { Icon } from "../components/Icon";
import { StopConfirm } from "../components/StopConfirm";
import { Logo } from "../components/Logo";
import type { DemoResult } from "./fixtures";
import {
  ExtractionWaitError, HttpError, cancelRuleExtraction, downloadApprovedRules, extractionActive, friendlyExtractionMessage, getRuleExtraction, loadRules, ruleStep, sectionProgress, startRuleExtraction, watchRuleExtraction, RULE_STEPS,
  type RuleExtractionStatus,
} from "./live";
import type { DocElement } from "../types";
import type { RuleReviewEntry } from "./live";
import { useReviewActions } from "./ReviewControls";
import { FILTER_LABEL, RuleQueue } from "./RuleQueue";
import { AdvancedDetails, Dialog, HelpContent, MoreMenu, ReviewMain, ReviewSidebar } from "./RuleReview";
import {
  applyReview, generatedAt, isPending, isReviewed, matchesFilter, matchesSearch, overviewOf, provisionCoverage, provisionOf, queueOrder, toRuleResults,
  type QueueOrder, type ReviewFilter, type RuleItem, type RuleResults,
} from "./ruleResults";
import { useReviewerName, useRuleReviews, type ReviewApi } from "./useRuleReviews";
import "./rule-extraction.css";

const TOO_LARGE_CODES = new Set(["too_large", "output_truncated"]);

/** The screen from before this run. `held` keeps Find Rules unavailable while the cancelled run is still finishing. */
function rested(hasResults: boolean, held = false, error?: string): Stage {
  return hasResults ? { kind: "results", holding: held, notice: error } : { kind: "ready", held, error };
}

const resting = (stage: Stage) => (stage.kind === "ready" && !!stage.held) || (stage.kind === "results" && !!stage.holding);

/** Where the page is. `results` shows the job's stored `rules.json`; every other stage is about getting one. */
type Stage =
  | { kind: "checking" }
  | { kind: "ready"; notice?: string; held?: boolean; error?: string }
  | { kind: "active"; status: RuleExtractionStatus }
  | { kind: "waiting"; error: ExtractionWaitError }
  | { kind: "failed"; message: string; code?: string }
  | { kind: "results"; notice?: string; holding?: boolean };

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
  /** Advanced details open. */
  advanced?: boolean;
  pageScroll: number;
}

interface Props {
  result: DemoResult;
  onBack: () => void;
  /** Document list. Does not cancel a running extraction. */
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
export function RuleExtractionView({ result, onBack, onHome, onShowInPdf, onRulesLoaded, nav }: Props) {
  const live = result.live;
  const [stored, setStored] = useState<unknown>(live?.ruleJson ?? null); // the job's rules.json: from opening, or loaded after an extraction
  const results = useMemo(() => toRuleResults(stored), [stored]);
  const [stage, setStage] = useState<Stage>(results ? { kind: "results" } : live ? { kind: "checking" } : { kind: "ready" });
  const [confirmRestart, setConfirmRestart] = useState(false);
  const starting = useRef(false); // set synchronously: a second click must not start a second paid request
  const holdRef = useRef(false); // a cancel was accepted; late polls must not bring the progress view back
  const restarting = useRef(false); // the user clicked Find Rules again and is waiting until the cancelled run has ended
  const watching = useRef<AbortController | null>(null);
  const hasStored = results !== null;
  const hasStoredRef = useRef(hasStored);
  hasStoredRef.current = hasStored;
  // coming back from "Show in PDF": the rules in hand were loaded by this page before, so they are not fetched again
  const resumed = useRef(!!live && !!nav?.current && nav.current.jobId === live.jobId && results !== null);

  const rulesLoaded = useCallback((rules: unknown) => { setStored(rules); onRulesLoaded?.(rules); }, [onRulesLoaded]);

  /** Follows the extraction until it ends; loads the stored rules when it completed. Never starts anything. */
  const watch = useCallback(async (jobId: string) => {
    watching.current?.abort();
    const ctrl = new AbortController();
    watching.current = ctrl;
    try {
      const final = await watchRuleExtraction(jobId, (status) => {
        if (ctrl.signal.aborted || restarting.current) return;
        if (!extractionActive(status) && status.status === "cancelled") {
          holdRef.current = false;
          setStage(rested(hasStoredRef.current, false));
          return;
        }
        setStage((current) => {
          // a poll that started before Cancel must not bring the progress view back, and must not disable Find Rules
          if ((holdRef.current || resting(current)) && extractionActive(status)) return rested(hasStoredRef.current, false);
          if (!extractionActive(status)) return current;
          return { kind: "active", status };
        });
      }, { signal: ctrl.signal });
      if (ctrl.signal.aborted || restarting.current || !final) return;
      if (final.status === "cancelled") {
        setStage(rested(hasStoredRef.current, false));
        return;
      }
      if (final.status !== "completed") {
        setStage({ kind: "failed", message: friendlyExtractionMessage(final.message, final.errorCode), code: final.errorCode ?? undefined });
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
      if (ctrl.signal.aborted || holdRef.current) return; // the hold poll below keeps checking; a missed poll is not a new failure
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
          holdRef.current = !!status!.cancelRequested;
          setStage(status!.cancelRequested ? rested(hasStored, false) : { kind: "active", status: status! });
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
        const notice = status?.status === "failed" ? `The last attempt failed: ${friendlyExtractionMessage(status.message, status.errorCode)}` : undefined;
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

  // The watch above is aborted when this page is left or replaced. This poll belongs to the hold itself, so the
  // start button comes back once the backend reports a terminal status even if that watch already stopped.
  const holding = (stage.kind === "ready" && !!stage.held) || (stage.kind === "results" && !!stage.holding);
  useEffect(() => {
    if (!holding || !live) return;
    let dead = false;
    let ticket = 0;
    const poll = async () => {
      const mine = ++ticket;
      try {
        const status = await getRuleExtraction(live.jobId);
        if (dead || mine !== ticket || restarting.current || extractionActive(status)) return;
        holdRef.current = false;
        if (status?.status === "completed") {
          const rules = await loadRules(live.jobId);
          if (dead || mine !== ticket) return;
          if (rules !== null) { rulesLoaded(rules); setStage({ kind: "results" }); return; }
        }
        if (status?.status === "failed") {
          setStage({ kind: "failed", message: friendlyExtractionMessage(status.message, status.errorCode), code: status.errorCode ?? undefined });
          return;
        }
        setStage(rested(hasStoredRef.current, false));
      } catch { /* the next tick tries again; the button stays disabled while the run may still be active */ }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 2000);
    return () => { dead = true; window.clearInterval(timer); };
  }, [holding, live, rulesLoaded]);

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
    restarting.current = true;
    holdRef.current = false;
    setConfirmRestart(false);
    setStage({ kind: "active", status: { status: "queued" } });
    try {
      let status: RuleExtractionStatus;
      for (;;) {
        try {
          status = await startRuleExtraction(live.jobId);
          break;
        } catch (e) {
          if (!(e instanceof HttpError && e.status === 409)) throw e;
          status = (await getRuleExtraction(live.jobId)) ?? { status: "queued" };
          // a run the user did not cancel is already the one to follow; a cancelled run has to finish before a new one can start
          if (!(extractionActive(status) && status.cancelRequested)) break;
          await new Promise((r) => setTimeout(r, 1000));
        }
      }
      restarting.current = false;
      setStage({ kind: "active", status });
      await watch(live.jobId);
    } catch (e) {
      setStage({ kind: "failed", message: friendlyExtractionMessage(e instanceof Error ? e.message : String(e)) });
    } finally {
      restarting.current = false;
      starting.current = false;
    }
  };

  const cancel = async () => {
    if (!live) return;
    holdRef.current = true;
    setStage(rested(hasStoredRef.current, false));
    try {
      const status = await cancelRuleExtraction(live.jobId);
      if (!extractionActive(status)) holdRef.current = false;
      if (!restarting.current) setStage(rested(hasStoredRef.current, false));
    } catch (e) {
      if (e instanceof HttpError && e.status === 409) return; // it already finished; the watch shows that result
      const message = e instanceof Error ? e.message : String(e);
      setStage(rested(hasStoredRef.current, false, message));
    }
  };

  return (
    <main className="workspace rex">
      <TopBar step={stage.kind === "results" ? 3 : 2} onBack={onBack} onHome={onHome} />

      <div className="rex-body">
        <div className="rex-fade" key={stage.kind}>
          {stage.kind === "checking" && <p className="rex-checking" role="status"><span className="spinner" aria-hidden="true" /> Checking for an earlier extraction…</p>}
          {stage.kind === "ready" && <StartPanel result={result} notice={stage.notice} held={stage.held} error={stage.error} onRetry={() => void cancel()} onStart={() => void start()} />}
          {stage.kind === "active" && <ProgressPanel status={stage.status} onCancel={() => void cancel()} />}
          {stage.kind === "waiting" && (
            <StatusPanel tone="warn" title="Still waiting for the extraction" message={stage.error.message}>
              <button type="button" className="btn primary" onClick={() => live && void watch(live.jobId)}><Icon name="refresh" size={16} />Check status</button>
              {hasStored && <button type="button" className="btn" onClick={() => setStage({ kind: "results" })}>Show previous results</button>}
            </StatusPanel>
          )}
          {stage.kind === "failed" && (
            <StatusPanel tone="error" title="Finding rules failed" message={stage.message} code={stage.code}
                         hint={stage.code && TOO_LARGE_CODES.has(stage.code) ? "This document is read in one pass, so a shorter document is needed." : undefined}>
              <button type="button" className="btn primary" onClick={() => (hasStored ? setConfirmRestart(true) : void start())}><Icon name="refresh" size={16} />Try again</button>
              {hasStored && <button type="button" className="btn" onClick={() => setStage({ kind: "results" })}>Show previous results</button>}
              {hasStored && confirmRestart && <RestartConfirm onConfirm={() => void start()} onCancel={() => setConfirmRestart(false)} />}
            </StatusPanel>
          )}
          {stage.kind === "results" && results && (
            <ResultsPanel result={result} results={results} notice={stage.notice} confirmRestart={confirmRestart} canRestart={!!live && !stage.holding}
                          onAskRestart={() => setConfirmRestart(true)} onCancelRestart={() => setConfirmRestart(false)} onRestart={() => void start()} onShowInPdf={onShowInPdf}
                          onReloadRules={reloadRules} nav={nav} />
          )}
        </div>
      </div>
    </main>
  );
}

/** The page's header: the logo, the three steps of the workflow and help. "Document" leads back to Document Review. */
function TopBar({ step, onBack, onHome }: { step: 2 | 3; onBack: () => void; onHome?: () => void }) {
  const [help, setHelp] = useState(false);
  const steps: Array<{ label: string; state: "done" | "current" | "upcoming" }> = [
    { label: "Document", state: "done" },
    { label: "Rules extracted", state: step === 3 ? "done" : "current" },
    { label: "Review", state: step === 3 ? "current" : "upcoming" },
  ];
  return (
    <header className="rex-top">
      <button type="button" className="brand-link" onClick={onHome} disabled={!onHome} aria-label="ODOS home"><Logo compact /></button>
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
      <div className="rex-top-actions">
        <button type="button" className="btn rex-back" onClick={onBack}><Icon name="back" size={16} />Back to document review</button>
        <button type="button" className="rex-icon-btn rex-help-btn" onClick={() => setHelp(true)} aria-label="Help" title="How reviewing works"><Icon name="help" size={26} /></button>
      </div>
      {help && <Dialog title="How reviewing works" onClose={() => setHelp(false)} className="small"><HelpContent /></Dialog>}
    </header>
  );
}

// ── before and during an extraction ──────────────────────────────────────────────────────────────────────────────────────

function StartPanel({ result, notice, held, error, onRetry, onStart }: { result: DemoResult; notice?: string; held?: boolean; error?: string; onRetry?: () => void; onStart: () => void }) {
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
          <p className="rex-card-sub">Look through this document for draft rules. You review every rule before it is used.</p>
        </div>
      </div>
      <dl className="rex-facts">
        <div><dt>Document</dt><dd title={filename}>{filename}</dd></div>
        <div><dt>Pages</dt><dd>{pages}</dd></div>
        <div>
          <dt>Document</dt>
          <dd>{legalReady ? <span className="rex-status ok"><Icon name="check" size={12} />Ready</span> : <span className="rex-status review">{legal ? "Nothing to read" : "Not available"}</span>}</dd>
        </div>
      </dl>
      {notice && <div className="alert warn" role="status"><Icon name="info" size={14} />{notice}</div>}
      <p className="rex-note"><Icon name="info" size={14} />This can take several minutes and may cost money. Every rule stays a draft until you review it.</p>
      <details className="rex-advanced">
        <summary>Advanced</summary>
        <p>The prepared document is read in one request. It is not split into sections. Cancel stops that request and discards its answer. Work the model has already started may still be charged. Documents you already finished, and rules you already reviewed, stay as they are.</p>
      </details>
      <div>
        <button type="button" className="btn primary rex-start-btn" onClick={onStart} disabled={!legalReady || !!held}>
          <Icon name="sparkle" size={18} />Find Rules
        </button>
        {error && <button type="button" className="btn" onClick={onRetry}>Try again</button>}
      </div>
      {error && <div className="alert error" role="alert"><p>{error}</p></div>}
      {!result.live && <p className="rex-note"><Icon name="info" size={14} />This document is not available from the server, so rules cannot be found in it.</p>}
    </section>
  );
}

const seconds = (ms: number) => Math.max(0, Math.round(ms / 1000));
const clock = (total: number) => {
  const h = Math.floor(total / 3600), m = Math.floor((total % 3600) / 60), sec = total % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
};

const RULE_STEP_TEXT = ["Preparing your document", "Finding rules", "Checking results", "Ready for review"] as const;

/** Steps follow the backend stage. The bar stays indeterminate: there is no percentage and, in this build, no section count. */
function ProgressPanel({ status, onCancel }: { status: RuleExtractionStatus; onCancel: () => void }) {
  const step = ruleStep(status);
  const stopping = step < 0;
  const title = stopping ? "Stopping…" : RULE_STEP_TEXT[step] ?? "Finding rules";
  const sections = sectionProgress(status);
  const since = Date.parse((status.status === "queued" ? status.requestedAt : status.startedAt) ?? status.requestedAt ?? "");
  const known = Number.isFinite(since);
  const [now, setNow] = useState(() => Date.now());
  const [confirm, setConfirm] = useState(false);
  useEffect(() => {
    if (stopping) return; // the counter must not keep running after the user has asked to stop
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, [stopping]);
  if (stopping) {
    return <p className="rex-note" role="status">Stopping the request. Its answer will not be used.</p>;
  }
  return (
    <section className="rex-panel rex-progress" aria-label="Finding rules" aria-busy="true">
      <div className="rex-progress-head">
        <span className="rex-orb" aria-hidden="true"><Icon name="sparkle" size={22} /></span>
        <div>
          <h3 className="rex-progress-title">{title}</h3>
          <p className="rex-card-sub">{stopping
            ? "Stopping the request. Its answer will not be used."
            : step >= 3 ? "Opening the rules for review." : `Next: ${RULE_STEP_TEXT[Math.min(step + 1, RULE_STEP_TEXT.length - 1)].toLowerCase()}.`}</p>
        </div>
      </div>
      <ol className="flow">
        {RULE_STEPS.map((name, index) => {
          const state = stopping ? "" : index < step ? "done" : index === step ? "current" : "";
          return <li key={name} className={state} aria-current={state === "current" ? "step" : undefined}><i aria-hidden="true" />{name}</li>;
        })}
      </ol>
      {sections && <p className="rex-note" role="status">{sections}</p>}
      <div className="rex-indeterminate" role="progressbar" aria-label={title} aria-valuetext={sections ?? title}><span /><span /></div>
      <dl className="rex-progress-facts">
        <div><dt>Elapsed</dt><dd className="rex-elapsed">{known ? clock(seconds(now - since)) : "—"}</dd></div>
      </dl>
      <span className="sr-only" role="status">{title}.</span>
      {!stopping && <p className="rex-note"><Icon name="info" size={14} />You can leave this page. Finding rules continues until you cancel it.</p>}
      {!stopping && (
        <div className="flow-actions">
          <button type="button" className="btn" onClick={() => setConfirm(true)}>Cancel</button>
        </div>
      )}
      {confirm && <StopConfirm onKeep={() => setConfirm(false)} onStop={() => { setConfirm(false); onCancel(); }} />}
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
        {code && <details className="rex-advanced"><summary>Advanced</summary><p className="rex-code">Code: <code>{code}</code></p></details>}
      </div>
      <div className="rex-actions">{children}</div>
    </section>
  );
}

function RestartConfirm({ onConfirm, onCancel }: { onConfirm: () => void; onCancel: () => void }) {
  return (
    <div className="alert warn rex-confirm" role="alertdialog" aria-labelledby="rex-confirm-title" aria-describedby="rex-confirm-text">
      <strong id="rex-confirm-title">Find rules again?</strong>
      <p id="rex-confirm-text">The document is read again, which may cost money. The rules below stay until a new result is ready. A failed attempt does not replace them.</p>
      <div className="rex-actions">
        <button type="button" className="btn primary" onClick={onConfirm}>Find rules again</button>
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
  const [order, setOrder] = useState<QueueOrder>(saved?.order ?? "flagged"); // rules with a potential issue first
  const [advance, setAdvance] = useState(saved?.advance ?? true);
  const [advanced, setAdvanced] = useState(saved?.advanced ?? false);
  const [overview, setOverview] = useState(false);
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
  const provisions = useMemo(() => provisionCoverage(elements, view.items), [elements, view.items]);
  const provisionById = useMemo(() => new Map(view.items.map((r) => [r.id, provisionOf(r, elements)])), [view.items, elements]);

  const reviewedCount = view.items.filter(isReviewed).length;
  const filters: ReviewFilter[] = api.kind === "ready" ? ["all", "pending", "flagged", "accepted", "rejected"]
    : reviewedCount ? ["all", "pending", "flagged", "reviewed"] : ["all", "pending", "flagged"];
  const activeFilter = filters.includes(filter) ? filter : "all"; // a filter that is not offered now (e.g. a saved "Accepted") does not hide everything
  // the order in which Previous / Next walk the rules: all rules (or those of the filter chosen in the overview)
  const sequence = useMemo(() => queueOrder(view.items.filter((r) => (matchesFilter(r, activeFilter) || r.id === pinned) && matchesSearch(r, search)), order),
                           [view, activeFilter, search, order, pinned]);

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
    nav.current = { pageScroll: 0, ...(nav.current?.jobId === jobId ? nav.current : {}), jobId, filter, search, selectedId, order, advance, advanced };
  }, [nav, jobId, filter, search, selectedId, order, advance, advanced]);
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

  const countOf = (f: ReviewFilter) => view.items.filter((r) => matchesFilter(r, f)).length;
  const scope = activeFilter !== "all" || search.trim() ? [activeFilter !== "all" ? FILTER_LABEL[activeFilter] : null, search.trim() ? `“${search.trim()}”` : null].filter(Boolean).join(", ") : null;
  const filename = result.filename ?? result.title;

  return (
    <section className="rex-results" aria-label="Extracted rules">
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
        <div className="rex-layout">
          <ReviewSidebar filename={filename} ov={ov} api={api} onOverview={() => setOverview(true)} exporting={exportState.busy} onDownload={() => void download()}
                         menu={(
                           <MoreMenu>
                             {(close) => (
                               <button type="button" role="menuitem" disabled={!canRestart || confirmRestart} onClick={() => { close(); onAskRestart(); }}
                                       title={canRestart ? "Read the document again. You will be asked to confirm." : "Needs a document from the server"}>
                                 <Icon name="refresh" size={14} />Find rules again
                               </button>
                             )}
                           </MoreMenu>
                         )} />
          {selected ? (
            <RuleView key={selected.id} rule={selected} position={position} count={sequence.length} scope={scope} onPrevious={() => move(-1)} onNext={() => move(1)}
                      elements={elements} numPages={result.model.source.num_pages} onShowInPdf={onShowInPdf} jobId={jobId} api={api} reviewer={reviewer} onReviewer={setReviewer}
                      onEntry={setEntry} onReload={reload} onDecided={onDecided} onConflict={setPinned} results={view} ov={ov} provisions={provisions}
                      advanced={advanced} onAdvanced={setAdvanced} />
          ) : (
            <div className="rex-main rex-empty-detail" role="status">
              <Icon name="info" size={20} /><span>No rules match the chosen filter. <button type="button" className="btn small" onClick={() => { setFilter("all"); setSearch(""); }}>Show all rules</button></span>
            </div>
          )}
        </div>
      )}

      {overview && (
        <Dialog title="All rules" onClose={() => setOverview(false)} className="wide">
          <RuleQueue items={sequence} selectedId={selected?.id ?? null} onSelect={(id) => { select(id); setOverview(false); }} filters={filters} activeFilter={activeFilter}
                     onFilter={(f) => { setPinned(null); setFilter(f); }} countOf={countOf} search={search} onSearch={(q) => { setPinned(null); setSearch(q); }}
                     order={order} onOrder={setOrder} advance={advance} onAdvance={setAdvance} canAdvance={api.kind === "ready"} provisionOf={(r) => provisionById.get(r.id) ?? null} />
        </Dialog>
      )}
    </section>
  );
}

/** One rule on screen: its review state (the hook belongs to the rule, so nothing typed for one rule reaches another). */
function RuleView({ rule, jobId, api, reviewer, onEntry, onReload, onDecided, onConflict, results, ov, provisions, advanced, onAdvanced, ...card }: {
  rule: RuleItem; position: number; count: number; scope: string | null; onPrevious: () => void; onNext: () => void;
  elements: Map<string, DocElement>; numPages: number; onShowInPdf?: (elementId: string) => void;
  jobId: string | undefined; api: ReviewApi; reviewer: string; onReviewer: (name: string) => void;
  onEntry: (ruleId: string, entry: RuleReviewEntry) => void; onReload: () => Promise<void>; onDecided: (ruleId: string) => void; onConflict: (ruleId: string) => void;
  results: RuleResults; ov: ReturnType<typeof overviewOf>; provisions: { total: number; withRules: number } | null; advanced: boolean; onAdvanced: (open: boolean) => void;
}) {
  const review = useReviewActions({ jobId: jobId ?? "", rule, api: jobId ? api : { kind: "unavailable", reason: null }, reviewer: jobId ? reviewer : "", onEntry, onReload, onDecided, onConflict });
  return (
    <ReviewMain rule={rule} review={review} reviewer={reviewer} {...card}
                advanced={<AdvancedDetails rule={rule} results={results} ov={ov} review={review} provisions={provisions} open={advanced} onOpen={onAdvanced} />} />
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
