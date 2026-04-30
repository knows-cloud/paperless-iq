/** API client for Paperless IQ backend. */

const BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({ detail: resp.statusText }));
    const detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? resp.statusText);
    throw new Error(detail);
  }
  return resp.json();
}

export interface PaperlessEntity { id: number; name: string; }
export interface PaperlessCustomField { id: number; name: string; data_type: string; }
export interface DocumentItem {
  id: number; title: string; correspondent: number | null;
  document_type: number | null; tags: number[]; created: string; added: string;
}
export interface PagedResult<T> { items: T[]; total: number; page: number; page_size: number; }

export interface MetadataSuggestionResponse {
  id: string;
  document_id: number;
  status: string;
  title: string | null;
  tags: string[];
  correspondent: string | null;
  document_type: string | null;
  storage_path: string | null;
  custom_fields: Record<string, unknown>;
  llm_provider: string;
  llm_model: string;
}

export interface ConnectionTestResult {
  status: "ok" | "error";
  detail?: string;
  version?: string;
}

export const api = {
  getSettings: () => request<Record<string, unknown>>("/settings"),
  updateSettings: (data: Record<string, unknown>) =>
    request<Record<string, unknown>>("/settings", { method: "PUT", body: JSON.stringify(data) }),

  getQueue: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request<{ items: unknown[]; total: number }>(`/queue${qs}`);
  },
  approveItem: (id: string, opts?: { edits?: Record<string, unknown>; merge_tags?: boolean; create_missing?: boolean }) =>
    request(`/queue/${id}/approve`, { method: "POST", body: JSON.stringify(opts ?? {}) }),
  rejectItem: (id: string) =>
    request(`/queue/${id}/reject`, { method: "POST" }),
  emptyQueue: () =>
    request<{ rejected_count: number }>("/queue/empty", { method: "POST" }),
  reanalyzeItem: (suggestionId: string) =>
    request("/queue/reanalyze", { method: "POST", body: JSON.stringify({ suggestion_id: suggestionId }) }),
  reanalyzeAll: () =>
    request<{ detail: string }>("/queue/reanalyze-all", { method: "POST" }),
  getDocumentTags: (documentId: number) =>
    request<string[]>(`/documents/${documentId}/tags`),

  getAuditLog: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request<{ items: unknown[]; total: number }>(`/audit${qs}`);
  },

  search: (q: string, topN = 5) =>
    request<{ results: unknown[]; query: string }>(`/search?q=${encodeURIComponent(q)}&top_n=${topN}`),

  discover: (question: string, topN = 5) =>
    request<{ answer: string; sources: Array<{ document_id: number; title: string; score: number; deeplink_url: string; snippet: string }>; question: string }>(
      "/discover", { method: "POST", body: JSON.stringify({ question, top_n: topN }) }
    ),

  analyze: (documentId: number, overrides?: Record<string, unknown>) =>
    request<MetadataSuggestionResponse>("/analyze", { method: "POST", body: JSON.stringify({ document_id: documentId, ...overrides }) }),

  exportConfig: () => request<Record<string, unknown>>("/config/export"),
  importConfig: (data: Record<string, unknown>) =>
    request<{ applied: string[]; skipped: unknown[] }>("/config/import", { method: "POST", body: JSON.stringify(data) }),
  translatePrompt: (text: string, targetLanguage: string) =>
    request<{ translated: string }>("/translate-prompt", { method: "POST", body: JSON.stringify({ text, target_language: targetLanguage }) }),

  testPaperlessConnection: () => request<ConnectionTestResult>("/paperless/test"),
  enqueueSuggestion: (suggestion: MetadataSuggestionResponse) =>
    request<MetadataSuggestionResponse>("/queue", { method: "POST", body: JSON.stringify(suggestion) }),

  // Paperless NGX proxy
  getTags: () => request<PaperlessEntity[]>("/paperless/tags"),
  getCorrespondents: () => request<PaperlessEntity[]>("/paperless/correspondents"),
  getDocumentTypes: () => request<PaperlessEntity[]>("/paperless/document_types"),
  getCustomFields: () => request<PaperlessCustomField[]>("/paperless/custom_fields"),
  getStoragePaths: () => request<PaperlessEntity[]>("/paperless/storage_paths"),
  getLogos: () => request<string[]>("/logos"),
  getTheme: () => request<{ primary_color: string; sidebar_from: string; sidebar_to: string; font: string; font_size: string; text_color: string; bg_color: string; card_color: string; card_alt_hex: string; card_alt_opacity: number; logo: string; nav_icons: Record<string, string>; ui_language: string }>("/theme"),
  getStatus: () => request<{ llm_online: boolean; embed_online: boolean; queue_pending: number; queue_processing: number; embedded_chunks: number; total_documents: number; processing: Record<string, unknown> }>("/status"),
  triggerReindex: () => request<{ detail: string }>("/reindex", { method: "POST" }),
  getDocuments: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request<PagedResult<DocumentItem>>(`/documents${qs}`);
  },
};
