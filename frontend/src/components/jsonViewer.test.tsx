// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RULE_DOOR, STORED } from "../demo/ruleTestData";
import { JsonViewer, tokenizeJsonLine } from "./JsonViewer";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const kinds = (line: string) => tokenizeJsonLine(line).filter((t) => t.kind !== "space").map((t) => [t.kind, t.text]);

describe("tokenizeJsonLine", () => {
  it("tells keys, strings, numbers, booleans and null apart", () => {
    expect(kinds('  "fact": "tuer.lichte_breite",')).toEqual([["key", '"fact"'], ["punct", ":"], ["string", '"tuer.lichte_breite"'], ["punct", ","]]);
    expect(kinds('"value": 0.9,')).toEqual([["key", '"value"'], ["punct", ":"], ["number", "0.9"], ["punct", ","]]);
    expect(kinds('"n": -12')).toEqual([["key", '"n"'], ["punct", ":"], ["number", "-12"]]);
    expect(kinds('"n": 1.5e-3')).toEqual([["key", '"n"'], ["punct", ":"], ["number", "1.5e-3"]]);
    expect(kinds('"ok": true')).toEqual([["key", '"ok"'], ["punct", ":"], ["boolean", "true"]]);
    expect(kinds('"ok": false,')).toEqual([["key", '"ok"'], ["punct", ":"], ["boolean", "false"], ["punct", ","]]);
    expect(kinds('"x": null')).toEqual([["key", '"x"'], ["punct", ":"], ["null", "null"]]);
    expect(kinds("  [")).toEqual([["punct", "["]]);
    expect(kinds("},")).toEqual([["punct", "}"], ["punct", ","]]);
    expect(kinds('"m",')).toEqual([["string", '"m"'], ["punct", ","]]);
  });

  it("never takes the inside of a string for syntax, including escaped quotes and a colon", () => {
    expect(kinds('"s": "a: {1, true} null"')).toEqual([["key", '"s"'], ["punct", ":"], ["string", '"a: {1, true} null"']]);
    expect(kinds('"s": "say \\"hi\\": 5"')).toEqual([["key", '"s"'], ["punct", ":"], ["string", '"say \\"hi\\": 5"']]);
    expect(kinds('"Türen müssen ≥ 0,90 m": 1')[0]).toEqual(["key", '"Türen müssen ≥ 0,90 m"']);
  });

  it("keeps every character of the line, whatever it contains", () => {
    for (const line of ['    "a": [1, "b"],', '"x":null', "  ??? ~", ""]) expect(tokenizeJsonLine(line).map((t) => t.text).join("")).toBe(line);
  });
});

let host: HTMLElement;
let root: Root;
const mount = async (value: unknown) => {
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => { root.render(<JsonViewer value={value} label="Rule JSON" />); });
};
const q = (sel: string) => host.querySelector<HTMLElement>(sel);
const copyButton = () => q("button")!;

describe("JsonViewer", () => {
  beforeEach(() => { vi.useFakeTimers(); });
  afterEach(() => { act(() => root.unmount()); host.remove(); vi.useRealTimers(); vi.unstubAllGlobals(); });

  it("shows exactly the formatted JSON, with its nesting and indentation, and nothing added", async () => {
    await mount(RULE_DOOR);
    const expected = JSON.stringify(RULE_DOOR, null, 2);
    expect(q(".jsonv-code")!.textContent).toBe(expected);
    expect(JSON.parse(q(".jsonv-code")!.textContent!)).toEqual(RULE_DOOR);
    expect(q(".jsonv-code")!.textContent).toContain('    "conditions": {\n      "kind": "all",'); // nested levels keep their indentation
  });

  it("highlights keys, strings, numbers, booleans and null", async () => {
    await mount({ id: "r", value: 0.9, ok: true, off: false, nothing: null, nested: { list: [1, "a"] } });
    const text = (cls: string) => [...host.querySelectorAll(`.${cls}`)].map((n) => n.textContent);
    expect(text("jt-key")).toEqual(['"id"', '"value"', '"ok"', '"off"', '"nothing"', '"nested"', '"list"']);
    expect(text("jt-string")).toEqual(['"r"', '"a"']);
    expect(text("jt-number")).toEqual(["0.9", "1"]);
    expect(text("jt-boolean")).toEqual(["true", "false"]);
    expect(text("jt-null")).toEqual(["null"]);
  });

  it("numbers every line in a gutter that is hidden from assistive technology and is not part of the copied text", async () => {
    await mount(STORED.rules[0]);
    const lines = JSON.stringify(STORED.rules[0], null, 2).split("\n").length;
    const gutter = q(".jsonv-gutter")!;
    expect(gutter.getAttribute("aria-hidden")).toBe("true");
    expect(gutter.textContent!.split("\n")).toEqual(Array.from({ length: lines }, (_, i) => String(i + 1)));
    expect(q(".jsonv-label")!.textContent).toContain(`${lines} lines`);
    expect(q(".jsonv-code")!.textContent).not.toMatch(/^1\n/);
  });

  it("copies the unformatted-by-colour JSON text, without line numbers, and confirms it", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    await mount(RULE_DOOR);
    expect(copyButton().textContent).toBe("Copy");
    await act(async () => { copyButton().click(); });
    expect(writeText).toHaveBeenCalledWith(JSON.stringify(RULE_DOOR, null, 2));
    expect(copyButton().textContent).toBe("Copied");
    expect(q('[role="status"]')!.textContent).toContain("copied to the clipboard");
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(copyButton().textContent).toBe("Copy");
  });

  it("says so when copying is not possible", async () => {
    vi.stubGlobal("navigator", { clipboard: { writeText: vi.fn().mockRejectedValue(new Error("denied")) } });
    await mount({ a: 1 });
    await act(async () => { copyButton().click(); });
    expect(copyButton().textContent).toBe("Copy failed");
  });

  it("is a keyboard-reachable, labelled region that scrolls on its own", async () => {
    await mount({ a: 1 });
    const region = q('[role="region"]')!;
    expect(region.tabIndex).toBe(0);
    expect(region.getAttribute("aria-label")).toBe("Rule JSON, 3 lines");
  });
});
