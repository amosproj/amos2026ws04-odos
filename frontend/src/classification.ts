import type { Classification, ProcessingMode } from "./types";

// Document classification and routing: what to tell the user about a suggestion and a manual mode choice.

export const DOC_TYPE_LABELS: Record<string, string> = {
  german_law: "German law (§ structure)",
  german_model_regulation: "German model regulation",
  eu_regulation: "EU regulation",
  eu_directive: "EU directive",
  technical_standard: "Technical standard (ISO/IEC/DIN/EN)",
  unknown: "Unknown / not recognised",
};

export const MODE_LABELS: Record<string, string> = {
  german_law: "German law (prototype)",
  eu_legislation: "EU legislation (prototype)",
  extract_only: "Extract only",
};

export const BAND_TEXT: Record<string, string> = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
};

export interface ClassificationView {
  tone: "ok" | "info" | "warn";
  headline: string;
  detail: string;
  uncertain: boolean;
}

/** What to tell the user about a classification. The band is a heuristic rule outcome, never shown as a percentage. */
export function classificationView(c: Classification): ClassificationView {
  const type = DOC_TYPE_LABELS[c.document_type] ?? c.document_type;
  const band = BAND_TEXT[c.confidence_band] ?? c.confidence_band;
  switch (c.support_status) {
    case "supported":
      return { tone: c.confidence_band === "high" ? "ok" : "info", headline: `Detected: ${type}`, uncertain: c.confidence_band !== "high",
        detail: `${band} (heuristic). Suggested mode: ${MODE_LABELS[c.suggested_processing_mode]}.${c.confidence_band === "medium" ? " Please check the evidence." : ""}` };
    case "recognised_not_supported":
      return { tone: "warn", headline: `Detected: ${type}`, uncertain: false,
        detail: `${band} (heuristic). No structured pipeline supports this type yet, so only text extraction is suggested.` };
    case "uncertain":
      return { tone: "warn", headline: `Possibly: ${type}`, uncertain: true,
        detail: `Low confidence: the evidence is weak, so extraction only is suggested${c.candidate_mode ? `. You can still choose ${MODE_LABELS[c.candidate_mode]} yourself` : ""}.` };
    default:
      return { tone: "warn", headline: "Document type not recognised", uncertain: true,
        detail: "Not enough evidence for any supported type. Only text extraction is suggested." };
  }
}

/** Note shown when the chosen mode differs from the suggestion; null when they agree or nothing is known. */
export function modeChoiceNote(c: Classification | null, mode: ProcessingMode): string | null {
  if (!c || mode === c.suggested_processing_mode) return null;
  const type = DOC_TYPE_LABELS[c.document_type] ?? c.document_type;
  if (mode === "extract_only") return "Manual choice: text extraction only, no legal structure will be produced.";
  if (c.candidate_mode === mode) return "Manual choice: the classification was not confident enough to suggest this mode.";
  return `Manual override: this document was classified as ${type}. ${MODE_LABELS[mode]} may give an empty or misleading structure.`;
}

/** Evidence grouped for display: strongest first, with the page it was found on. */
export function evidenceRows(c: Classification): { key: string; text: string; page: number | null; weight: number }[] {
  return [...c.evidence].sort((a, b) => b.weight - a.weight || a.rule_id.localeCompare(b.rule_id)).map((e) => ({
    key: e.rule_id, weight: e.weight, page: e.page,
    text: e.snippet ? `${e.description} — “${e.snippet}”` : e.count ? `${e.description} (${e.count}×)` : e.description,
  }));
}
