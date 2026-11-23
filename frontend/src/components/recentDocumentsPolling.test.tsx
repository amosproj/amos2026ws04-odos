// @vitest-environment jsdom
// The library keeps re-reading while a document is queued/processing, so it never stays on "Processing".
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RecentDocuments } from "./RecentDocuments";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const doc = (status: string) => ({ id: "d1", filename: "a.pdf", status, created_at: "2026-11-23T00:06:00Z" });
let host: HTMLElement;
let root: Root;
let status = "processing";
let listCalls = 0;

beforeEach(() => {
  vi.useFakeTimers();
  status = "processing";
  listCalls = 0;
  vi.stubGlobal("fetch", vi.fn(async () => {
    listCalls++;
    return new Response(JSON.stringify([doc(status)]), { status: 200, headers: { "Content-Type": "application/json" } });
  }));
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => { root.unmount(); });
  host.remove();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("RecentDocuments polling", () => {
  it("moves from Processing to Cancelled without a manual refresh, then stops polling", async () => {
    await act(async () => { root.render(<RecentDocuments onOpen={() => {}} />); await vi.advanceTimersByTimeAsync(0); });
    expect(host.textContent).toContain("Processing");

    status = "cancelled"; // the backend has settled the cancellation
    await act(async () => { await vi.advanceTimersByTimeAsync(3100); });
    expect(host.textContent).toContain("Cancelled");
    expect(host.textContent).not.toContain("Processing");

    const settled = listCalls;
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(listCalls).toBe(settled); // nothing unsettled any more: no further requests
  });

  it("does not poll a library with only finished documents", async () => {
    status = "completed";
    await act(async () => { root.render(<RecentDocuments onOpen={() => {}} />); await vi.advanceTimersByTimeAsync(0); });
    const first = listCalls;
    await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
    expect(listCalls).toBe(first);
  });
});
