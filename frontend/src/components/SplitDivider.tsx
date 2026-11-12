import { useEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent, type RefObject } from "react";

export const HANDLE_PX = 14; // the divider's column in the grid
export const MIN_PANEL_PX = 320;
export const DEFAULT_SPLIT = 0.5;

/** The left panel's share of the width beside the divider, limited so that both panels stay at least `minPx` wide. When
 *  the container is too narrow for that, the panels share the width evenly. */
export function clampSplit(fraction: number, containerWidth: number, minPx = MIN_PANEL_PX): number {
  const free = containerWidth - HANDLE_PX;
  if (!(free >= 2 * minPx)) return DEFAULT_SPLIT;
  const lo = minPx / free;
  return Math.min(1 - lo, Math.max(lo, fraction));
}

/** The grid's custom properties for a split: the two columns as flex shares. */
export const splitVars = (fraction: number) => ({ "--left": `${(fraction * 1000).toFixed(1)}fr`, "--right": `${((1 - fraction) * 1000).toFixed(1)}fr` }) as CSSProperties;

interface Props {
  /** The grid that holds the two panels and this divider. */
  containerRef: RefObject<HTMLElement | null>;
  value: number;
  /** Called when a drag ends or a key changes the split. While dragging, only the grid's custom properties change. */
  onCommit: (fraction: number) => void;
  minPx?: number;
}

/** A draggable, keyboard-operable divider between two panels (WAI-ARIA window splitter). */
export function SplitDivider({ containerRef, value, onCommit, minPx = MIN_PANEL_PX }: Props) {
  const dragging = useRef(false);
  const live = useRef(value);
  const [active, setActive] = useState(false);
  const [width, setWidth] = useState(0);

  useEffect(() => { live.current = value; }, [value]);
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    setWidth(el.getBoundingClientRect().width);
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setWidth(el.getBoundingClientRect().width));
    ro.observe(el);
    return () => ro.disconnect();
  }, [containerRef]);

  const bounds = (w: number) => ({ lo: clampSplit(0, w, minPx), hi: clampSplit(1, w, minPx) });
  const { lo, hi } = bounds(width);

  const apply = (fraction: number) => {
    const el = containerRef.current;
    if (!el) return;
    const vars = splitVars(fraction) as Record<string, string>;
    for (const k of Object.keys(vars)) el.style.setProperty(k, vars[k]);
    live.current = fraction;
  };
  const commit = (fraction: number) => {
    const w = containerRef.current?.getBoundingClientRect().width ?? 0;
    const f = clampSplit(fraction, w, minPx);
    apply(f);
    onCommit(f);
  };

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    e.preventDefault(); // no text selection while dragging
    dragging.current = true;
    setActive(true);
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const el = containerRef.current;
    if (!dragging.current || !el) return;
    const rect = el.getBoundingClientRect();
    const f = (e.clientX - rect.left - HANDLE_PX / 2) / (rect.width - HANDLE_PX);
    apply(clampSplit(f, rect.width, minPx)); // no React render while dragging
  };
  const end = () => {
    if (!dragging.current) return;
    dragging.current = false;
    setActive(false);
    onCommit(live.current);
  };
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = e.shiftKey ? 0.1 : 0.02;
    const next = e.key === "ArrowLeft" ? value - step : e.key === "ArrowRight" ? value + step : e.key === "Home" ? 0 : e.key === "End" ? 1 : e.key === "Enter" ? DEFAULT_SPLIT : null;
    if (next === null) return;
    e.preventDefault();
    commit(next);
  };

  return (
    <div
      className={`splitter${active ? " active" : ""}`}
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize the PDF and structure panels"
      aria-valuenow={Math.round(value * 100)}
      aria-valuemin={Math.round(lo * 100)}
      aria-valuemax={Math.round(hi * 100)}
      tabIndex={0}
      title="Drag to resize · arrow keys · double-click to reset"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={end}
      onPointerCancel={end}
      onLostPointerCapture={end}
      onKeyDown={onKeyDown}
      onDoubleClick={() => commit(DEFAULT_SPLIT)}
    />
  );
}
