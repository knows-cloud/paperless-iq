import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { t } from "../i18n";

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

  const mutedText: React.CSSProperties = { color: "var(--text-on-card-muted)" };
  const secondaryText: React.CSSProperties = { color: "var(--text-on-card-secondary)" };
  const infoBox: React.CSSProperties = {
    background: "var(--petrol-50)", border: "1px solid var(--petrol-200)",
    borderRadius: "var(--radius-sm)", padding: "0.65rem 1rem",
  };

  return (
    <div>
      <h2>{t("processing.title")}</h2>

      {/* ── System Status ── */}
      <div className="card">
        <h3>{t("processing.systemStatus")}</h3>
        <div style={{
          display: "flex", gap: "2rem", flexWrap: "wrap", fontSize: "0.9rem",
          background: "var(--petrol-50)", border: "1px solid var(--petrol-200)",
          borderRadius: "var(--radius-sm)", padding: "0.65rem 1rem",
        }}>
          <div>
            <span style={mutedText}>{t("processing.llm")}:</span>{" "}
            <strong style={{ color: d?.llm_online ? "var(--success-on-card, var(--success))" : "var(--error-on-card, var(--error))" }}>
              {d?.llm_online ? t("processing.online") : t("processing.offline")}
            </strong>
          </div>
          <div>
            <span style={mutedText}>{t("processing.embedding")}:</span>{" "}
            <strong style={{ color: d?.embed_online ? "var(--success-on-card, var(--success))" : "var(--error-on-card, var(--error))" }}>
              {d?.embed_online ? t("processing.online") : t("processing.offline")}
            </strong>
          </div>
          <div>
            <span style={mutedText}>{t("processing.approvalQueue")}:</span>{" "}
            <strong>{d?.queue_pending ?? 0}</strong>{" "}
            <span style={secondaryText}>{t("processing.pending")}</span>
          </div>
        </div>
      </div>

      {/* ── Processing Queue ── */}
      <div className="card card-alt" style={{ marginTop: "1rem" }}>
        <h3>{t("processing.queue")}</h3>
        <div style={infoBox}>
          {proc?.active_task ? (
            <div style={{ fontSize: "0.9rem" }}>
              <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
                <span style={{ display: "inline-block", width: "8px", height: "8px", borderRadius: "50%", background: "var(--petrol-500)", animation: "pulse 1.5s infinite" }} />
                <strong>{String(proc.active_task)}</strong>
                <span className="badge badge-pending">{String(proc.active_priority ?? "")}</span>
              </div>
            </div>
          ) : (
            <p style={{ ...mutedText, fontSize: "0.9rem", margin: 0 }}>{t("processing.idle")}</p>
          )}
          {((proc?.pending_tasks as string[]) ?? []).length > 0 && (
            <div style={{ marginTop: "0.5rem" }}>
              <p style={{ fontSize: "0.82rem", ...secondaryText, marginBottom: "0.3rem", fontWeight: 500 }}>{t("processing.waiting")}</p>
              {((proc?.pending_tasks as string[]) ?? []).map((label, i) => (
                <div key={i} style={{
                  fontSize: "0.85rem", padding: "0.25rem 0.5rem", marginBottom: "2px",
                  background: i % 2 === 0 ? "transparent" : "rgba(0,0,0,0.04)",
                  borderRadius: "var(--radius-sm)",
                }}>
                  {label}
                </div>
              ))}
            </div>
          )}
          {!proc?.active_task && ((proc?.pending_tasks as string[]) ?? []).length === 0 && null}
        </div>
      </div>

      {/* ── Vector Store Indexing ── */}
      <div className="card" style={{ marginTop: "1rem" }}>
        <h3>{t("processing.vectorStore")}</h3>
        <div style={infoBox}>
          {proc?.embedding_active ? (
            <div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.9rem", marginBottom: "0.5rem" }}>
                <span>{t("processing.indexingDocs")}</span>
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
            <p style={{ ...mutedText, fontSize: "0.9rem", margin: 0 }}>
              {d?.embedded_chunks
                ? t("processing.chunksIndexed", { chunks: String(d.embedded_chunks), docs: String(d.total_documents) })
                : t("processing.noDocsYet")}
            </p>
          )}
        </div>
      </div>

      {/* ── Document Tracking ── */}
      <div className="card card-alt" style={{ marginTop: "1rem" }}>
        <h3>{t("processing.tracking")}</h3>
        {tr && (
          <div style={infoBox}>
            <div style={{ fontSize: "0.9rem" }}>
              <div style={{ display: "flex", gap: "2rem", flexWrap: "wrap", marginBottom: "0.75rem" }}>
                <div><span style={mutedText}>{t("processing.trackedLabel")}</span> <strong>{tr.tracked_documents}</strong></div>
                <div>
                  <span style={mutedText}>{t("processing.approvedLabel")}</span>{" "}
                  <strong style={{ color: "var(--success-on-card, var(--success))" }}>{tr.suggestions_approved}</strong>
                </div>
                <div>
                  <span style={mutedText}>{t("processing.rejectedLabel")}</span>{" "}
                  <strong style={{ color: "var(--error-on-card, var(--error))" }}>{tr.suggestions_rejected}</strong>
                </div>
                <div><span style={mutedText}>{t("processing.pendingLabel")}</span> <strong>{tr.suggestions_pending}</strong></div>
              </div>
              <p style={{ fontSize: "0.82rem", ...mutedText, marginBottom: "0.75rem" }}>
                {t("processing.trackingHint")}
              </p>
              <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                <button className="btn" onClick={() => setShowResetConfirm("rejected")}
                  disabled={!tr.suggestions_rejected}>
                  {t("processing.resetRejected", { count: String(tr.suggestions_rejected) })}
                </button>
                <button className="btn" onClick={() => setShowResetConfirm("all")}>
                  {t("processing.resetAll")}
                </button>
                <button className="btn" onClick={() => reindex.mutate()} disabled={reindex.isPending}>
                  {reindex.isPending ? t("processing.reindexing") : t("processing.reindex")}
                </button>
              </div>
            </div>
          </div>
        )}
        {showResetConfirm && (
          <div style={{
            marginTop: "0.75rem", padding: "0.75rem",
            background: "rgba(234, 88, 12, 0.12)",
            borderRadius: "var(--radius-sm)",
            border: "1px solid rgba(234, 88, 12, 0.3)",
          }}>
            <p style={{ fontWeight: 600, margin: "0 0 0.5rem" }}>
              {showResetConfirm === "all"
                ? t("processing.confirmResetAll")
                : t("processing.confirmResetRejected", { count: String(tr?.suggestions_rejected ?? 0) })}
            </p>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button className="btn btn-danger"
                onClick={() => showResetConfirm === "all" ? resetAll.mutate() : resetRejected.mutate()}
                disabled={resetAll.isPending || resetRejected.isPending}>
                {resetAll.isPending || resetRejected.isPending ? t("processing.resetting") : t("processing.confirmBtn")}
              </button>
              <button className="btn" onClick={() => setShowResetConfirm(null)}>{t("processing.cancel")}</button>
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
