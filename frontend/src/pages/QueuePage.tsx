import { useState, useMemo } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type PaperlessEntity, type PaperlessCustomField } from "../api";
import TagInput from "../TagInput";
import AutocompleteInput from "../AutocompleteInput";

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
  const tagsQ = useQuery({ queryKey: ["tags"], queryFn: api.getTags, retry: false });
  const corrsQ = useQuery({ queryKey: ["correspondents"], queryFn: api.getCorrespondents, retry: false });
  const dtQ = useQuery({ queryKey: ["docTypes"], queryFn: api.getDocumentTypes, retry: false });
  const cfQ = useQuery({ queryKey: ["customFields"], queryFn: api.getCustomFields, retry: false });
  const spQ = useQuery({ queryKey: ["storagePaths"], queryFn: api.getStoragePaths, retry: false });

  const tagNames = useMemo(() => new Set((tagsQ.data ?? []).map((t: PaperlessEntity) => t.name.toLowerCase())), [tagsQ.data]);
  const corrNames = useMemo(() => new Set((corrsQ.data ?? []).map((c: PaperlessEntity) => c.name.toLowerCase())), [corrsQ.data]);
  const dtNames = useMemo(() => new Set((dtQ.data ?? []).map((d: PaperlessEntity) => d.name.toLowerCase())), [dtQ.data]);
  const cfNames = useMemo(() => new Set((cfQ.data ?? []).map((c: PaperlessCustomField) => c.name.toLowerCase())), [cfQ.data]);

  const [edits, setEdits] = useState<Record<string, QueueItem>>({});
  const [mergeTagsMap, setMergeTagsMap] = useState<Record<string, boolean>>({});
  const [createMissingMap, setCreateMissingMap] = useState<Record<string, boolean>>({});

  const approve = useMutation({
    mutationFn: ({ id, item }: { id: string; item: QueueItem }) => {
      const mergeTags = mergeTagsMap[id] ?? true;
      const createMissing = createMissingMap[id] ?? false;
      return api.approveItem(id, {
        edits: { title: item.title, tags: item.tags, correspondent: item.correspondent, document_type: item.document_type, storage_path: item.storage_path, custom_fields: item.custom_fields },
        merge_tags: mergeTags,
        create_missing: createMissing,
      });
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["queue"] }),
  });

  const reject = useMutation({
    mutationFn: (id: string) => api.rejectItem(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["queue"] }),
  });

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

  if (isLoading) return <p>Loading queue…</p>;
  const items = (data?.items ?? []) as Array<Record<string, unknown>>;

  const existingChip = { background: "#e0e0e0", borderRadius: "3px", padding: "2px 8px", fontSize: "0.8rem", display: "inline-flex" as const, alignItems: "center" as const, gap: "4px" };
  const newChip = { ...existingChip, background: "#ffcdd2", color: "#b71c1c", fontWeight: 700 as const };
  const newInputStyle = { fontSize: "0.85rem", color: "#c62828", fontWeight: 700 };

  return (
    <div>
      <h2>Approval Queue</h2>
      {items.length === 0 && <p>No pending suggestions.</p>}
      {items.map((raw, idx) => {
        const item = getItem(raw);
        const id = item.id;
        const isNewTag = (t: string) => !tagNames.has(t.toLowerCase());
        const isNewCorr = item.correspondent ? !corrNames.has(item.correspondent.toLowerCase()) : false;
        const isNewDt = item.document_type ? !dtNames.has(item.document_type.toLowerCase()) : false;
        const cfEntries = Object.entries(item.custom_fields ?? {});
        const isNewCf = (name: string) => !cfNames.has(name.toLowerCase());
        const hasAnyNew = item.tags.some(isNewTag) || isNewCorr || isNewDt || cfEntries.some(([k]) => isNewCf(k));
        const mergeTags = mergeTagsMap[id] ?? true;
        const createMissing = createMissingMap[id] ?? false;

        return (
          <div key={id} className={`card${idx % 2 === 1 ? " card-alt" : ""}`} style={{ marginBottom: "0.5rem" }}>
            <p style={{ margin: "0 0 0.5rem", fontWeight: 600 }}>Document {item.document_id}</p>
            <div style={{ fontSize: "0.85rem" }}>
              <div className="form-group" style={{ marginBottom: "0.4rem" }}>
                <label style={{ fontWeight: 600, color: "#555", fontSize: "0.85rem" }}>Title</label>
                <input value={item.title ?? ""} style={{ fontSize: "0.85rem" }}
                  onChange={e => updateField(id, raw, "title", e.target.value || null)} />
              </div>
              <div className="form-group" style={{ marginBottom: "0.4rem" }}>
                <label style={{ fontWeight: 600, color: "#555", fontSize: "0.85rem" }}>Tags</label>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "0.25rem", marginBottom: "0.25rem" }}>
                  {item.tags.map((tag, i) => (
                    <span key={i} style={isNewTag(tag) ? newChip : existingChip}>
                      {tag}{isNewTag(tag) && " (new)"}
                      <button type="button" onClick={() => updateField(id, raw, "tags", item.tags.filter((_: string, j: number) => j !== i))}
                        style={{ background: "none", border: "none", cursor: "pointer", padding: 0, fontSize: "0.9rem", color: isNewTag(tag) ? "#b71c1c" : "#888", lineHeight: 1 }}>×</button>
                    </span>
                  ))}
                </div>
                <TagInput
                  allTags={(tagsQ.data ?? []).map((t: PaperlessEntity) => t.name)}
                  placeholder="Add tag…"
                  onAdd={tag => { if (!item.tags.includes(tag)) updateField(id, raw, "tags", [...item.tags, tag]); }}
                />
              </div>
              <div className="form-group" style={{ marginBottom: "0.4rem" }}>
                <label style={{ fontWeight: 600, color: "#555", fontSize: "0.85rem" }}>Correspondent</label>
                <AutocompleteInput
                  value={item.correspondent ?? ""}
                  suggestions={(corrsQ.data ?? []).map((c: PaperlessEntity) => c.name)}
                  onChange={v => updateField(id, raw, "correspondent", v || null)}
                  style={isNewCorr ? newInputStyle : undefined}
                />
                {isNewCorr && <small style={{ color: "#c62828" }}>New — will be created if "Create missing" is checked</small>}
              </div>
              <div className="form-group" style={{ marginBottom: "0.4rem" }}>
                <label style={{ fontWeight: 600, color: "#555", fontSize: "0.85rem" }}>Document Type</label>
                <AutocompleteInput
                  value={item.document_type ?? ""}
                  suggestions={(dtQ.data ?? []).map((d: PaperlessEntity) => d.name)}
                  onChange={v => updateField(id, raw, "document_type", v || null)}
                  style={isNewDt ? newInputStyle : undefined}
                />
                {isNewDt && <small style={{ color: "#c62828" }}>New — will be created if "Create missing" is checked</small>}
              </div>
              <div className="form-group" style={{ marginBottom: "0.4rem" }}>
                <label style={{ fontWeight: 600, color: "#555", fontSize: "0.85rem" }}>Storage Path</label>
                <AutocompleteInput
                  value={item.storage_path ?? ""}
                  suggestions={(spQ.data ?? []).map((s: PaperlessEntity) => s.name)}
                  onChange={v => updateField(id, raw, "storage_path", v || null)}
                />
              </div>
              {cfEntries.length > 0 && <label style={{ fontWeight: 600, color: "#555", fontSize: "0.85rem", display: "block", marginTop: "0.25rem" }}>Custom Fields</label>}
              {cfEntries.map(([key, val]) => (
                <div key={key} style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginBottom: "0.25rem" }}>
                  <span style={isNewCf(key) ? { fontWeight: 700, color: "#c62828", minWidth: "120px", fontSize: "0.85rem" } : { minWidth: "120px", color: "#555", fontSize: "0.85rem" }}>
                    {key}{isNewCf(key) && " (new)"}:
                  </span>
                  <input value={String(val ?? "")} style={{ fontSize: "0.85rem", flex: 1 }}
                    onChange={e => updateField(id, raw, "custom_fields", { ...item.custom_fields, [key]: e.target.value || null })} />
                  <button type="button" onClick={() => { const cf = { ...item.custom_fields }; delete cf[key]; updateField(id, raw, "custom_fields", cf); }}
                    style={{ background: "none", border: "none", cursor: "pointer", color: "#888", fontSize: "1rem" }}>×</button>
                </div>
              ))}
            </div>
            <div style={{ marginTop: "0.5rem" }}>
              <div style={{ display: "flex", gap: "1rem", marginBottom: "0.5rem", fontSize: "0.85rem" }}>
                <label style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: "0.25rem" }}>
                  <input type="checkbox" checked={mergeTags} onChange={e => setMergeTagsMap(prev => ({ ...prev, [id]: e.target.checked }))} />
                  Keep existing tags
                </label>
                {hasAnyNew && (
                  <label style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: "0.25rem" }}>
                    <input type="checkbox" checked={createMissing} onChange={e => setCreateMissingMap(prev => ({ ...prev, [id]: e.target.checked }))} />
                    Create missing values
                  </label>
                )}
              </div>
              <div style={{ display: "flex", gap: "0.5rem" }}>
                <button className="btn btn-primary" onClick={() => approve.mutate({ id, item })}
                  disabled={approve.isPending && approve.variables?.id === id}>
                  {approve.isPending && approve.variables?.id === id ? "Approving…" : "Approve"}
                </button>
                <button className="btn" onClick={() => reject.mutate(id)} disabled={reject.isPending && reject.variables === id}>Reject</button>
              </div>
              {approve.isError && approve.variables?.id === id && (
                <p className="error" style={{ marginTop: "0.5rem" }}>Approval failed: {(approve.error as Error).message}</p>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
