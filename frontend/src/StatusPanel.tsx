import { useQuery, useMutation } from "@tanstack/react-query";
import { api } from "./api";

export default function StatusPanel() {
  const { data } = useQuery({
    queryKey: ["status"],
    queryFn: api.getStatus,
    refetchInterval: 15000,
    retry: false,
  });

  const reindex = useMutation({
    mutationFn: api.triggerReindex,
  });

  if (!data) return null;

  const dot = (online: boolean) => (
    <span style={{
      display: "inline-block", width: "8px", height: "8px", borderRadius: "50%",
      background: online ? "#22c55e" : "#ef4444",
      boxShadow: online ? "0 0 4px #22c55e" : "0 0 4px #ef4444",
    }} />
  );

  return (
    <div style={{
      padding: "0.6rem 1.25rem",
      borderTop: "1px solid rgba(255,255,255,0.08)",
      borderBottom: "1px solid rgba(255,255,255,0.08)",
      fontSize: "0.75rem",
      color: "rgba(255,255,255,0.6)",
      display: "flex",
      flexDirection: "column",
      gap: "0.35rem",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span>{dot(data.llm_online)} LLM</span>
        <span>{dot(data.embed_online)} Embed</span>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <span title="Documents waiting for approval">📋 {data.queue_pending} pending</span>
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <span title="Chunks indexed / total documents">
          📊 {data.embedded_chunks} chunks / {data.total_documents} docs
        </span>
      </div>
      <button
        onClick={() => reindex.mutate()}
        disabled={reindex.isPending || !data.embed_online}
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
