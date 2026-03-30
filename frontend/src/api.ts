/** API client for Paperless IQ backend. */

const BASE = "/api";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new Error(body.detail || resp.statusText);
  }
  return resp.json();
}

export const api = {
  getSettings: () => request<Record<string, unknown>>("/settings"),
  updateSettings: (data: Record<string, unknown>) =>
    request<Record<string, unknown>>("/settings", { method: "PUT", body: JSON.stringify(data) }),

  getQueue: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request<{ items: unknown[]; total: number }>(`/queue${qs}`);
  },
  approveItem: (id: string, edits?: Record<string, unknown>) =>
    request(`/queue/${id}/approve`, { method: "POST", body: JSON.stringify({ edits }) }),
  rejectItem: (id: string) =>
    request(`/queue/${id}/reject`, { method: "POST" }),

  getAuditLog: (params?: Record<string, string>) => {
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    return request<{ items: unknown[]; total: number }>(`/audit${qs}`);
  },

  search: (q: string, topN = 5) =>
    request<{ results: unknown[] }>(`/search?q=${encodeURIComponent(q)}&top_n=${topN}`),

  analyze: (documentId: number, overrides?: Record<string, unknown>) =>
    request("/analyze", { method: "POST", body: JSON.stringify({ document_id: documentId, ...overrides }) }),

  exportConfig: () => request<Record<string, unknown>>("/config/export"),
  importConfig: (data: Record<string, unknown>) =>
    request<{ applied: string[]; skipped: unknown[] }>("/config/import", { method: "POST", body: JSON.stringify(data) }),
};
