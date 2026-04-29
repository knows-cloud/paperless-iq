import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";

export default function ProcessingPage() {
  const [expanded, setExpanded] = useState(true);
  const status = useQuery({ queryKey: ["status"], queryFn: api.getStatus, refetchInterval: 5000, retry: false });
  const queue = useQuery({ queryKey: ["queue-all"], queryFn: () => api.getQueue({ status: "pending" }), refetchInterval: 10000, retry: false });

  const d = status.data;
  const items = (queue.data?.items ?? []) as Array<Record<string, unknown>>;

  return (
    <div>
      <h2>Processing</h2>

      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h3 style={{ margin: 0 }}>Current Status</h3>
          {d && (
            <div style={{ display: "flex", gap: "1rem", fontSize: "0.85rem" }}>
              <span>LLM: <strong style={{ color: d.llm_online ? "var(--petrol-600)" : "var(--error)" }}>{d.llm_online ? "online" : "offline"}</strong></span>
              <span>Embed: <strong style={{ color: d.embed_online ? "var(--petrol-600)" : "var(--error)" }}>{d.embed_online ? "online" : "offline"}</strong></span>
            </div>
          )}
        </div>
        {d && (
          <div style={{ marginTop: "0.75rem", fontSize: "0.85rem" }}>
            <div style={{ display: "flex", gap: "2rem" }}>
              <div>
                <span style={{ color: "var(--gray-500)" }}>Pending approval:</span>{" "}
                <strong>{d.queue_pending}</strong>
              </div>
              <div>
                <span style={{ color: "var(--gray-500)" }}>Indexed chunks:</span>{" "}
                <strong>{d.embedded_chunks}</strong> / {d.total_documents} docs
              </div>
            </div>
            {d.embedded_chunks < d.total_documents && d.total_documents > 0 && (
              <div style={{ marginTop: "0.5rem" }}>
                <div style={{ background: "var(--gray-200)", borderRadius: "4px", height: "6px", overflow: "hidden" }}>
                  <div style={{
                    background: "var(--petrol-500)", height: "100%", borderRadius: "4px",
                    width: `${Math.min(100, (d.embedded_chunks / Math.max(1, d.total_documents * 5)) * 100)}%`,
                    transition: "width 0.5s ease",
                  }} />
                </div>
                <small style={{ color: "var(--gray-500)" }}>Embedding progress (approximate)</small>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="card" style={{ marginTop: "1rem" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer" }}
          onClick={() => setExpanded(!expanded)}>
          <h3 style={{ margin: 0 }}>
            <span style={{ fontSize: "0.75rem", display: "inline-block", transform: expanded ? "rotate(90deg)" : "rotate(0deg)", transition: "transform 0.2s", marginRight: "0.5rem" }}>▶</span>
            Approval Queue ({items.length})
          </h3>
        </div>
        {expanded && (
          <div style={{ marginTop: "0.75rem" }}>
            {items.length === 0 && <p style={{ color: "var(--gray-500)", fontSize: "0.85rem" }}>No documents waiting for approval.</p>}
            {items.map((item, idx) => (
              <div key={String(item.id)} style={{
                padding: "0.5rem 0.75rem", fontSize: "0.85rem",
                borderBottom: idx < items.length - 1 ? "1px solid var(--gray-200)" : "none",
                background: idx % 2 === 1 ? "var(--card-alt-bg, rgba(26,114,136,0.06))" : "transparent",
              }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <span><strong>Doc {String(item.document_id)}</strong> — {String(item.title ?? "Untitled")}</span>
                  <span className="badge badge-pending">pending</span>
                </div>
                {(item.tags as string[] | undefined)?.length ? (
                  <div style={{ fontSize: "0.8rem", color: "var(--gray-500)", marginTop: "0.2rem" }}>
                    Tags: {(item.tags as string[]).join(", ")}
                  </div>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
