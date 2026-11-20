// TEST-ONLY fixtures for the Rule Extraction tests: records in the shape of Rule JSON 2.0 (backend/schemas/rule-json/rule.schema.json)
// and of the backend's `rules.json` / RuleExtraction status. Never imported by the application: the page shows only what the
// backend returns, and these values must not be mistaken for an extraction result.
import { box, el, modelOf } from "../testing";
import type { DemoResult } from "./fixtures";
import type { RuleExtractionStatus } from "./live";

export const ABS1 = "doc/par-1/abs-1";
export const ABS2 = "doc/par-1/abs-2";

export const model = modelOf([
  el("doc", "document", null, ["doc/par-1"], { region: "document" }),
  el("doc/par-1", "paragraph", "doc", [ABS1, ABS2], { marker: "§ 1", title: "Türen", pages: [1] }),
  el(ABS1, "absatz", "doc/par-1", [], { marker: "(1)", original_text: "(1) Türen müssen mindestens 0,90 m breit sein.", pages: [3], provenance: [box(3, 60, 680, 500, 668)] }),
  el(ABS2, "absatz", "doc/par-1", [], { marker: "(2)", original_text: "(2) Brandabschnitte sind zu begrenzen.", pages: [4], provenance: [box(4, 60, 680, 500, 668)] }),
], { source: { num_pages: 83 } });

export const legal = { title: "Beispielgesetz", frontMatter: [], tableOfContents: [], structure: [{ id: "doc/par-1", children: [] }] };

export const rule = (id: string, summary: string, elementId: string, review: Record<string, unknown> = {}, extra: Record<string, unknown> = {}) => ({
  schemaVersion: "2.0",
  id,
  source: { documentId: "beispielgesetz", documentTitle: "Beispielgesetz", language: "de", citation: `§ 1 ${id}`, elements: [{ elementId, sentenceId: `${elementId}/satz-1`, role: "primary", pdfPages: [3] }] },
  classification: { type: "obligation", normativeCategory: "substantive", summary },
  requirements: [{ kind: "comparison", fact: "tuer.lichte_breite", operator: ">=", value: 0.9, valueType: "number", unit: "m" }],
  review: { status: "draft", machineCheckable: true, checkMethods: ["ids"], notes: ["Model: eu.anthropic.claude-sonnet-4-6 (Amazon Bedrock, eu-central-1)"], ...review },
  ...extra,
});

export const NESTED = { kind: "all", conditions: [{ kind: "comparison", fact: "gebaeude.hoehe", operator: ">", value: 7, valueType: "number", unit: "m" }] };

export const RULE_DOOR = rule("tuer-breite", "Türen müssen eine lichte Breite von mindestens 0,90 m haben.", ABS1,
  { ambiguities: ["ODOS check: unit of 'tuer.lichte_breite' is not stated in the source text", "Der Begriff 'Tür' ist nicht definiert."] },
  { applicability: { targets: [{ entity: "Tür" }], conditions: NESTED } });
export const RULE_FIRE = rule("brandabschnitt", "Brandabschnitte sind zu begrenzen.", ABS2);
export const RULE_FOREIGN = rule("fremd", "Regel mit Quelle außerhalb des Dokuments.", "doc/unknown/abs-9", { status: "reviewed" });

export const generation = {
  provider: "aws-bedrock", modelId: "eu.anthropic.claude-sonnet-4-6", generatedAt: "2026-11-18T19:19:20+00:00", promptVersion: "3",
  counts: { proposed: 4, accepted: 3, rejected: 1, repaired: 0, flagged: 1 },
  coverage: { sentences: 10, sentencesCited: 8, elements: 5, elementsCited: 5, uncitedSentences: [], uncitedElements: [], citedOnlyByRejected: [] },
  rulesRejected: [{ index: 3, id: "abgelehnt-1", reasons: ["applicability/conditions: unknown operator"] }],
};

export const rulesFile = (rules: unknown[], gen: Record<string, unknown> = generation) => ({ _generation: gen, rules });
export const STORED = rulesFile([RULE_DOOR, RULE_FIRE, RULE_FOREIGN]);

export const status = (s: RuleExtractionStatus["status"], extra: Partial<RuleExtractionStatus> = {}): RuleExtractionStatus => ({
  status: s, scope: "document", requestedAt: "2026-11-20T10:00:00+00:00", ...extra,
});

export const demoResult = (ruleJson: unknown | null = null, withLive = true): DemoResult => ({
  title: "Beispielgesetz",
  filename: "MusterBauVerordnung.pdf",
  model,
  json: "{}\n",
  download: { href: "/api/jobs/j1/files/document.json?download=true", name: "x.legal.json" },
  live: withLive ? { jobId: "j1", persistent: true, legal: legal as never, ruleJson, ruleDownload: { href: "/api/jobs/j1/files/rules.json?download=true", name: "x.rules.json" } } : undefined,
});
