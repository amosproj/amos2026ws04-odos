import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Akn4euReportView } from "./components/Akn4euPanel";
import { akn4euHeadline, akn4euLayers, akn4euNotices, akn4euStatusLines } from "./exports";
import type { Akn4euReport } from "./types";

const file = (valid = true, passed = true) => ({
  bytes: 343812, xml_sha256: "ab".repeat(32), valid_akn_3_1: valid, errors: valid ? [] : [{ line: 3, message: "bogus" }],
  sample_checks: { passed, findings: passed ? [] : [{ rule: "POINT_IN_LIST", message: "point outside list" }] },
});

const report: Akn4euReport = {
  profile: "akn4eu",
  status: "sample-compatible AKN4EU (not officially verified AKN4EU conformance)",
  conformance: {
    oasis_akn_3_1_xsd: { valid: true, schema_version: "OASIS Akoma Ntoso Version 2.0 … AKN 3.1", schema_files: [] },
    akn4eu_sample_checks: { passed: true, rules: 16, meaning: "sample compatibility" },
    official_akn4eu_validation: { performed: false, reason: "no official AKN4EU schema or Schematron available" },
    text_and_order_against_model: true,
  },
  files: { "act-reg_2023_1230-de.xml": file(), "ANNEX-reg_2023_1230_anx_1-de.xml": file() },
  act_file: "act-reg_2023_1230-de.xml",
  package: "akn4eu_package.zip",
  identifiers: { eli: null, resource_type: "REG", authors: ["EP", "CONSIL"], language: "DEU", akn4eu_version: "5.0.0.1" },
  scope: { articles: 54, recitals: 86, annexes: 12, retrieval_date: "2026-10-29" },
  generator_warnings: [{ code: "NO_ELI" }, { code: "UNCERTAIN_ELEMENT_INCLUDED" }, { code: "UNCERTAIN_ELEMENT_INCLUDED" }],
  unmapped: [],
  text_preservation_summary: { same_order_and_text: true, atoms_compared: 2958, characters_compared: 372519, footnotes: { total: 26, at_reference: 26, end_of_text: 0 } },
};

describe("AKN4EU export view", () => {
  it("keeps the validation layers apart and never claims conformance", () => {
    const html = renderToStaticMarkup(<Akn4euReportView docId="d1" report={report} selected={null} onView={() => {}} />);
    expect(html).toContain("Sample-compatible AKN4EU — not officially verified AKN4EU conformance.");
    expect(html).toContain("OASIS Akoma Ntoso 3.1 XSD");
    expect(html).toContain("2 of 2 files valid");
    expect(html).toContain("all 16 rules hold");
    expect(html).toContain("Official AKN4EU validation");
    expect(html).toContain("not performed");
    expect(html).toContain("no official AKN4EU schema or Schematron available");
    expect(html).toContain("identical (372,519 characters)");
    expect(html).not.toMatch(/AKN4EU (conformant|compliant|valid)\b/i);
  });

  it("lists every file with view and download, and the package and reports", () => {
    const html = renderToStaticMarkup(<Akn4euReportView docId="d1" report={report} selected={null} onView={() => {}} />);
    expect(html).toContain("Act · act-reg_2023_1230-de.xml");
    expect(html).toContain("Annex · ANNEX-reg_2023_1230_anx_1-de.xml");
    expect(html).toContain('href="/api/documents/d1/exports/akn4eu/files/act-reg_2023_1230-de.xml"');
    for (const kind of ["package", "report", "traceability", "text_report"]) expect(html).toContain(`/api/documents/d1/exports/akn4eu/${kind}`);
    expect(html).toContain("no ELI (not printed in the PDF, none supplied");
    expect(html).toContain("UNCERTAIN_ELEMENT_INCLUDED ×2");
  });

  it("shows a failed layer as such", () => {
    const bad: Akn4euReport = { ...report, status: "NOT sample-compatible: see the failing layer(s)",
      conformance: { ...report.conformance, oasis_akn_3_1_xsd: { ...report.conformance.oasis_akn_3_1_xsd, valid: false }, akn4eu_sample_checks: { passed: false, rules: 16, meaning: "" } },
      files: { "act-reg_2023_1230-de.xml": file(false, false) } };
    expect(akn4euHeadline(bad).kind).toBe("error");
    expect(akn4euLayers(bad).map((l) => l.tone)).toEqual(["fail", "fail", "notdone", "ok"]);
    const html = renderToStaticMarkup(<Akn4euReportView docId="d1" report={bad} selected={null} onView={() => {}} />);
    expect(html).toContain("0 of 1 files valid");
    expect(html).toContain("1 XSD errors");
    expect(html).toContain("1 rule findings");
  });

  it("shows the AKN4EU 5.0.1.0 rules as a separate layer, with what is not met", () => {
    const spec = { passed: true, complete: false, verdict: "NOT conformant", failed: [], missing_input: ["OJ_URI", "FRBR_SUBTYPE"], deviations: ["META_SOURCE"], meaning: "" };
    const r: Akn4euReport = { ...report, main_file: "main-OJ_L_2023_165-de.xml", conformance: { ...report.conformance, akn4eu_5_0_1_0_rules: spec },
      files: { "main-OJ_L_2023_165-de.xml": file(), ...report.files }, model_source: { kind: "effective_reviewed_model", model_revision: 2 } };
    expect(akn4euLayers(r).map((l) => [l.name, l.tone])).toContainEqual(["AKN4EU 5.0.1.0 specification rules", "notdone"]);
    const html = renderToStaticMarkup(<Akn4euReportView docId="d1" report={r} selected={null} onView={() => {}} />);
    expect(html).toContain("not met: 2 need information not in the PDF, 1 deliberate deviation(s)");
    expect(html).toContain("OJ entry file · main-OJ_L_2023_165-de.xml");
    expect(html).toContain("built from the reviewed model (revision 2, review NOT approved)");
    const bad = { ...r, conformance: { ...r.conformance, akn4eu_5_0_1_0_rules: { ...spec, passed: false, failed: ["MODEL_COMPLETE"] } } };
    expect(akn4euLayers(bad).find((l) => l.name.startsWith("AKN4EU 5.0.1.0"))).toMatchObject({ tone: "fail", result: "1 mandatory rule(s) violated" });
    expect(html).not.toMatch(/AKN4EU (conformant|compliant|valid)\b/i);
  });

  it("keeps XSD-valid and AKN4EU-conformant apart, and names an unapproved review", () => {
    const spec = { passed: true, complete: false, verdict: "NOT conformant", failed: [], missing_input: ["OJ_URI"], deviations: [], warnings: ["OJ_CLASSIFICATION"], meaning: "" };
    const r: Akn4euReport = { ...report, conformance: { ...report.conformance, akn4eu_5_0_1_0_rules: spec },
      model_source: { kind: "effective_reviewed_model", model_revision: 3, review_state: "in_review", approved: false },
      export_warnings: [{ code: "UNAPPROVED_REVIEW", detail: "built from the reviewed model of revision 3, but the review is 'in_review', not approved" }] };
    const lines = akn4euStatusLines(r);
    expect(lines.map((l) => [l.label, l.tone])).toEqual([["XSD (AKN 3.1)", "ok"], ["AKN4EU 5.0.1.0", "notdone"], ["Official AKN4EU validator", "notdone"]]);
    expect(lines[0].text).toContain("says nothing about AKN4EU conformance");
    expect(lines[1].text).toContain("NOT conformant: 1 required item(s) missing");
    expect(akn4euNotices(r)).toEqual([expect.stringContaining("not approved"), "Recommended (SHOULD) requirements not met: OJ_CLASSIFICATION"]);
    const html = renderToStaticMarkup(<Akn4euReportView docId="d1" report={r} selected={null} onView={() => {}} />);
    expect(html).toContain("review NOT approved");
    expect(html).toContain('data-testid="akn4eu-notice"');
    // an XSD-valid export that violates a mandatory rule is a failure, not a pass
    const bad = { ...r, conformance: { ...r.conformance, akn4eu_5_0_1_0_rules: { ...spec, passed: false, failed: ["ATTACHMENTS"] } } };
    expect(akn4euStatusLines(bad).map((l) => l.tone).slice(0, 2)).toEqual(["ok", "fail"]);
    // approved review: no notice about approval
    const ok = { ...r, export_warnings: [], model_source: { kind: "effective_reviewed_model", model_revision: 3, review_state: "approved", approved: true } };
    expect(akn4euNotices(ok)).toEqual(["Recommended (SHOULD) requirements not met: OJ_CLASSIFICATION"]);
  });
});
