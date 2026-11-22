import { useEffect, useMemo, useRef, useState } from "react";
import { Icon } from "./Icon";

export type JsonTokenKind = "key" | "string" | "number" | "boolean" | "null" | "punct" | "space";
export interface JsonToken { kind: JsonTokenKind; text: string }

// One token per match. Strings come first so that braces, digits or `true` inside a string are never taken for syntax; a
// string followed by a colon is an object key. JSON.stringify puts every key and every value on a line of its own, so a
// line is enough context.
const TOKEN = /("(?:[^"\\]|\\.)*")(\s*:)?|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|\b(true|false)\b|\bnull\b|([{}[\],:])|(\s+)/g;

/** Splits one line of formatted JSON into tokens. The tokens' texts always add up to the line itself. */
export function tokenizeJsonLine(line: string): JsonToken[] {
  const out: JsonToken[] = [];
  let last = 0;
  for (const m of line.matchAll(TOKEN)) {
    if (m.index > last) out.push({ kind: "punct", text: line.slice(last, m.index) }); // anything unexpected stays visible, unstyled
    if (m[1] !== undefined) {
      if (m[2] !== undefined) { out.push({ kind: "key", text: m[1] }); out.push({ kind: "punct", text: m[2] }); }
      else out.push({ kind: "string", text: m[1] });
    } else if (m[3] !== undefined) out.push({ kind: "number", text: m[3] });
    else if (m[4] !== undefined) out.push({ kind: "boolean", text: m[4] });
    else if (m[0] === "null") out.push({ kind: "null", text: "null" });
    else if (m[5] !== undefined) out.push({ kind: "punct", text: m[5] });
    else out.push({ kind: "space", text: m[6] });
    last = m.index + m[0].length;
  }
  if (last < line.length) out.push({ kind: "punct", text: line.slice(last) });
  return out;
}

async function writeClipboard(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(text); return true; }
  } catch { /* fall through to the selection-based copy */ }
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.cssText = "position:fixed;top:0;left:0;opacity:0";
    document.body.append(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    return ok;
  } catch {
    return false;
  }
}

/** Formatted, syntax-highlighted JSON with line numbers and a copy button. The value is shown exactly as
 *  `JSON.stringify(value, null, 2)` writes it: nothing is added, removed or reordered, and the copy button copies that
 *  text (without line numbers). */
export function JsonViewer({ value, label = "JSON" }: { value: unknown; label?: string }) {
  const text = useMemo(() => JSON.stringify(value, null, 2) ?? "", [value]);
  const lines = useMemo(() => text.split("\n"), [text]);
  const tokens = useMemo(() => lines.map(tokenizeJsonLine), [lines]);
  const [copy, setCopy] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  useEffect(() => setCopy("idle"), [text]);

  const onCopy = async () => {
    setCopy((await writeClipboard(text)) ? "copied" : "failed");
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopy("idle"), 1800);
  };

  return (
    <div className="jsonv">
      <div className="jsonv-bar">
        <span className="jsonv-label">{label} <span className="jsonv-count">· {lines.length} lines</span></span>
        <button type="button" className="btn small" onClick={() => void onCopy()} aria-label={`Copy ${label}`}>
          <Icon name={copy === "copied" ? "check" : "file"} size={14} />
          {copy === "copied" ? "Copied" : copy === "failed" ? "Copy failed" : "Copy"}
        </button>
        <span className="sr-only" role="status">{copy === "copied" ? `${label} copied to the clipboard.` : copy === "failed" ? "Copying failed." : ""}</span>
      </div>
      <div className="jsonv-scroll" tabIndex={0} role="region" aria-label={`${label}, ${lines.length} lines`}>
        <pre className="jsonv-gutter" aria-hidden="true">{lines.map((_, i) => i + 1).join("\n")}</pre>
        <pre className="jsonv-code"><code>{tokens.map((line, i) => (
          <span className="jsonv-line" key={i}>{line.map((t, j) => (t.kind === "space" || t.kind === "punct" ? t.text : <span key={j} className={`jt-${t.kind}`}>{t.text}</span>))}{i < tokens.length - 1 ? "\n" : ""}</span>
        ))}</code></pre>
      </div>
    </div>
  );
}
