// Mirrors the FastAPI response schemas (odos.api.schemas / odos.document_model).
export type JobState = "uploaded" | "queued" | "processing" | "completed" | "failed";
export type ProcessingMode = "german_law" | "eu_legislation" | "extract_only";

export interface ArtifactInfo {
  type: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  url: string;
}

export type DocumentType = "german_law" | "german_model_regulation" | "eu_regulation" | "eu_directive" | "technical_standard" | "unknown";
export type ConfidenceBand = "high" | "medium" | "low";
export type SupportStatus = "supported" | "recognised_not_supported" | "uncertain" | "unsupported";

export interface Evidence {
  rule_id: string;
  description: string;
  supports: DocumentType[];
  weight: number;
  page: number | null;
  snippet: string | null;
  source_ref: string | null;
  count: number | null;
}

export interface Classification {
  document_type: DocumentType;
  suggested_processing_mode: ProcessingMode;
  candidate_mode: ProcessingMode | null;
  confidence_band: ConfidenceBand;
  confidence_note: string;
  support_status: SupportStatus;
  supported: boolean;
  summary: string;
  evidence: Evidence[];
  points: Record<string, number>;
  warnings: string[];
  input: { source: string; pages_total: number; pages_scanned: number; lines: number; characters: number };
}

export interface Routing {
  document_type: string | null;
  suggested_mode: string | null;
  chosen_mode: ProcessingMode;
  manual_override: boolean;
  warnings: string[];
}

export interface DocumentStatus {
  id: string;
  filename: string;
  size_bytes: number;
  uploaded_at: string;
  status: JobState;
  stage: string | null;
  mode: ProcessingMode | null;
  outcome: "completed" | "unsupported" | null;
  message: string | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  summary: Record<string, unknown>;
  routing?: Routing | null;
  artifacts: ArtifactInfo[];
  document_type?: string | null; // recognised type (classification), derived by the API
  review_state?: string | null; // human review state if a review exists, derived by the API
}

// Document deletion (odos.api.schemas.DeletionPreview / DeleteResult)
export interface DeletionItem {
  category: string;
  label: string;
  files: number;
  size_bytes: number;
  details: string[];
}
export interface DeletionPreview {
  id: string;
  filename: string;
  can_delete: boolean;
  blocked_reason: string | null;
  items: DeletionItem[];
  total_files: number;
  total_bytes: number;
}
export interface DeleteResult {
  id: string;
  filename: string;
  deleted: boolean;
  removed: DeletionPreview;
}

export interface BoundingBox {
  l: number;
  t: number;
  r: number;
  b: number;
  coord_origin: string;
}

export interface Provenance {
  page_no: number;
  bbox: BoundingBox | null;
  charspan: [number, number] | null;
}

export interface SourceSpan {
  ref: string;
  start: number;
  end: number;
  page_no: number | null;
  bbox: BoundingBox | null;
  bbox_scope: "docling_item"; // the box covers the whole Docling item, not just this text segment
}

export interface DocElement {
  id: string;
  type: string;
  region: "document" | "front" | "toc" | "preamble" | "body" | "conclusions" | "annex" | "furniture";
  parent_id: string | null;
  children_ids: string[];
  number: string | null;
  marker: string | null;
  title: string | null;
  original_text: string;
  content_text: string;
  table: { num_rows: number; num_cols: number; rows: string[][] } | null;
  source_refs: string[];
  docling_label: string | null;
  pages: number[];
  provenance: Provenance[];
  uncertain: boolean;
  uncertainty_reasons: string[];
  source_spans?: SourceSpan[]; // present only for segments of a split Docling item
  highlight_boxes?: Provenance[]; // exact per-line rectangles proven from the PDF glyphs (else provenance is drawn)
  reviewed?: { fields: Record<string, { original: string | null; corrected: string }>; corrections: string[]; verbatim_from_source: false } | null;
  search_text?: string | null;
  hygiene_flags?: string[];
}

export interface ParserWarning {
  code: string;
  severity: "info" | "warning";
  message: string;
  element_id: string | null;
  source_ref: string | null;
}

export interface DocumentMetadata {
  title: string | null;
  short_title: string | null;
  ausfertigungsdatum: string | null;
  stand: string | null;
  vollzitat: string | null;
  document_type?: string | null;
  document_number?: string | null;
  issuing_bodies?: string | null;
  adoption_date_text?: string | null;
  adoption_date?: string | null;
  subject?: string | null;
  eea_relevance?: boolean | null;
  publication_journal?: string | null;
  publication_reference?: string | null;
  publication_date_text?: string | null;
  publication_date?: string | null;
  metadata_provenance?: Record<string, string[]>;
}

export interface DocumentModel {
  model_version: string;
  profile?: string | null; // "eu_legislation"; absent for the German-law parser
  source: { filename: string | null; docling_version: string | null; docling_json_sha256: string; num_pages: number };
  metadata: DocumentMetadata;
  root_id: string;
  elements: DocElement[];
  furniture: DocElement[];
  warnings: ParserWarning[];
  toc_entries?: TocEntry[]; // normalized TOC lines in printed order (derived, read-only)
}

export interface TocEntry {
  id: string;
  kind: string;
  marker: string;
  number: string | null;
  title: string | null;
  level: number;
  source_element_ids: string[]; // the raw Docling TOC elements the entry's characters come from
  target_id: string | null; // confirmed body element (kind, number, title and hierarchy agree)
  candidate_ids: string[];
  status: "linked" | "candidate" | "unmatched" | "ambiguous";
  evidence: string;
}

export interface TraceNode {
  model_id: string;
  eId: string | null;
  akn_element: string | null;
}

export type ReviewState = "pending_review" | "in_review" | "changes_requested" | "approved";
export type EditableField = "content_text" | "title" | "marker";

export interface Correction {
  id: string;
  element_id: string;
  field: EditableField;
  original_value: string | null;
  previous_value: string | null;
  corrected_value: string;
  timestamp: string;
  review_revision: number;
  model_revision: number;
  note: string | null;
  reviewer: string | null;
}

export interface Confirmation { element_id: string; reasons: string[]; timestamp: string; review_revision: number; note: string | null }

export interface RevisionValidation {
  model_revision: number;
  generated: boolean;
  xsd_valid: boolean | null;
  xsd_errors: string[];
  text_identical_to_reviewed_model: boolean | null;
  uncorrected_text_differences: string[];
  corrected_elements: string[];
  blocking_errors: string[];
  xml_sha256: string | null;
}

export interface Approval { review_revision: number; model_revision: number; model_sha256: string; xml_sha256: string; approved_at: string; note: string | null; confirmed_uncertain: number; corrections: number }

export interface ReviewView {
  document_id: string;
  state: ReviewState;
  review_revision: number;
  model_revision: number;
  corrections: Correction[];
  confirmations: Confirmation[];
  corrected_element_ids: string[];
  uncertain_element_ids: string[];
  unresolved_uncertain_ids: string[];
  validation: RevisionValidation | null;
  can_approve: boolean;
  approval_blockers: string[];
  approval: Approval | null;
  exports: { model_revision: number; xml_sha256: string | null; xsd_valid: boolean | null; status: string; created_at: string }[];
  original_export_superseded: boolean;
  structural_editing_supported: boolean;
  history: { at: string; event: string; review_revision: number; detail: string | null }[];
}

// AKN4EU export (odos.akn.akn4eu_artifacts): three validation layers kept apart, never one "valid"
export interface Akn4euFileReport {
  bytes: number;
  xml_sha256: string;
  valid_akn_3_1: boolean;
  errors: { line: number; message: string }[];
  sample_checks: { passed: boolean; findings: { rule: string; message: string }[] };
}

export interface Akn4euReport {
  profile: "akn4eu";
  status: string;
  conformance: {
    oasis_akn_3_1_xsd: { valid: boolean; schema_version: string; schema_files: { file: string; sha256: string; source: string }[] };
    akn4eu_sample_checks: { passed: boolean; rules: number; meaning: string };
    official_akn4eu_validation: { performed: boolean; reason: string };
    text_and_order_against_model: boolean;
  };
  files: Record<string, Akn4euFileReport>;
  act_file: string;
  package: string;
  identifiers: { eli: string | null; resource_type: string; authors: string[]; language: string; akn4eu_version: string };
  scope: { articles: number; recitals: number; annexes: number; retrieval_date: string };
  generator_warnings: { code: string; model_id?: string; detail?: string }[];
  unmapped: unknown[];
  text_preservation_summary: { same_order_and_text: boolean; atoms_compared: number; characters_compared: number; footnotes: { total: number; at_reference: number; end_of_text: number } };
}
