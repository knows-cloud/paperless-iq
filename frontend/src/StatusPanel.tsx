import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

export default function StatusPanel() {
  const { data } = useQuery({
    queryKey: ["status"],
    queryFn: api.getStatus,
    refetchInterval: 10000,
    retry: false,
  });

  const d = data ?? { llm_online: false, embed_online: false, queue_pending: 0, embedded_chunks: 0, total_documents: 0, processing: {} };
  const proc = (d.processing ?? {}) as Record<string, unknown>;
  const queueSize = (proc.queue_size as number) ?? 0;
  const embeddingActive = proc.embedding_active as boolean ?? false;
  const embeddingDone = (proc.embedding_done as number) ?? 0;
  const embeddingTotal = (proc.embedding_total as number) ?? 0;
  const chunksOk = d.embedded_chunks > 0;

  const iconStyle = (color: string, flash?: boolean): React.CSSProperties => ({
    display: "inline-block", width: "10px", height: "10px", borderRadius: "50%",
    background: color,
    boxShadow: `0 0 4px ${color}60`,
    animation: flash ? "statusPulse 1.2s infinite" : "none",
  });

  return (
    <div style={{
      padding: "0.5rem 1.25rem",
      borderTop: "1px solid rgba(255,255,255,0.08)",
      borderBottom: "1px solid rgba(255,255,255,0.08)",
      display: "flex",
      justifyContent: "space-around",
      gap: "0.5rem",
    }}>
      <span title={`LLM: ${d.llm_online ? "online" : "offline"}`}
        style={iconStyle(d.llm_online ? "#3b82f6" : "#ef4444")} />
      <span title={`Embedding: ${d.embed_online ? "online" : "offline"}`}
        style={iconStyle(d.embed_online ? "#3b82f6" : "#ef4444")} />
      <span title={`Processing queue: ${queueSize} items`}
        style={iconStyle(queueSize > 15 ? "#ef4444" : "#3b82f6")} />
      <span title={`Vector DB: ${d.embedded_chunks} chunks, ${embeddingDone}/${embeddingTotal} docs indexed`}
        style={iconStyle(
          !chunksOk ? "#ef4444" : "#3b82f6",
          embeddingActive,
        )} />
      <style>{`
        @keyframes statusPulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.2; }
        }
      `}</style>
    </div>
  );
}
