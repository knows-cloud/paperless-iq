import { useQuery, useMutation } from "@tanstack/react-query";
import { api } from "./api";

export default function StatusPanel() {
  const { data, isError } = useQuery({
    queryKey: ["status"],
    queryFn: api.getStatus,
    refetchInterval: 30000,
    retry: false,
  });

  const reindex = useMutation({
    mutationFn: api.triggerReindex,
  });

  if (!data && !isError) return null;

  // Colorblind-friendly: blue = online, red = offline
  const dot = (online: boolean) => (
    <span style={{
      display: "inline-block", width: "8px", height: "8px", borderRadius: "50%",
      background: online ? "#3b82f6" : "#ef4444",
      boxShadow: online ? "0 0 4px rgba(59,130,246,0.6)" : "0 0 4px rgba(239,68,68,0.6)",
    }} />
  );

  const statusLabel = (online: boolean) => (
    <span style={{ color: online ? "rgba(255,255,255,0.8)" : "rgba(239,68,68,0.9)", fontSize: "0.72rem" }}>
      {online ? "online" : "offline"}
    </span>
  );

  const d = data ?? { llm_online: false, embed_online: false, queue_pending: 0, embedded_chunks: 0, total_documents: 0 };

  return (
    <div style={{
      padding: "0.6rem 1.25rem",
      borderTop: "1px solid rgba(255,255,255,0.08)",
      borderBottom: "1px solid rgba(255,255,255,0.08)",
      fontSize: "0.75rem",
      color: "rgba(255,255,255,0.6)",
      display: "flex",
      flexDirection: "column",
      gap: "0.3rem",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>{dot(d.llm_online)} LLM {statusLabel(d.llm_online)}</span>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span style={{ display: "flex", alignItems: "center", gap: "4px" }}>{dot(d.embed_online)} Embed {statusLabel(d.embed_online)}</span>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", marginTop: "0.15rem" }}>
        <span title="Documents waiting for approval">📋 {d.queue_pending} pending</span>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <span title="Chunks indexed / total documents">
          📊 {d.embedded_chunks} / {d.total_documents}
        </span>
      </div>
      <button
        onClick={() => reindex.mutate()}
        disabled={reindex.isPending || !d.embed_online}
        style={{
          background: "rgba(255,255,255,0.1)",
          border: "1px solid rgba(255,255,255,0.15)",
          borderRadius: "4px",
          color: "rgba(255,255,255,0.7)",
          padding: "0.25rem 0.5rem",
          fontSize: "0.7rem",
          cursor: reindex.isPending ? "wait" : "pointer",
          marginTop: "0.1rem",
        }}>
        {reindex.isPending ? "Indexing…" : reindex.isSuccess ? "✓ Started" : "↻ Reindex"}
      </button>
    </div>
  );
}
