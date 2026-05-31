/** API client for Paperless IQ backend. */

const BASE = "/api";

const TOKEN_KEY = "piq_session_token";

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setStoredToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearStoredToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getStoredToken();
  const authHeaders: Record<string, string> = token
    ? { Authorization: `Bearer ${token}` }
    : {};

  const resp = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...authHeaders, ...options?.headers },
    ...options,
  });

  if (resp.status === 401) {
    // Token expired or invalid — clear it and notify the app to show login
    clearStoredToken();
    window.dispatchEvent(new CustomEvent("piq-logout"));
    throw new Error("Session expired — please log in again.");
  }

  if (!resp.ok) {
    const body = await resp.json().catch(() => ({ detail: resp.statusText }));
    const detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? resp.statusText);
    throw new Error(detail);
  }
  return resp.json();
}

/** Like `request` but returns a Blob (for binary content like PDFs/images). */
async function requestBlob(path: string): Promise<Blob> {
  const token = getStoredToken();
  const authHeaders: Record<string, string> = token
    ? { Authorization: `Bearer ${token}` }
    : {};
  const resp = await fetch(`${BASE}${path}`, { headers: authHeaders });
  if (resp.status === 401) {
    clearStoredToken();
    window.dispatchEvent(new CustomEvent("piq-logout"));
    throw new Error("Session expired — please log in again.");
  }
  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
  }
  return resp.blob();
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

export interface VisionAnalysisResult {
  suggestion: MetadataSuggestionResponse;
  extracted_content: string | null;
  original_ocr_content: string | null;
  page_count: number;
}

export interface ConnectionTestResult {
  status: "ok" | "error";
  detail?: string;
  version?: string;
}

export interface AuthMeResponse {
  user: string | null;
  auth_required: boolean;
}

export interface UserPermissions {
  username: string;
  ng_admin: boolean;
  can_access: boolean;
  can_view_queue: boolean;
  can_approve: boolean;
  can_analyze: boolean;
  can_discover: boolean;
  can_settings: boolean;
  updated_at?: string | null;
  has_piq_record?: boolean;
}

export const api = {
  // Auth
  getMe: () =>
    fetch(`${BASE}/auth/me`, {
      headers: getStoredToken() ? { Authorization: `Bearer ${getStoredToken()}` } : {},
    }).then(r => r.json()) as Promise<AuthMeResponse>,

  login: (username: string, password: string) =>
    fetch(`${BASE}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    }).then(async r => {
      if (!r.ok) {
        const body = await r.json().catch(() => ({ detail: r.statusText }));
        throw new Error(typeof body.detail === "string" ? body.detail : "Login failed");
      }
      return r.json() as Promise<{ token: string; user: string }>;
    }),

  logout: () => {
    const result = request<{ detail: string }>("/auth/logout", { method: "POST" });
    clearStoredToken();
    return result;
  },

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
    return request<{ items: unknown[]; total: number; page: number; page_size: number }>(`/audit${qs}`);
  },

  exportAuditLog: (params?: Record<string, string>, fmt: "csv" | "json" = "csv") => {
    const p = { ...(params ?? {}), fmt };
    // Strip empty values so they don't become spurious filter params
    const filtered: Record<string, string> = {};
    for (const [k, v] of Object.entries(p)) { if (v) filtered[k] = v; }
    const qs = "?" + new URLSearchParams(filtered).toString();
    const token = getStoredToken();
    const authHeaders: Record<string, string> = token ? { Authorization: `Bearer ${token}` } : {};
    return fetch(`${BASE}/audit/export${qs}`, { headers: authHeaders })
      .then(async r => {
        if (!r.ok) throw new Error(`Export failed: ${r.statusText}`);
        return r.blob();
      });
  },

  search: (q: string, topN = 5) =>
    request<{ results: unknown[]; query: string }>(`/search?q=${encodeURIComponent(q)}&top_n=${topN}`),

  createDiscoverSession: () =>
    request<{ session_id: string }>("/discover/sessions", { method: "POST" }),

  deleteDiscoverSession: (sessionId: string) =>
    request<{ deleted: string }>(`/discover/sessions/${sessionId}`, { method: "DELETE" }),

  discover: (
    question: string,
    topN = 5,
    sessionId: string | null = null,
    history: Array<{ role: string; content: string }> = [],
  ) =>
    request<{ answer: string; sources: Array<{ document_id: number; title: string; score: number; deeplink_url: string; snippet: string }>; question: string; session_id: string | null }>(
      "/discover", { method: "POST", body: JSON.stringify({ question, top_n: topN, session_id: sessionId, history }) }
    ),

  analyze: (documentId: number, overrides?: Record<string, unknown>) =>
    request<MetadataSuggestionResponse>("/analyze", { method: "POST", body: JSON.stringify({ document_id: documentId, ...overrides }) }),

  analyzeVision: (body: { document_id: number; include_content: boolean; max_pages?: number | null }) =>
    request<VisionAnalysisResult>("/analyze/vision", { method: "POST", body: JSON.stringify(body) }),

  getDocumentPageCount: (documentId: number) =>
    request<{ page_count: number }>(`/documents/${documentId}/page-count`),

  updateDocumentContent: (documentId: number, content: string) =>
    request<{ ok: boolean }>(`/documents/${documentId}/content`, {
      method: "PATCH",
      body: JSON.stringify({ content }),
    }),

  getOllamaVisionSupport: () =>
    request<{ supported: boolean | null; reason?: string }>("/ollama/vision-support"),

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
  getTheme: () => request<{ primary_color: string; sidebar_from: string; sidebar_to: string; font: string; font_size: string; text_color: string; bg_color: string; card_color: string; card_alt_hex: string; card_alt_opacity: number; nav_icons: Record<string, string>; ui_language: string; chip_color: string }>("/theme"),
  getStatus: () => request<{ llm_online: boolean; embed_online: boolean; queue_pending: number; queue_processing: number; embedded_chunks: number; total_documents: number; processing: Record<string, unknown>; paperless_url: string; paperless_public_url: string }>("/status"),
  getDocumentPreview: (id: number) => requestBlob(`/documents/${id}/preview`),
  getDocumentThumb: (id: number) => requestBlob(`/documents/${id}/thumb`),
  triggerReindex: () => request<{ detail: string }>("/reindex", { method: "POST" }),
  migrateVectorStore: () => request<{ migrated: number; memories_migrated: number; needs_reindex: boolean; detail: string }>("/vector/migrate", { method: "POST" }),
  reindexSince: (date: string) => request<{ detail: string; count: number }>("/reindex/since", {
    method: "POST",
    body: JSON.stringify({ modified_after: date }),
  }),
  registerWebhook: () => request<{ detail: string; callback_url: string }>("/webhook/register", { method: "POST" }),
  getTrackingStats: () => request<{ tracked_documents: number; suggestions_pending: number; suggestions_approved: number; suggestions_rejected: number }>("/tracking/stats"),
  resetTracking: () => request<{ cleared: number }>("/tracking/reset", { method: "POST" }),
  resetRejected: () => request<{ deleted_suggestions: number; cleared_tracking: number }>("/tracking/reset-rejected", { method: "POST" }),
  // Long-term memories
  getMemories: () =>
    request<Array<{ id: string; text: string; created_at: string; updated_at: string; source_session_id: string | null }>>("/memories"),
  updateMemory: (id: string, text: string) =>
    request<{ id: string; text: string }>(`/memories/${id}`, { method: "PUT", body: JSON.stringify({ text }) }),
  deleteMemory: (id: string) =>
    request<{ deleted: string }>(`/memories/${id}`, { method: "DELETE" }),
  clearMemories: () =>
    request<{ cleared: boolean }>("/memories", { method: "DELETE" }),

  // User permissions
  getMyPermissions: () => request<UserPermissions>("/piq-users/me"),
  listPiqUsers: () => request<UserPermissions[]>("/piq-users"),
  updatePiqUser: (username: string, perms: Omit<UserPermissions, "username" | "ng_admin" | "updated_at">) =>
    request<{ detail: string }>(`/piq-users/${encodeURIComponent(username)}`, {
      method: "PUT",
      body: JSON.stringify(perms),
    }),
  deletePiqUser: (username: string) =>
    request<{ detail: string }>(`/piq-users/${encodeURIComponent(username)}`, { method: "DELETE" }),

  getDocuments: (params?: Record<string, string | string[]>) => {
    const qs = new URLSearchParams();
    if (params) {
      for (const [key, val] of Object.entries(params)) {
        if (Array.isArray(val)) { for (const v of val) qs.append(key, v); }
        else qs.append(key, val);
      }
    }
    const qStr = qs.toString();
    return request<PagedResult<DocumentItem>>(`/documents${qStr ? "?" + qStr : ""}`);
  },
};
