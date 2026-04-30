import { useQuery } from "@tanstack/react-query";
import { api } from "../api";

export default function ProcessingPage() {
  const status = useQuery({ queryKey: ["status"], queryFn: api.getStatus, refetchInterval: 3000, retry: false });
  const d = status.data;
  const proc = d?.processing as Record<string, unknown> | undefined;

  return (
    <div>
      <h2>Processing Pipeline</h2>

      <div className="card">
        <h3>System Status</h3>
        <div style={{ display: "flex", gap: "2rem", flexWrap: "wrap", fontSize: "0.9rem" }}>
          <div>
            <span style={{ color: "var(--gray-500)" }}>LLM:</span>{" "}
            <strong style={{ color: d?.llm_online ? "var(--petrol-600)" : "var(--error)" }}>{d?.llm_online ? "online" : "offline"}</strong>
          </div>
          <div>
            <span style={{ color: "var(--gray-500)" }}>Embedding:</span>{" "}
            <strong style={{ color: d?.embed_online ? "var(--petrol-600)" : "var(--error)" }}>{d?.embed_online ? "online" : "offline"}</strong>
          </div>
          <div>
            <span style={{ color: "var(--gray-500)" }}>Approval queue:</span>{" "}
            <strong>{d?.queue_pending ?? 0}</strong> pending
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: "1rem" }}>
        <h3>Current Task</h3>
        {proc?.active_task ? (
          <div style={{ fontSize: "0.9rem" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <span style={{ display: "inline-block", width: "8px", height: "8px", borderRadius: "50%", background: "var(--petrol-500)", animation: "pulse 1.5s infinite" }} />
              <strong>{String(proc.active_task)}</strong>
              <span className="badge badge-pending">{String(proc.active_priority ?? "")}</span>
            </div>
          </div>
        ) : (
          <p style={{ color: "var(--gray-500)", fontSize: "0.9rem" }}>Idle — no task running</p>
        )}
        {(proc?.queue_size as number) > 0 && (
          <p style={{ fontSize: "0.85rem", color: "var(--gray-500)", marginTop: "0.5rem" }}>
            {String(proc?.queue_size)} task(s) waiting in queue
          </p>
        )}
      </div>

      <div className="card" style={{ marginTop: "1rem" }}>
        <h3>Vector Store Indexing</h3>
        {proc?.embedding_active ? (
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.9rem", marginBottom: "0.5rem" }}>
              <span>Indexing documents into vector store…</span>
              <strong>{String(proc.embedding_done)} / {String(proc.embedding_total)}</strong>
            </div>
            <div style={{ background: "var(--gray-200)", borderRadius: "4px", height: "8px", overflow: "hidden" }}>
              <div style={{
                background: "var(--petrol-500)", height: "100%", borderRadius: "4px",
                width: `${Math.min(100, ((proc.embedding_done as number) / Math.max(1, proc.embedding_total as number)) * 100)}%`,
                transition: "width 0.5s ease",
              }} />
            </div>
          </div>
        ) : (
          <div style={{ fontSize: "0.9rem" }}>
            <p style={{ color: "var(--gray-500)" }}>
              {d?.embedded_chunks ? `${d.embedded_chunks} chunks indexed from ${d.total_documents} documents` : "No documents indexed yet"}
            </p>
          </div>
        )}
      </div>

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
      `}</style>
    </div>
  );
}
