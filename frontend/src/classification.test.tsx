import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ClassificationPanel } from "./components/ClassificationPanel";
import { classificationView, evidenceRows, modeChoiceNote } from "./classification";
import type { Classification } from "./types";

const base: Classification = {
  document_type: "eu_regulation", suggested_processing_mode: "eu_legislation", candidate_mode: null, confidence_band: "high",
  confidence_note: "Confidence is a heuristic band, not a probability.", support_status: "supported", supported: true,
  summary: "x", points: { eu_regulation: 26 }, warnings: ["The EU parser has been tested on Regulation (EU) 2023/1230 only."],
  evidence: [
    { rule_id: "eu_official_journal", description: "Official Journal indicator", supports: ["eu_regulation"], weight: 3, page: 1, snippet: "Amtsblatt der Europäischen Union", source_ref: "pdf_text_layer:p1:l2", count: null },
    { rule_id: "eu_regulation_title", description: "Title block names a regulation", supports: ["eu_regulation"], weight: 5, page: 1, snippet: "VERORDNUNG (EU) 2023/1230", source_ref: "pdf_text_layer:p1:l9", count: null },
    { rule_id: "eu_article_headings", description: "54 stand-alone 'Artikel n' headings", supports: ["eu_regulation"], weight: 3, page: 11, snippet: "Artikel 1", source_ref: null, count: 54 },
  ],
  input: { source: "pdf_text_layer", pages_total: 102, pages_scanned: 102, lines: 5000, characters: 300000 },
};
const directive: Classification = { ...base, document_type: "eu_directive", suggested_processing_mode: "extract_only", support_status: "recognised_not_supported", supported: false, candidate_mode: null };
const uncertain: Classification = { ...base, document_type: "german_law", suggested_processing_mode: "extract_only", candidate_mode: "german_law", confidence_band: "low", support_status: "uncertain", supported: false };
const unknown: Classification = { ...base, document_type: "unknown", suggested_processing_mode: "extract_only", confidence_band: "low", support_status: "unsupported", supported: false, evidence: [] };

describe("classificationView", () => {
  it("presents a confident supported type as a suggestion", () => {
    const v = classificationView(base);
    expect(v.headline).toBe("Detected: EU regulation");
    expect(v.detail).toMatch(/High confidence \(heuristic\)\. Suggested mode: EU legislation \(prototype\)/);
    expect(v.uncertain).toBe(false);
    expect(v.detail).not.toMatch(/%/); // never a percentage
  });
  it("says plainly when a type is recognised but unsupported (directive)", () => {
    const v = classificationView(directive);
    expect(v.headline).toBe("Detected: EU directive");
    expect(v.detail).toMatch(/No structured pipeline supports this type yet/);
    expect(v.tone).toBe("warn");
  });
  it("flags uncertain classifications and points to the manual choice", () => {
    const v = classificationView(uncertain);
    expect(v.uncertain).toBe(true);
    expect(v.headline).toBe("Possibly: German law (§ structure)");
    expect(v.detail).toMatch(/You can still choose German law \(prototype\)/);
  });
  it("handles unknown documents", () => {
    expect(classificationView(unknown).headline).toBe("Document type not recognised");
  });
  it("asks for a check on medium confidence", () => {
    expect(classificationView({ ...base, confidence_band: "medium" }).detail).toMatch(/check the evidence/);
  });
});

describe("modeChoiceNote", () => {
  it("is silent when the suggestion is followed or nothing is known", () => {
    expect(modeChoiceNote(base, "eu_legislation")).toBeNull();
    expect(modeChoiceNote(null, "german_law")).toBeNull();
  });
  it("warns on a mismatching structured mode", () => {
    expect(modeChoiceNote(base, "german_law")).toMatch(/Manual override: this document was classified as EU regulation/);
    expect(modeChoiceNote(directive, "eu_legislation")).toMatch(/classified as EU directive/);
  });
  it("explains choosing extraction only and choosing a candidate mode on low confidence", () => {
    expect(modeChoiceNote(base, "extract_only")).toMatch(/text extraction only/);
    expect(modeChoiceNote(uncertain, "german_law")).toMatch(/not confident enough/);
  });
});

describe("evidence and panel", () => {
  it("lists the strongest evidence first with snippets and pages", () => {
    const rows = evidenceRows(base);
    expect(rows.map((r) => r.key)).toEqual(["eu_regulation_title", "eu_article_headings", "eu_official_journal"]);
    expect(rows[0].text).toContain("“VERORDNUNG (EU) 2023/1230”");
    expect(rows[1].text).toContain("54 stand-alone");
    expect(evidenceRows({ ...base, evidence: [{ ...base.evidence[2], snippet: null }] })[0].text).toContain("(54×)");
  });
  it("renders headline, band, warnings and evidence (high confidence collapses the evidence)", () => {
    const html = renderToStaticMarkup(<ClassificationPanel classification={base} onGoToPage={() => {}} />);
    expect(html).toContain("Detected: EU regulation");
    expect(html).toContain("band-high");
    expect(html).toContain("tested on Regulation (EU) 2023/1230 only");
    expect(html).toContain("Show evidence (3)");
  });
  it("opens the evidence by default when the band is not high", () => {
    const html = renderToStaticMarkup(<ClassificationPanel classification={uncertain} onGoToPage={() => {}} />);
    expect(html).toContain("Hide evidence");
    expect(html).toContain("p. 11");
    expect(html).toContain("not a probability");
  });
});
