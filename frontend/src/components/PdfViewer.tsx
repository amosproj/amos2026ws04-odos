import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { useEffect, useMemo, useRef, useState } from "react";
import { bboxToRect, type Rect } from "../structure";
import type { Provenance } from "../types";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

interface Props {
  url: string;
  page: number;
  onPageChange: (page: number) => void;
  highlights: Provenance[]; // only those on `page` are drawn
  approximate?: boolean; // the box covers a whole Docling item that holds more than this element
}

export function PdfViewer({ url, page, onPageChange, highlights, approximate = false }: Props) {
  const [pdf, setPdf] = useState<pdfjs.PDFDocumentProxy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [size, setSize] = useState<{ w: number; h: number; scale: number } | null>(null);
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(600);
  const [rendered, setRendered] = useState(0); // page whose pixels are currently on the canvas

  useEffect(() => {
    let dead = false;
    const task = pdfjs.getDocument({ url });
    task.promise.then((d) => { if (!dead) setPdf(d); }, (e: Error) => { if (!dead) setError(e.message); });
    return () => { dead = true; void task.destroy(); };
  }, [url]);

  useEffect(() => {
    if (!wrap.current) return;
    const ro = new ResizeObserver((entries) => setWidth(entries[0].contentRect.width));
    ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);

  const pages = pdf?.numPages ?? 0;
  const pageNo = Math.min(Math.max(page, 1), Math.max(pages, 1));

  useEffect(() => {
    if (!pdf || !canvas.current) return;
    let cancelled = false;
    let task: pdfjs.RenderTask | undefined;
    void pdf.getPage(pageNo).then((p) => {
      if (cancelled || !canvas.current) return;
      const base = p.getViewport({ scale: 1 });
      const scale = Math.max(0.3, ((width - 24) / base.width) * zoom);
      const dpr = window.devicePixelRatio || 1;
      const vp = p.getViewport({ scale: scale * dpr });
      const c = canvas.current;
      c.width = Math.floor(vp.width);
      c.height = Math.floor(vp.height);
      c.style.width = `${base.width * scale}px`;
      c.style.height = `${base.height * scale}px`;
      setSize({ w: base.width * scale, h: base.height * scale, scale });
      task = p.render({ canvas: c, viewport: vp });
      task.promise.then(() => { if (!cancelled) setRendered(pageNo); }, () => undefined); // cancelled renders reject
      // keep the base page height in points for bbox conversion
      pageHeight.current = base.height;
    });
    return () => { cancelled = true; task?.cancel(); };
  }, [pdf, pageNo, width, zoom]);

  const pageHeight = useRef(0);
  const rects: Rect[] = useMemo(() => {
    if (!size || rendered !== pageNo) return []; // never draw boxes over a stale page image
    return highlights
      .filter((h) => h.page_no === pageNo && h.bbox)
      .map((h) => bboxToRect(h.bbox!, pageHeight.current, size.scale));
  }, [highlights, pageNo, size, rendered]);

  useEffect(() => {
    if (rects.length && wrap.current) {
      const top = Math.min(...rects.map((r) => r.top));
      wrap.current.scrollTo({ top: Math.max(0, top - 120), behavior: "smooth" });
    }
  }, [rects]);

  if (error) return <div className="alert error">Could not display the PDF: {error}</div>;

  return (
    <div className="pdf">
      <div className="pdf-toolbar">
        <button onClick={() => onPageChange(pageNo - 1)} disabled={pageNo <= 1} aria-label="Previous page">‹</button>
        <label className="pageinput">
          Page
          <input type="number" min={1} max={pages || 1} value={pageNo} onChange={(e) => onPageChange(Number(e.target.value) || 1)} />
          <span>/ {pages || "…"}</span>
        </label>
        <button onClick={() => onPageChange(pageNo + 1)} disabled={pageNo >= pages} aria-label="Next page">›</button>
        <span className="spacer" />
        <button onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))} aria-label="Zoom out">−</button>
        <span className="muted">{Math.round(zoom * 100)}%</span>
        <button onClick={() => setZoom((z) => Math.min(3, z + 0.25))} aria-label="Zoom in">+</button>
      </div>
      <div className="pdf-scroll" ref={wrap}>
        {!pdf && <p className="muted pad">Loading PDF…</p>}
        <div className="pdf-page" style={size ? { width: size.w, height: size.h } : undefined}>
          <canvas ref={canvas} />
          {rects.map((r, i) => (
            <div key={i} className={`hl${approximate ? " approx" : ""}`} title={approximate ? "Box of the whole source item; this element is only part of its text" : undefined} style={{ left: r.left - 2, top: r.top - 2, width: r.width + 4, height: r.height + 4 }} />
          ))}
        </div>
      </div>
    </div>
  );
}
