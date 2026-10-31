import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Akn4euReportView } from "./components/Akn4euPanel";
import { akn4euHeadline, akn4euLayers } from "./exports";
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
});
