import { useState, useMemo, useEffect, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type PaperlessEntity, type PaperlessCustomField } from "../api";
import TagInput from "../TagInput";
import AutocompleteInput from "../AutocompleteInput";
import CfNameEditor from "../CfNameEditor";
import { t } from "../i18n";

interface QueueItem {
  id: string;
  document_id: number;
  title: string | null;
  tags: string[];
  correspondent: string | null;
  document_type: string | null;
  storage_path: string | null;
  custom_fields: Record<string, unknown>;
}

export default function QueuePage() {
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["queue"], queryFn: () => api.getQueue({ status: "pending" }) });
  const statusQ = useQuery({ queryKey: ["status"], queryFn: api.getStatus, retry: false, staleTime: 60_000 });
  const tagsQ = useQuery({ queryKey: ["tags"], queryFn: api.getTags, retry: false });
  const corrsQ = useQuery({ queryKey: ["correspondents"], queryFn: api.getCorrespondents, retry: false });
  const dtQ = useQuery({ queryKey: ["docTypes"], queryFn: api.getDocumentTypes, retry: false });
  const cfQ = useQuery({ queryKey: ["customFields"], queryFn: api.getCustomFields, retry: false });
  const spQ = useQuery({ queryKey: ["storagePaths"], queryFn: api.getStoragePaths, retry: false });

  const paperlessUrl = (statusQ.data?.paperless_public_url || statusQ.data?.paperless_url || "").replace(/\/$/, "");

  const tagNames = useMemo(() => new Set((tagsQ.data ?? []).map((t: PaperlessEntity) => t.name.toLowerCase())), [tagsQ.data]);
  const corrNames = useMemo(() => new Set((corrsQ.data ?? []).map((c: PaperlessEntity) => c.name.toLowerCase())), [corrsQ.data]);
  const dtNames = useMemo(() => new Set((dtQ.data ?? []).map((d: PaperlessEntity) => d.name.toLowerCase())), [dtQ.data]);
  const cfNames = useMemo(() => new Set((cfQ.data ?? []).map((c: PaperlessCustomField) => c.name.toLowerCase())), [cfQ.data]);

  const [edits, setEdits] = useState<Record<string, QueueItem>>({});
  const [mergeTagsMap, setMergeTagsMap] = useState<Record<string, boolean>>({});
  const [createMissingMap, setCreateMissingMap] = useState<Record<string, boolean>>({});
  const [existingTagsMap, setExistingTagsMap] = useState<Record<number, string[]>>({});
  const [showEmptyConfirm, setShowEmptyConfirm] = useState(false);
  const [reanalyzingIds, setReanalyzingIds] = useState<Set<string>>(new Set());
  const [removedExistingTags, setRemovedExistingTags] = useState<Record<string, Set<string>>>({});

  // Preview state
  const [openPreviews, setOpenPreviews] = useState<Set<number>>(new Set());
  const [previewUrls, setPreviewUrls] = useState<Record<number, string>>({});
  const [previewErrors, setPreviewErrors] = useState<Record<number, string>>({});
  const [previewLoading, setPreviewLoading] = useState<Set<number>>(new Set());

  // Revoke blob URLs on unmount to prevent memory leaks
  useEffect(() => {
    const urls = previewUrls;
    return () => { Object.values(urls).forEach(u => URL.revokeObjectURL(u)); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const items = (data?.items ?? []) as Array<Record<string, unknown>>;

  // Fetch existing tags for each document in the queue
  useEffect(() => {
    const docIds = [...new Set(items.map(r => Number(r.document_id)))];
    for (const docId of docIds) {
      if (docId && !existingTagsMap[docId]) {
        api.getDocumentTags(docId).then(tags => {
          setExistingTagsMap(prev => ({ ...prev, [docId]: tags }));
        }).catch(() => {});
      }
    }
  }, [items.length]); // eslint-disable-line react-hooks/exhaustive-deps

  /** Toggle the preview panel; fetches blob on first open. */
  const togglePreview = useCallback(async (docId: number) => {
    if (openPreviews.has(docId)) {
      setOpenPreviews(prev => { const next = new Set(prev); next.delete(docId); return next; });
      return;
    }
    setOpenPreviews(prev => new Set(prev).add(docId));
    if (previewUrls[docId] || previewLoading.has(docId)) return; // already loaded or loading
    setPreviewLoading(prev => new Set(prev).add(docId));
    try {
      const blob = await api.getDocumentPreview(docId);
      const url = URL.createObjectURL(blob);
      setPreviewUrls(prev => ({ ...prev, [docId]: url }));
    } catch (err: unknown) {
      setPreviewErrors(prev => ({ ...prev, [docId]: (err as Error).message }));
    } finally {
      setPreviewLoading(prev => { const next = new Set(prev); next.delete(docId); return next; });
    }
  }, [openPreviews, previewUrls, previewLoading]);

  const approve = useMutation({
    mutationFn: ({ id, item, docId }: { id: string; item: QueueItem; docId: number }) => {
      let mergeTags = mergeTagsMap[id] ?? true;
      const createMissing = createMissingMap[id] ?? false;
      const removed = removedExistingTags[id];
      let finalTags = item.tags;

      if (removed && removed.size > 0) {
        const existing = existingTagsMap[docId] ?? [];
        const kept = existing.filter(t => !removed.has(t));
        const merged = [...new Set([...kept, ...item.tags])];
        finalTags = merged;
        mergeTags = false;
      }

      return api.approveItem(id, {
        edits: { title: item.title, tags: finalTags, correspondent: item.correspondent, document_type: item.document_type, storage_path: item.storage_path, custom_fields: item.custom_fields },
        merge_tags: mergeTags, create_missing: createMissing,
      });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["queue"] }),
  });

  const reject = useMutation({
    mutationFn: (id: string) => api.rejectItem(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["queue"] }),
  });

  const emptyQueue = useMutation({
    mutationFn: () => api.emptyQueue(),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["queue"] }); setShowEmptyConfirm(false); },
  });

  const reanalyzeAll = useMutation({
    mutationFn: () => api.reanalyzeAll(),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["queue"] }); },
  });

  const handleReanalyze = async (id: string) => {
    setReanalyzingIds(prev => new Set(prev).add(id));
    try {
      await api.reanalyzeItem(id);
      qc.invalidateQueries({ queryKey: ["queue"] });
    } catch { /* ignore */ }
    setReanalyzingIds(prev => { const n = new Set(prev); n.delete(id); return n; });
  };

  const getItem = (raw: Record<string, unknown>): QueueItem => {
    const id = String(raw.id);
    if (edits[id]) return edits[id];
    return {
      id, document_id: Number(raw.document_id),
      title: (raw.title as string) ?? null, tags: (raw.tags as string[]) ?? [],
      correspondent: (raw.correspondent as string) ?? null,
      document_type: (raw.document_type as string) ?? null,
      storage_path: (raw.storage_path as string) ?? null,
      custom_fields: (raw.custom_fields as Record<string, unknown>) ?? {},
    };
  };

  const updateField = (id: string, raw: Record<string, unknown>, field: string, value: unknown) => {
    const current = edits[id] ?? getItem(raw);
    setEdits(prev => ({ ...prev, [id]: { ...current, [field]: value } }));
  };

  if (isLoading) return <p style={{ color: "var(--text-on-body)" }}>{t("audit.loading")}</p>;

  const existingChip: React.CSSProperties = { background: "var(--chip-bg)", color: "var(--chip-text)", border: "1px solid var(--chip-border)", borderRadius: "3px", padding: "2px 8px", fontSize: "0.8rem", display: "inline-flex", alignItems: "center", gap: "4px" };
  const newChip: React.CSSProperties = { ...existingChip, background: "var(--error-band-bg)", color: "var(--error-on-card)", border: "1px solid var(--error-band-border)", fontWeight: 700 };
  const docTagChip: React.CSSProperties = { ...existingChip, background: "var(--chip-bg-subtle)", color: "var(--chip-subtle-text)", border: "1px solid var(--chip-border)", cursor: "pointer" };
  const newInputStyle = { fontSize: "0.85rem", color: "var(--error-on-card, #c62828)", fontWeight: 700 };
  const labelColor: React.CSSProperties = { fontWeight: 600, color: "var(--text-on-card-secondary)", fontSize: "0.85rem" };

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
        <h2 style={{ margin: 0 }}>{t("queue.title")}</h2>
        {items.length > 0 && (
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button className="btn btn-primary" onClick={() => reanalyzeAll.mutate()}
              disabled={reanalyzeAll.isPending}>
              {reanalyzeAll.isPending
                ? t("queue.reanalyzingAll")
                : t("queue.reanalyzeAll", { count: String(items.length) })}
            </button>
            <button className="btn btn-danger" onClick={() => setShowEmptyConfirm(true)}>
              {t("queue.emptyQueue")}
            </button>
          </div>
        )}
      </div>

      {showEmptyConfirm && (
        <div className="card" style={{ background: "rgba(234,88,12,0.08)", border: "1px solid rgba(234,88,12,0.25)", marginBottom: "1rem" }}>
          <p style={{ fontWeight: 600, margin: "0 0 0.5rem", color: "var(--text-on-card)" }}>{t("queue.emptyConfirm")}</p>
          <p style={{ fontSize: "0.85rem", margin: "0 0 0.75rem", color: "var(--text-on-card-secondary)" }}>
            {t("queue.emptyConfirmDetail", { count: String(items.length) })}
          </p>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button className="btn btn-danger" onClick={() => emptyQueue.mutate()} disabled={emptyQueue.isPending}>
              {emptyQueue.isPending ? t("queue.emptyingQueue") : t("queue.emptyConfirmYes")}
            </button>
            <button className="btn" onClick={() => setShowEmptyConfirm(false)}>{t("processing.cancel")}</button>
          </div>
        </div>
      )}

      {items.length === 0 && !showEmptyConfirm && (
        <p style={{ color: "var(--text-on-body-secondary)" }}>{t("queue.empty")}</p>
      )}

      {items.map((raw, idx) => {
        const item = getItem(raw);
        const id = item.id;
        const isNewTag = (tg: string) => !tagNames.has(tg.toLowerCase());
        const isNewCorr = item.correspondent ? !corrNames.has(item.correspondent.toLowerCase()) : false;
        const isNewDt = item.document_type ? !dtNames.has(item.document_type.toLowerCase()) : false;
        const cfEntries = Object.entries(item.custom_fields ?? {});
        const isNewCf = (name: string) => !cfNames.has(name.toLowerCase());
        const hasAnyNew = item.tags.some(isNewTag) || isNewCorr || isNewDt || cfEntries.some(([k]) => isNewCf(k));
        const mergeTags = mergeTagsMap[id] ?? true;
        const createMissing = createMissingMap[id] ?? false;
        const docExistingTags = existingTagsMap[item.document_id] ?? [];
        const isReanalyzing = reanalyzingIds.has(id);
        const previewOpen = openPreviews.has(item.document_id);
        const previewUrl = previewUrls[item.document_id];
        const previewErr = previewErrors[item.document_id];
        const previewIsLoading = previewLoading.has(item.document_id);

        return (
          <div key={id} className={`card${idx % 2 === 1 ? " card-alt" : ""}`} style={{ marginBottom: "0.5rem" }}>

            {/* ── Card header ── */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: previewOpen ? "0.5rem" : "0.75rem" }}>
              <div>
                <p style={{ margin: 0, fontWeight: 600, color: "var(--text-on-card)" }}>
                  {item.title || `${t("queue.document")} #${item.document_id}`}
                </p>
                {item.title && (
                  <p style={{ margin: "0.1rem 0 0", fontSize: "0.78rem", color: "var(--text-on-card-muted)" }}>
                    #{item.document_id}
                    {paperlessUrl && (
                      <a href={`${paperlessUrl}/documents/${item.document_id}/details`}
                        target="_blank" rel="noreferrer"
                        style={{ marginLeft: "0.5rem", color: "var(--petrol-700)", fontWeight: 500, textDecoration: "underline" }}>
                        {t("queue.openInPaperless")}
                      </a>
                    )}
                  </p>
                )}
              </div>
              <div style={{ display: "flex", gap: "0.4rem", flexShrink: 0, marginLeft: "1rem" }}>
                <button
                  className="btn"
                  onClick={() => togglePreview(item.document_id)}
                  style={{ fontSize: "0.78rem", padding: "0.25rem 0.6rem" }}
                >
                  {previewOpen ? `✕ ${t("queue.hidePreview")}` : `📄 ${t("queue.preview")}`}
                </button>
                <button className="btn" onClick={() => handleReanalyze(id)} disabled={isReanalyzing}
                  style={{ fontSize: "0.78rem", padding: "0.25rem 0.6rem" }}>
                  {isReanalyzing ? t("queue.reanalyzing") : t("queue.reanalyze")}
                </button>
              </div>
            </div>

            {/* ── Preview panel ── */}
            {previewOpen && (
              <div style={{ marginBottom: "0.75rem", borderRadius: "var(--radius-sm)", overflow: "hidden", border: "1px solid var(--gray-200)" }}>
                {previewIsLoading ? (
                  <div style={{ padding: "2.5rem", textAlign: "center", color: "var(--text-on-card-muted)", fontSize: "0.85rem" }}>
                    {t("queue.previewLoading")}
                  </div>
                ) : previewErr ? (
                  <div style={{ padding: "1rem", display: "flex", gap: "0.75rem", alignItems: "center", flexWrap: "wrap" }}>
                    <span style={{ color: "var(--error-on-card, var(--error))", fontSize: "0.85rem" }}>
                      {t("queue.previewError")} {previewErr}
                    </span>
                    {paperlessUrl && (
                      <a href={`${paperlessUrl}/documents/${item.document_id}/details`}
                        target="_blank" rel="noreferrer"
                        style={{ color: "var(--petrol-600)", fontSize: "0.85rem", textDecoration: "none" }}>
                        {t("queue.openInPaperless")}
                      </a>
                    )}
                  </div>
                ) : previewUrl ? (
                  <iframe
                    src={previewUrl}
                    title={`Preview #${item.document_id}`}
                    style={{ width: "100%", height: "640px", border: "none", display: "block" }}
                  />
                ) : null}
              </div>
            )}

            {/* ── Existing document tags ── */}
            {docExistingTags.length > 0 && (
              <div style={{ marginBottom: "0.5rem" }}>
                <label style={{ ...labelColor, display: "block", marginBottom: "0.2rem" }}>
                  {t("queue.currentTags")} <span style={{ color: "var(--text-on-card-muted)", fontWeight: 400 }}>{t("queue.currentTagsHint")}</span>
                </label>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "0.25rem" }}>
                  {docExistingTags.map(tag => {
                    const removed = removedExistingTags[id]?.has(tag) ?? false;
                    return (
                      <span key={tag}
                        onClick={() => {
                          setRemovedExistingTags(prev => {
                            const current = new Set(prev[id] ?? []);
                            if (current.has(tag)) current.delete(tag); else current.add(tag);
                            return { ...prev, [id]: current };
                          });
                        }}
                        style={{
                          ...docTagChip,
                          textDecoration: removed ? "line-through" : "none",
                          opacity: removed ? 0.5 : 1,
                          background: removed ? "var(--error-band-bg)" : "var(--chip-bg-subtle)",
                          color: removed ? "var(--error-on-card)" : "var(--chip-subtle-text)",
                          transition: "all 0.15s ease",
                        }}>
                        {tag}
                      </span>
                    );
                  })}
                </div>
              </div>
            )}

            {/* ── Edit form ── */}
            <div style={{ fontSize: "0.85rem" }}>
              <div className="form-group" style={{ marginBottom: "0.4rem" }}>
                <label style={labelColor}>Title</label>
                <input value={item.title ?? ""} style={{ fontSize: "0.85rem" }}
                  onChange={e => updateField(id, raw, "title", e.target.value || null)} />
              </div>
              <div className="form-group" style={{ marginBottom: "0.4rem" }}>
                <label style={labelColor}>{t("queue.suggestedTags")}</label>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "0.25rem", marginBottom: "0.25rem" }}>
                  {item.tags.map((tag, i) => (
                    <span key={i} style={isNewTag(tag) ? newChip : existingChip}>
                      {tag}{isNewTag(tag) && ` (${t("analysis.newValue")})`}
                      <button type="button" onClick={() => updateField(id, raw, "tags", item.tags.filter((_: string, j: number) => j !== i))}
                        style={{ background: "none", border: "none", cursor: "pointer", padding: 0, fontSize: "0.9rem", color: isNewTag(tag) ? "var(--error-on-card)" : "var(--text-on-card-muted)", lineHeight: 1 }}>×</button>
                    </span>
                  ))}
                </div>
                <TagInput allTags={(tagsQ.data ?? []).map((t: PaperlessEntity) => t.name)} placeholder={t("analysis.addTag")}
                  onAdd={tag => { if (!item.tags.includes(tag)) updateField(id, raw, "tags", [...item.tags, tag]); }} />
              </div>
              <div className="form-group" style={{ marginBottom: "0.4rem" }}>
                <label style={labelColor}>{t("analysis.correspondent_field")}</label>
                <AutocompleteInput value={item.correspondent ?? ""} suggestions={(corrsQ.data ?? []).map((c: PaperlessEntity) => c.name)}
                  onChange={v => updateField(id, raw, "correspondent", v || null)} style={isNewCorr ? newInputStyle : undefined} />
                {isNewCorr && <small className="error">{t("analysis.newHint")}</small>}
              </div>
              <div className="form-group" style={{ marginBottom: "0.4rem" }}>
                <label style={labelColor}>{t("analysis.docType_field")}</label>
                <AutocompleteInput value={item.document_type ?? ""} suggestions={(dtQ.data ?? []).map((d: PaperlessEntity) => d.name)}
                  onChange={v => updateField(id, raw, "document_type", v || null)} style={isNewDt ? newInputStyle : undefined} />
                {isNewDt && <small className="error">{t("analysis.newHint")}</small>}
              </div>
              <div className="form-group" style={{ marginBottom: "0.4rem" }}>
                <label style={labelColor}>{t("analysis.storagePath_field")}</label>
                <AutocompleteInput value={item.storage_path ?? ""} suggestions={(spQ.data ?? []).map((s: PaperlessEntity) => s.name)}
                  onChange={v => updateField(id, raw, "storage_path", v || null)} />
              </div>
              {cfEntries.length > 0 && <label style={{ ...labelColor, display: "block", marginTop: "0.25rem" }}>{t("analysis.customFields")}</label>}
              {cfEntries.map(([key, val]) => (
                <CfNameEditor key={key} name={key} value={val} isNew={isNewCf(key)}
                  suggestions={(cfQ.data ?? []).map((c: PaperlessCustomField) => c.name)}
                  onRename={newName => { if (!newName || newName === key) return; const cf = { ...item.custom_fields }; const v = cf[key]; delete cf[key]; cf[newName] = v; updateField(id, raw, "custom_fields", cf); }}
                  onChangeValue={v => updateField(id, raw, "custom_fields", { ...item.custom_fields, [key]: v || null })}
                  onRemove={() => { const cf = { ...item.custom_fields }; delete cf[key]; updateField(id, raw, "custom_fields", cf); }} />
              ))}
            </div>

            {/* ── Approve / Reject ── */}
            <div style={{ marginTop: "0.75rem" }}>
              <div style={{ display: "flex", gap: "1rem", marginBottom: "0.5rem", fontSize: "0.85rem" }}>
                <label style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: "0.25rem", color: "var(--text-on-card-secondary)" }}>
                  <input type="checkbox" checked={mergeTags} onChange={e => setMergeTagsMap(prev => ({ ...prev, [id]: e.target.checked }))} />
                  {t("queue.keepExistingTags")}
                </label>
                {hasAnyNew && (
                  <label style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: "0.25rem", color: "var(--text-on-card-secondary)" }}>
                    <input type="checkbox" checked={createMissing} onChange={e => setCreateMissingMap(prev => ({ ...prev, [id]: e.target.checked }))} />
                    {t("queue.createMissing")}
                  </label>
                )}
              </div>
              <div style={{ display: "flex", gap: "0.5rem" }}>
                <button className="btn btn-primary"
                  onClick={() => approve.mutate({ id, item, docId: item.document_id })}
                  disabled={approve.isPending && approve.variables?.id === id}>
                  {approve.isPending && approve.variables?.id === id ? t("queue.approving") : t("queue.approve")}
                </button>
                <button className="btn"
                  onClick={() => reject.mutate(id)}
                  disabled={reject.isPending && reject.variables === id}>
                  {t("queue.reject")}
                </button>
              </div>
              {approve.isError && approve.variables?.id === id && (
                <p className="error" style={{ marginTop: "0.5rem" }}>
                  {t("queue.approvalFailed")} {(approve.error as Error).message}
                </p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
