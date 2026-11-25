// @vitest-environment jsdom
import { act, createRef } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RowDivider } from "./SplitDivider";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let host: HTMLElement;
afterEach(() => host?.remove());

describe("RowDivider", () => {
  it("is a keyboard-operable horizontal separator that stays within 20-80 %", async () => {
    host = document.createElement("div");
    document.body.append(host);
    const onChange = vi.fn();
    await act(async () => { createRoot(host).render(<RowDivider containerRef={createRef()} value={0.45} onChange={onChange} />); });
    const sep = host.querySelector<HTMLElement>('[role="separator"]')!;
    expect(sep.getAttribute("aria-orientation")).toBe("horizontal");
    expect(sep.getAttribute("aria-valuenow")).toBe("45");
    await act(async () => { sep.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowDown", bubbles: true })); });
    expect(onChange).toHaveBeenLastCalledWith(expect.closeTo(0.5, 5));
    await act(async () => { sep.dispatchEvent(new KeyboardEvent("keydown", { key: "End", bubbles: true })); });
    expect(onChange).toHaveBeenLastCalledWith(0.8);
    await act(async () => { sep.dispatchEvent(new KeyboardEvent("keydown", { key: "Home", bubbles: true })); });
    expect(onChange).toHaveBeenLastCalledWith(0.2);
  });
});
