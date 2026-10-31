import type { Akn4euReport, Classification, DeleteResult, DeletionPreview, DocumentModel, DocumentStatus, EditableField, ProcessingMode, ReviewView } from "./types";

// Relative by default (Vite proxies /api in development); override with VITE_API_BASE if the API lives elsewhere.
const BASE: string = import.meta.env.VITE_API_BASE ?? "";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit, parse: "json" | "text" = "json"): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, init);
  } catch {
    throw new ApiError(0, "network", "Cannot reach the ODOS API. Is the backend running (odos serve)?");
  }
  if (!res.ok) {
    let code = "error";
    let message = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.code) code = body.code;
      if (body?.message) message = body.message;
      else if (Array.isArray(body?.detail)) message = "Invalid request: " + body.detail.map((d: { msg: string }) => d.msg).join("; ");
    } catch {
      /* keep defaults */
    }
    throw new ApiError(res.status, code, message);
  }
  return (parse === "json" ? res.json() : res.text()) as Promise<T>;
}

function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

export const api = {
  listDocuments: () => request<DocumentStatus[]>("/api/documents"),
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<DocumentStatus>("/api/documents", { method: "POST", body: form });
  },
  process: (id: string, mode: ProcessingMode) =>
    request<DocumentStatus>(`/api/documents/${id}/process`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    }),
  health: () => request<{ status: string }>("/api/health"),
  deletionPreview: (id: string) => request<DeletionPreview>(`/api/documents/${id}/deletion-preview`),
  deleteDocument: (id: string) => request<DeleteResult>(`/api/documents/${id}`, { method: "DELETE" }),
  status: (id: string) => request<DocumentStatus>(`/api/documents/${id}/status`),
  classification: (id: string, refresh = false) =>
    request<Classification>(`/api/documents/${id}/classification${refresh ? "?refresh=true" : ""}`),
  review: (id: string) => request<ReviewView>(`/api/documents/${id}/review`),
  reviewModel: (id: string, revision?: number) =>
    request<DocumentModel>(`/api/documents/${id}/review/model${revision != null ? `?revision=${revision}` : ""}`),
  correct: (id: string, body: { base_revision: number; element_id: string; field: EditableField; value: string; note?: string }) =>
    post<ReviewView>(`/api/documents/${id}/review/corrections`, body),
  confirm: (id: string, body: { base_revision: number; element_id: string; note?: string }) =>
    post<ReviewView>(`/api/documents/${id}/review/confirmations`, body),
  decide: (id: string, action: "approve" | "request-changes" | "reopen", body: { base_revision: number; note?: string }) =>
    post<ReviewView>(`/api/documents/${id}/review/${action}`, body),
  revisionUrl: (id: string, revision: number, kind: "xml" | "validation" | "traceability" | "text_report" | "review_validation") =>
    `${BASE}/api/documents/${id}/review/revisions/${revision}/${kind}`,
  akn4eu: (id: string) => request<Akn4euReport>(`/api/documents/${id}/exports/akn4eu`),
  generateAkn4eu: (id: string, eli?: string) => post<Akn4euReport>(`/api/documents/${id}/exports/akn4eu`, eli ? { eli } : {}),
  akn4euFileUrl: (id: string, name: string) => `${BASE}/api/documents/${id}/exports/akn4eu/files/${encodeURIComponent(name)}`,
  akn4euUrl: (id: string, kind: "package" | "report" | "traceability" | "text_report") => `${BASE}/api/documents/${id}/exports/akn4eu/${kind}`,
  structure: (id: string) => request<DocumentModel>(`/api/documents/${id}/structure`),
  artifactText: (url: string) => request<string>(url, undefined, "text"),
  originalUrl: (id: string) => `${BASE}/api/documents/${id}/original`,
  artifactUrl: (url: string) => `${BASE}${url}`,
};
