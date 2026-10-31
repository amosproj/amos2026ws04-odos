import type { Akn4euReport } from "./types";

// Exports: the Akoma Ntoso result banner (from the pipeline summary) and the AKN4EU validation layers.

export const AKN_EU_NOTE = "Akoma Ntoso XML was not generated for this EU document.";

/** Banner text for the Akoma Ntoso result of an EU document, from the pipeline summary only. */
export function aknStatus(summary: Record<string, unknown>): { kind: "info" | "warn" | "error"; title: string; text: string } {
  if (!summary.akn_generated) return { kind: "warn", title: "No Akoma Ntoso XML.", text: AKN_EU_NOTE };
  if (summary.akn_xsd_valid) {
    const text = summary.akn_text_identical ? "Text and order match the extracted document." : "Text check reported differences — see the text report.";
    return { kind: summary.akn_text_identical ? "info" : "warn", title: "Akoma Ntoso XML valid against the official OASIS XSD (Akoma Ntoso 3.1).", text };
  }
  return { kind: "error", title: "Akoma Ntoso XML is NOT schema-valid.", text: `${summary.akn_xsd_errors ?? "?"} XSD error(s) — see the validation report.` };
}

export type LayerTone = "ok" | "fail" | "notdone";
export interface Akn4euLayer { name: string; tone: LayerTone; result: string; meaning: string }

/** The three validation layers of an AKN4EU export (plus the text check), kept apart. Never claims conformance. */
export function akn4euLayers(r: Akn4euReport): Akn4euLayer[] {
  const c = r.conformance;
  const n = Object.keys(r.files).length;
  const valid = Object.values(r.files).filter((f) => f.valid_akn_3_1).length;
  const t = r.text_preservation_summary;
  return [
    { name: "OASIS Akoma Ntoso 3.1 XSD", tone: c.oasis_akn_3_1_xsd.valid ? "ok" : "fail", result: `${valid} of ${n} files valid`,
      meaning: "Official OASIS schema (OASIS Standard, 2 October 2026), unmodified and SHA-256 pinned." },
    { name: "AKN4EU sample rules", tone: c.akn4eu_sample_checks.passed ? "ok" : "fail",
      result: c.akn4eu_sample_checks.passed ? `all ${c.akn4eu_sample_checks.rules} rules hold` : "rules violated",
      meaning: "Regularities of all 60 official AKN4EU 5.0.1.0 sample files. Sample compatibility only." },
    { name: "Official AKN4EU validation", tone: "notdone", result: c.official_akn4eu_validation.performed ? "performed" : "not performed",
      meaning: c.official_akn4eu_validation.reason },
    { name: "Text and order vs. extracted model", tone: c.text_and_order_against_model ? "ok" : "fail",
      result: c.text_and_order_against_model ? `identical (${t.characters_compared.toLocaleString("en")} characters)` : "differences",
      meaning: `Every element's text rebuilt from the XML and compared; footnotes at their reference: ${t.footnotes.at_reference} of ${t.footnotes.total}.` },
  ];
}

export function akn4euHeadline(r: Akn4euReport): { kind: "info" | "error"; title: string } {
  const ok = r.status.startsWith("sample-compatible");
  return ok
    ? { kind: "info", title: "Sample-compatible AKN4EU — not officially verified AKN4EU conformance." }
    : { kind: "error", title: "Not sample-compatible: at least one validation layer failed (see below)." };
}
