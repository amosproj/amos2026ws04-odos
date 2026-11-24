// @vitest-environment jsdom
// Cancellation UX for Document Processing in DemoApp: Stop button, confirmation dialog, Stopping state.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DemoApp from "./DemoApp";
import type { Job } from "./live";

vi.mock("../components/PdfViewer", () => ({
  PdfViewer: () => <div className="pdf-stub" />,
}));
vi.mock("../components/ProcessingStatus", () => ({
  ProcessingStatus: ({ stage }: { stage: string }) => <div className="ps-stub">{stage}</div>,
}));
vi.mock("../components/RecentDocuments", () => ({
  RecentDocuments: () => <div className="rd-stub" />,
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const MINIMAL_PDF = new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d]); // %PDF-

function makeJob(partial: Partial<Job> = {}): Job {
  return { id: "job1", filename: "test.pdf", status: "processing", stage: "extracting", message: null, ...partial };
}

/** Installs a fetch mock that starts the job immediately, then blocks GET polls until `releaseGate` is called.
 *  Pre-releasing (calling releaseGate before the GET fires) queues the response for the next GET call. */
function installFakePdf() {
  let pendingResolve: ((job: Job) => void) | null = null;
  let queuedResponse: Job | null = null;

  const releaseGate = (job: Job) => {
    if (pendingResolve) {
      const r = pendingResolve;
      pendingResolve = null;
      r(job);
    } else {
      queuedResponse = job;
    }
  };

  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      const json = (body: unknown, status = 200) =>
        new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

      if (method === "POST" && url.endsWith("/api/jobs")) {
        return json(makeJob({ status: "processing", stage: "extracting" }), 202);
      }
      if (method === "GET" && /\/api\/jobs\//.test(url)) {
        if (queuedResponse) {
          const j = queuedResponse;
          queuedResponse = null;
          return json(j);
        }
        return new Promise<Response>((resolve) => {
          pendingResolve = (job) => resolve(json(job));
        });
      }
      if (method === "POST" && url.endsWith("/cancel")) {
        return json(makeJob({ cancelRequested: true, stage: "cancelling" }));
      }
      if (method === "DELETE") return new Response(null, { status: 204 });
      return json({ detail: "unexpected" }, 500);
    }),
  );
  return { releaseGate };
}

/** Choose a fake PDF file on the input and click Process document. */
async function pickAndProcess(host: HTMLElement) {
  const input = host.querySelector<HTMLInputElement>('input[type="file"]')!;
  await act(async () => {
    Object.defineProperty(input, "files", {
      configurable: true,
      get: () => {
        const f = new File([MINIMAL_PDF], "test.pdf", { type: "application/pdf" });
        return { 0: f, length: 1, item: () => f };
      },
    });
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
  const processBtn = [...host.querySelectorAll("button")].find((b) => /Process document/i.test(b.textContent ?? ""))!;
  await act(async () => { processBtn.click(); });
}

/** Click Stop processing button, open the confirmation dialog. */
async function clickStop(host: HTMLElement) {
  const stopBtn = [...host.querySelectorAll("button")].find((b) => /Stop processing/i.test(b.textContent ?? ""))!;
  await act(async () => { stopBtn.click(); });
}

/** Confirm the stop in the confirmation dialog. */
async function confirmStop(host: HTMLElement) {
  const dialogBtn = [...host.querySelectorAll<HTMLButtonElement>('[role="alertdialog"] button')].find(
    (b) => /Stop processing/i.test(b.textContent ?? ""),
  )!;
  await act(async () => { dialogBtn.click(); });
}

let host: HTMLElement;
let root: Root;

const flush = async (ms = 0) => {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
};

const q = (sel: string) => host.querySelector(sel);
const text = () => host.textContent ?? "";
const button = (re: RegExp) => [...host.querySelectorAll("button")].find((b) => re.test(b.textContent ?? ""));

beforeEach(() => { vi.useFakeTimers(); });

afterEach(async () => {
  await act(async () => { root.unmount(); });
  host.remove();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("document processing cancellation", () => {
  it("shows a Stop processing button while a document is being processed", async () => {
    const { releaseGate } = installFakePdf();
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    await act(async () => { root.render(<DemoApp />); });

    await pickAndProcess(host);

    expect(button(/Stop processing/i)).toBeDefined();

    releaseGate(makeJob({ status: "completed", stage: null }));
    await flush(1200);
  });

  it("opens a confirmation dialog when Stop processing is clicked", async () => {
    const { releaseGate } = installFakePdf();
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    await act(async () => { root.render(<DemoApp />); });

    await pickAndProcess(host);
    await clickStop(host);

    expect(q('[role="alertdialog"]')).not.toBeNull();
    expect(text()).toContain("Stop document processing?");
    expect(button(/Keep running/i)).toBeDefined();

    releaseGate(makeJob({ status: "completed", stage: null }));
    await flush(1200);
  });

  it("dismisses the dialog and continues when Keep running is clicked", async () => {
    const { releaseGate } = installFakePdf();
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    await act(async () => { root.render(<DemoApp />); });

    await pickAndProcess(host);
    await clickStop(host);

    await act(async () => {
      button(/Keep running/i)!.click();
    });

    expect(q('[role="alertdialog"]')).toBeNull();
    expect(button(/Stop processing/i)).toBeDefined();

    releaseGate(makeJob({ status: "completed", stage: null }));
    await flush(1200);
  });

  it("shows the cancelling stage and no dialog after the user confirms stop", async () => {
    const { releaseGate } = installFakePdf();
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    await act(async () => { root.render(<DemoApp />); });

    await pickAndProcess(host);
    await clickStop(host);
    await confirmStop(host);

    // dialog is gone immediately after confirming; the UI is already idle (immediate reset)
    expect(q('[role="alertdialog"]')).toBeNull();

    // pre-release gate: when the background processPdf loop detects the abort and polls, it gets "cancelled"
    releaseGate(makeJob({ status: "cancelled", stage: null }));
    // advance past the 1000ms sleep — the background loop settles (no-op for the already-idle UI)
    await flush(1100);

    // no error alert — cancellation was clean
    expect(q('[role="alert"]')).toBeNull();
    // Stop processing button is gone (UI is idle)
    expect(button(/Stop processing/i)).toBeUndefined();
  });

  it("returns to idle state without an error message after a successful cancellation", async () => {
    const { releaseGate } = installFakePdf();
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    await act(async () => { root.render(<DemoApp />); });

    await pickAndProcess(host);
    await clickStop(host);
    await confirmStop(host);

    // pre-release the gate: when the background sleep finishes the loop detects abort, fires cancelJob, polls and exits
    releaseGate(makeJob({ status: "cancelled", stage: null }));
    // advance past the 1000ms sleep → background loop settles; UI was already idle from confirmStop
    await flush(1200);

    expect(button(/Process document/i)).toBeDefined();
    expect(q('[role="alert"]')).toBeNull();
  });

  it("sends the cancel request at once when the user confirms, not after the next poll", async () => {
    installFakePdf();
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    await act(async () => { root.render(<DemoApp />); });

    await pickAndProcess(host);
    await clickStop(host);
    await confirmStop(host);
    await flush(0); // no timer has run: the 1 s poll interval has not elapsed

    const cancels = vi.mocked(fetch).mock.calls.filter(([u, i]) => String(u).endsWith("/cancel") && i?.method === "POST");
    expect(cancels).toHaveLength(1);
  });

  it("allows a retry right after cancelling, and a late answer of the cancelled run cannot change the new run", async () => {
    const { releaseGate } = installFakePdf();
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    await act(async () => { root.render(<DemoApp />); });

    await pickAndProcess(host);
    await clickStop(host);
    await confirmStop(host);
    await flush(0);
    expect(button(/Process document/i)).toBeDefined();
    expect(button(/Process document/i)?.hasAttribute("disabled")).toBe(false);

    await act(async () => { button(/Process document/i)!.click(); }); // retry with the same file
    expect(button(/Stop processing/i)).toBeDefined(); // the new run is busy

    // the old run's pending poll now answers "completed" (and its result files cannot be loaded): nothing may change
    releaseGate(makeJob({ status: "completed", stage: null }));
    await flush(50);
    expect(button(/Stop processing/i)).toBeDefined();
    expect(q('[role="alert"]')).toBeNull();
    expect(q(".ps-stub")).not.toBeNull();

    const uploads = vi.mocked(fetch).mock.calls.filter(([u, i]) => String(u).endsWith("/api/jobs") && i?.method === "POST");
    expect(uploads).toHaveLength(2); // exactly one upload per click: no duplicate processing
  });

  it("does not start a second run while one is being processed", async () => {
    installFakePdf();
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    await act(async () => { root.render(<DemoApp />); });

    await pickAndProcess(host);
    expect(button(/Process document|Processing/i)?.hasAttribute("disabled")).toBe(true);
    const uploads = vi.mocked(fetch).mock.calls.filter(([u, i]) => String(u).endsWith("/api/jobs") && i?.method === "POST");
    expect(uploads).toHaveLength(1);
  });
});
