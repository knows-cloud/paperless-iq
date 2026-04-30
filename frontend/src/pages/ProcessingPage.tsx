import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";

export default function ProcessingPage() {
  const qc = useQueryClient();
  const status = useQuery({ queryKey: ["status"], queryFn: api.getStatus, refetchInterval: 3000, retry: false });
  const tracking = useQuery({ queryKey: ["tracking"], queryFn: api.getTrackingStats, refetchInterval: 10000, retry: false });
  const [showResetConfirm, setShowResetConfirm] = useState<string | null>(null);
  const d = status.data;
  const proc = d?.processing as Record<string, unknown> | undefined;
  const tr = tracking.data;

  const resetAll = useMutation({ mutationFn: api.resetTracking, onSuccess: () => { qc.invalidateQueries({ queryKey: ["tracking"] }); setShowResetConfirm(null); } });
  const resetRejected = useMutation({ mutationFn: api.resetRejected, onSuccess: () => { qc.invalidateQueries({ queryKey: ["tracking"] }); setShowResetConfirm(null); } });
  const reindex = useMutation({ mutationFn: api.triggerReindex });

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

      <div className="card" style={{ marginTop: "1rem" }}>
        <h3>Document Tracking</h3>
        {tr && (
          <div style={{ fontSize: "0.9rem" }}>
            <div style={{ display: "flex", gap: "2rem", flexWrap: "wrap", marginBottom: "0.75rem" }}>
              <div><span style={{ color: "var(--gray-500)" }}>Tracked (seen):</span> <strong>{tr.tracked_documents}</strong></div>
              <div><span style={{ color: "var(--gray-500)" }}>Approved:</span> <strong style={{ color: "var(--success)" }}>{tr.suggestions_approved}</strong></div>
              <div><span style={{ color: "var(--gray-500)" }}>Rejected:</span> <strong style={{ color: "var(--error)" }}>{tr.suggestions_rejected}</strong></div>
              <div><span style={{ color: "var(--gray-500)" }}>Pending:</span> <strong>{tr.suggestions_pending}</strong></div>
            </div>
            <p style={{ fontSize: "0.82rem", color: "var(--gray-500)", marginBottom: "0.75rem" }}>
              "Tracked" documents are ones the inbox monitor has seen. They won't be re-analyzed
              unless you reset the tracking. Rejected documents stay tracked unless explicitly reset.
            </p>
            <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
              <button className="btn" onClick={() => setShowResetConfirm("rejected")}
                disabled={!tr.suggestions_rejected}>
                Reset Rejected ({tr.suggestions_rejected})
              </button>
              <button className="btn" onClick={() => setShowResetConfirm("all")}>
                Reset All Tracking
              </button>
              <button className="btn" onClick={() => reindex.mutate()} disabled={reindex.isPending}>
                {reindex.isPending ? "Reindexing…" : "↻ Reindex Vector Store"}
              </button>
            </div>
          </div>
        )}
        {showResetConfirm && (
          <div style={{ marginTop: "0.75rem", padding: "0.75rem", background: "#fff3e0", borderRadius: "var(--radius-sm)", border: "1px solid #ffcc80" }}>
            <p style={{ fontWeight: 600, margin: "0 0 0.5rem" }}>
              {showResetConfirm === "all"
                ? "⚠️ Reset all tracking? All inbox documents will be re-analyzed on the next poll cycle."
                : `⚠️ Reset ${tr?.suggestions_rejected ?? 0} rejected documents? They will be re-analyzed on the next poll cycle.`}
            </p>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button className="btn btn-danger"
                onClick={() => showResetConfirm === "all" ? resetAll.mutate() : resetRejected.mutate()}
                disabled={resetAll.isPending || resetRejected.isPending}>
                {resetAll.isPending || resetRejected.isPending ? "Resetting…" : "Confirm Reset"}
              </button>
              <button className="btn" onClick={() => setShowResetConfirm(null)}>Cancel</button>
            </div>
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
