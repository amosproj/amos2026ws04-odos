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
  const s = c.akn4eu_5_0_1_0_rules;
  const spec: Akn4euLayer[] = s ? [{
    name: "AKN4EU 5.0.1.0 specification rules", tone: !s.passed ? "fail" : s.complete ? "ok" : "notdone",
    result: !s.passed ? `${s.failed.length} mandatory rule(s) violated`
      : s.complete ? "all implemented mandatory rules met"
      : `not met: ${s.missing_input.length} need information not in the PDF, ${s.deviations.length} deliberate deviation(s)`,
    meaning: "Rules read from the AKN4EU 5.0.1.0 specification and implemented by ODOS (package, metadata, completeness). Not the official validator." }] : [];
  return [
    { name: "OASIS Akoma Ntoso 3.1 XSD", tone: c.oasis_akn_3_1_xsd.valid ? "ok" : "fail", result: `${valid} of ${n} files valid`,
      meaning: "Official OASIS schema (OASIS Standard, 2 October 2026), unmodified and SHA-256 pinned." },
    { name: "AKN4EU sample rules", tone: c.akn4eu_sample_checks.passed ? "ok" : "fail",
      result: c.akn4eu_sample_checks.passed ? `all ${c.akn4eu_sample_checks.rules} rules hold` : "rules violated",
      meaning: "Regularities of all 60 official AKN4EU 5.0.1.0 sample files. Sample compatibility only." },
    ...spec,
    { name: "Official AKN4EU validation", tone: "notdone", result: c.official_akn4eu_validation.performed ? "performed" : "not performed",
      meaning: c.official_akn4eu_validation.reason },
    { name: "Text and order vs. extracted model", tone: c.text_and_order_against_model ? "ok" : "fail",
      result: c.text_and_order_against_model ? `identical (${t.characters_compared.toLocaleString("en")} characters)` : "differences",
      meaning: `Every element's text rebuilt from the XML and compared; footnotes at their reference: ${t.footnotes.at_reference} of ${t.footnotes.total}.` },
  ];
}

export interface Akn4euStatusLine { label: string; tone: LayerTone; text: string }

/** The three claims kept apart: XSD-valid, conformant to the AKN4EU 5.0.1.0 rules ODOS implements, officially verified. */
export function akn4euStatusLines(r: Akn4euReport): Akn4euStatusLine[] {
  const n = Object.keys(r.files).length;
  const valid = Object.values(r.files).filter((f) => f.valid_akn_3_1).length;
  const s = r.conformance.akn4eu_5_0_1_0_rules;
  const spec: Akn4euStatusLine = !s
    ? { label: "AKN4EU 5.0.1.0", tone: "notdone", text: "not assessed (export made before these rules existed)" }
    : !s.passed ? { label: "AKN4EU 5.0.1.0", tone: "fail", text: `NOT conformant: ${s.failed.length} mandatory rule(s) violated` }
    : s.complete ? { label: "AKN4EU 5.0.1.0", tone: "ok", text: "all implemented mandatory rules met" }
    : { label: "AKN4EU 5.0.1.0", tone: "notdone", text: `NOT conformant: ${s.missing_input.length} required item(s) missing from the source, ${s.deviations.length} deliberate deviation(s)` };
  return [
    { label: "XSD (AKN 3.1)", tone: valid === n ? "ok" : "fail", text: `${valid} of ${n} files schema-valid — says nothing about AKN4EU conformance` },
    spec,
    { label: "Official AKN4EU validator", tone: "notdone", text: r.conformance.official_akn4eu_validation.performed ? "performed" : "not run (not available)" },
  ];
}

/** Warnings about how the export was built: an unapproved review is named as such, never presented as approved. */
export function akn4euNotices(r: Akn4euReport): string[] {
  const out = (r.export_warnings ?? []).map((w) => w.detail);
  const s = r.conformance.akn4eu_5_0_1_0_rules?.warnings ?? [];
  if (s.length) out.push(`Recommended (SHOULD) requirements not met: ${s.join(", ")}`);
  return out;
}

export function akn4euHeadline(r: Akn4euReport): { kind: "info" | "error"; title: string } {
  const ok = r.status.startsWith("sample-compatible");
  return ok
    ? { kind: "info", title: "Sample-compatible AKN4EU — not officially verified AKN4EU conformance." }
    : { kind: "error", title: "Not sample-compatible: at least one validation layer failed (see below)." };
}
