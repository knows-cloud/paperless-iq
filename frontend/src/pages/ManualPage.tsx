import { useState, useCallback, useMemo } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { api, type PaperlessEntity, type PaperlessCustomField, type DocumentItem, type MetadataSuggestionResponse } from "../api";
import TagInput from "../TagInput";
import AutocompleteInput from "../AutocompleteInput";
import CfNameEditor from "../CfNameEditor";
import { t } from "../i18n";

export default function ManualPage() {
  const [titleQuery, setTitleQuery] = useState("");
  const [tagFilter, setTagFilter] = useState("");
  const [corrFilter, setCorrFilter] = useState("");
  const [dtFilter, setDtFilter] = useState("");
  const [customFieldFilters, setCustomFieldFilters] = useState<Record<string, string>>({});
  const [page, setPage] = useState(1);
  const [shouldSearch, setShouldSearch] = useState(false);

  const [analysisResults, setAnalysisResults] = useState<Record<number, MetadataSuggestionResponse>>({});
  const [analysisErrors, setAnalysisErrors] = useState<Record<number, string>>({});
  const [analyzingDocs, setAnalyzingDocs] = useState<Set<number>>(new Set());
  const [dismissed, setDismissed] = useState<Set<number>>(new Set());
  const [approvedDocs, setApprovedDocs] = useState<Set<number>>(new Set());
  const [selectedDocs, setSelectedDocs] = useState<Set<number>>(new Set());
  const [batchRunning, setBatchRunning] = useState(false);
  const [hideAnalyzed, setHideAnalyzed] = useState(false);
  // Per-document options
  const [mergeTagsMap, setMergeTagsMap] = useState<Record<number, boolean>>({});
  const [createMissingMap, setCreateMissingMap] = useState<Record<number, boolean>>({});

  const tags = useQuery({ queryKey: ["tags"], queryFn: api.getTags, retry: false });
  const correspondents = useQuery({ queryKey: ["correspondents"], queryFn: api.getCorrespondents, retry: false });
  const docTypes = useQuery({ queryKey: ["docTypes"], queryFn: api.getDocumentTypes, retry: false });
  const customFields = useQuery({ queryKey: ["customFields"], queryFn: api.getCustomFields, retry: false });
  const storagePaths = useQuery({ queryKey: ["storagePaths"], queryFn: api.getStoragePaths, retry: false });

  // Build lookup sets for existence checking (lowercased for case-insensitive match)
  const tagNames = useMemo(() => new Set((tags.data ?? []).map((t: PaperlessEntity) => t.name.toLowerCase())), [tags.data]);
  const corrNames = useMemo(() => new Set((correspondents.data ?? []).map((c: PaperlessEntity) => c.name.toLowerCase())), [correspondents.data]);
  const dtNames = useMemo(() => new Set((docTypes.data ?? []).map((d: PaperlessEntity) => d.name.toLowerCase())), [docTypes.data]);
  const cfNames = useMemo(() => new Set((customFields.data ?? []).map((c: PaperlessCustomField) => c.name.toLowerCase())), [customFields.data]);

  const buildParams = () => {
    const p: Record<string, string> = { page: String(page), page_size: "20" };
    if (titleQuery.trim()) p.query = titleQuery.trim();
    if (tagFilter) p.tag_id = tagFilter;
    if (corrFilter) p.correspondent_id = corrFilter;
    if (dtFilter) p.document_type_id = dtFilter;
    for (const [key, value] of Object.entries(customFieldFilters)) {
      if (value) p[`custom_fields__${key}`] = value;
    }
    return p;
  };

  const docs = useQuery({
    queryKey: ["documents", titleQuery, tagFilter, corrFilter, dtFilter, customFieldFilters, page],
    queryFn: () => api.getDocuments(buildParams()),
    enabled: shouldSearch,
    retry: false,
  });

  const analyzeOne = useCallback(async (docId: number) => {
    setAnalyzingDocs(prev => new Set(prev).add(docId));
    setAnalysisErrors(prev => { const next = { ...prev }; delete next[docId]; return next; });
    try {
      const data = await api.analyze(docId);
      setAnalysisResults(prev => ({ ...prev, [docId]: data }));
      setMergeTagsMap(prev => ({ ...prev, [docId]: true }));
    } catch (err: unknown) {
      setAnalysisErrors(prev => ({ ...prev, [docId]: (err as Error).message }));
    } finally {
      setAnalyzingDocs(prev => { const next = new Set(prev); next.delete(docId); return next; });
    }
  }, []);

  const analyzeMut = useMutation({ mutationFn: (id: number) => analyzeOne(id) });

  const handleBatchAnalyze = useCallback(async () => {
    if (selectedDocs.size === 0) return;
    setBatchRunning(true);
    const ids = Array.from(selectedDocs);
    // Mark all as analyzing
    setAnalyzingDocs(prev => { const next = new Set(prev); ids.forEach(id => next.add(id)); return next; });
    // Submit all in parallel — they queue up in the backend OllamaQueue
    const promises = ids.map(async (id) => {
      setAnalysisErrors(prev => { const next = { ...prev }; delete next[id]; return next; });
      try {
        const data = await api.analyze(id);
        setAnalysisResults(prev => ({ ...prev, [id]: data }));
        setMergeTagsMap(prev => ({ ...prev, [id]: true }));
      } catch (err: unknown) {
        setAnalysisErrors(prev => ({ ...prev, [id]: (err as Error).message }));
      } finally {
        setAnalyzingDocs(prev => { const next = new Set(prev); next.delete(id); return next; });
      }
    });
    await Promise.all(promises);
    setBatchRunning(false);
    setSelectedDocs(new Set());
  }, [selectedDocs, analyzeOne]);

  const approveMut = useMutation({
    mutationFn: async ({ suggestion, mergeTags, createMissing }: { suggestion: MetadataSuggestionResponse; mergeTags: boolean; createMissing: boolean }) => {
      const enqueued = await api.enqueueSuggestion(suggestion);
      await api.approveItem(enqueued.id, { merge_tags: mergeTags, create_missing: createMissing });
      return enqueued;
    },
    onSuccess: (_data, { suggestion }) => {
      setApprovedDocs(prev => new Set(prev).add(suggestion.document_id));
    },
  });

  const handleSearch = () => { setPage(1); setShouldSearch(true); setSelectedDocs(new Set()); };
  const handleKeyDown = (e: React.KeyboardEvent) => { if (e.key === "Enter") handleSearch(); };
  const updateCustomFieldFilter = (fieldId: string, value: string) => {
    setCustomFieldFilters(prev => ({ ...prev, [fieldId]: value }));
  };
  const handleDismiss = (docId: number) => {
    setDismissed(prev => new Set(prev).add(docId));
    setAnalysisResults(prev => { const next = { ...prev }; delete next[docId]; return next; });
  };
  const toggleDocSelection = (docId: number) => {
    setSelectedDocs(prev => { const next = new Set(prev); if (next.has(docId)) next.delete(docId); else next.add(docId); return next; });
  };
  const toggleSelectAll = () => {
    if (!docs.data) return;
    const allIds = docs.data.items.map((d: DocumentItem) => d.id);
    setSelectedDocs(allIds.every((id: number) => selectedDocs.has(id)) ? new Set() : new Set(allIds));
  };
  const updateSuggestionField = (docId: number, field: string, value: unknown) => {
    setAnalysisResults(prev => { const c = prev[docId]; if (!c) return prev; return { ...prev, [docId]: { ...c, [field]: value } }; });
  };

  const paperlessUnavailable = tags.isError;
  const tagMap = new Map((tags.data ?? []).map((t: PaperlessEntity) => [t.id, t.name]));
  const corrMap = new Map((correspondents.data ?? []).map((c: PaperlessEntity) => [c.id, c.name]));
  const dtMap = new Map((docTypes.data ?? []).map((d: PaperlessEntity) => [d.id, d.name]));

  // Style for unknown (new) values
  const newValueStyle = { color: "#c62828", fontWeight: 700 } as const;
  const existingChipStyle = { background: "#e0e0e0", borderRadius: "3px", padding: "2px 8px", fontSize: "0.8rem", display: "inline-flex" as const, alignItems: "center" as const, gap: "4px" };
  const newChipStyle = { ...existingChipStyle, background: "#ffcdd2", color: "#b71c1c", fontWeight: 700 };

  const renderSuggestion = (suggestion: MetadataSuggestionResponse, docId: number) => {
    const customFieldEntries = Object.entries(suggestion.custom_fields ?? {});
    const isApproved = approvedDocs.has(docId);
    const isApproving = approveMut.isPending && approveMut.variables?.suggestion.document_id === docId;
    const hasFields = suggestion.title || suggestion.tags.length > 0 || suggestion.correspondent ||
      suggestion.document_type || suggestion.storage_path || customFieldEntries.length > 0;
    const mergeTags = mergeTagsMap[docId] ?? true;
    const createMissing = createMissingMap[docId] ?? false;

    // Check which values are new (don't exist in Paperless NGX)
    const isNewTag = (t: string) => !tagNames.has(t.toLowerCase());
    const isNewCorr = suggestion.correspondent ? !corrNames.has(suggestion.correspondent.toLowerCase()) : false;
    const isNewDt = suggestion.document_type ? !dtNames.has(suggestion.document_type.toLowerCase()) : false;
    const hasAnyNew = suggestion.tags.some(isNewTag) || isNewCorr || isNewDt || customFieldEntries.some(([k]) => !cfNames.has(k.toLowerCase()));

    return (
      <div style={{ marginTop: "0.5rem", padding: "0.75rem", background: "#f8f9fa", borderRadius: "6px", border: "1px solid #e0e0e0" }}>
        <strong style={{ fontSize: "0.9rem" }}>Suggested Metadata</strong>
        {!hasFields && (
          <p style={{ color: "#888", fontStyle: "italic", fontSize: "0.85rem", marginTop: "0.5rem" }}>No metadata could be determined for this document.</p>
        )}
        <div style={{ marginTop: "0.5rem", fontSize: "0.85rem" }}>
          <div className="form-group" style={{ marginBottom: "0.4rem" }}>
            <label style={{ fontWeight: 600, color: "#555", fontSize: "0.85rem" }}>Title</label>
            <input value={suggestion.title ?? ""} style={{ fontSize: "0.85rem" }}
              onChange={e => updateSuggestionField(docId, "title", e.target.value || null)} />
          </div>
          <div className="form-group" style={{ marginBottom: "0.4rem" }}>
            <label style={{ fontWeight: 600, color: "#555", fontSize: "0.85rem" }}>Tags</label>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.25rem", marginBottom: "0.25rem" }}>
              {suggestion.tags.map((tag, i) => (
                <span key={i} style={isNewTag(tag) ? newChipStyle : existingChipStyle}>
                  {tag}{isNewTag(tag) && " (new)"}
                  <button type="button" onClick={() => updateSuggestionField(docId, "tags", suggestion.tags.filter((_: string, j: number) => j !== i))}
                    style={{ background: "none", border: "none", cursor: "pointer", padding: 0, fontSize: "0.9rem", color: isNewTag(tag) ? "#b71c1c" : "#888", lineHeight: 1 }}>×</button>
                </span>
              ))}
            </div>
            <TagInput
              allTags={(tags.data ?? []).map((t: PaperlessEntity) => t.name)}
              placeholder="Add tag…"
              onAdd={tag => { if (!suggestion.tags.includes(tag)) updateSuggestionField(docId, "tags", [...suggestion.tags, tag]); }}
            />
          </div>
          <div className="form-group" style={{ marginBottom: "0.4rem" }}>
            <label style={{ fontWeight: 600, color: "#555", fontSize: "0.85rem" }}>Correspondent</label>
            <AutocompleteInput
              value={suggestion.correspondent ?? ""}
              suggestions={(correspondents.data ?? []).map((c: PaperlessEntity) => c.name)}
              onChange={v => updateSuggestionField(docId, "correspondent", v || null)}
              style={isNewCorr ? newValueStyle : undefined}
            />
            {isNewCorr && <small style={{ color: "#c62828" }}>New — will be created if "Create missing values" is checked</small>}
          </div>
          <div className="form-group" style={{ marginBottom: "0.4rem" }}>
            <label style={{ fontWeight: 600, color: "#555", fontSize: "0.85rem" }}>Document Type</label>
            <AutocompleteInput
              value={suggestion.document_type ?? ""}
              suggestions={(docTypes.data ?? []).map((d: PaperlessEntity) => d.name)}
              onChange={v => updateSuggestionField(docId, "document_type", v || null)}
              style={isNewDt ? newValueStyle : undefined}
            />
            {isNewDt && <small style={{ color: "#c62828" }}>New — will be created if "Create missing values" is checked</small>}
          </div>
          <div className="form-group" style={{ marginBottom: "0.4rem" }}>
            <label style={{ fontWeight: 600, color: "#555", fontSize: "0.85rem" }}>Storage Path</label>
            <AutocompleteInput
              value={suggestion.storage_path ?? ""}
              suggestions={(storagePaths.data ?? []).map((s: PaperlessEntity) => s.name)}
              onChange={v => updateSuggestionField(docId, "storage_path", v || null)}
            />
          </div>
          {customFieldEntries.length > 0 && <label style={{ fontWeight: 600, color: "#555", fontSize: "0.85rem", display: "block", marginTop: "0.25rem" }}>Custom Fields</label>}
          {customFieldEntries.map(([key, val]) => {
            const isNewCf = !cfNames.has(key.toLowerCase());
            return (
              <CfNameEditor
                key={key}
                name={key}
                value={val}
                isNew={isNewCf}
                suggestions={(customFields.data ?? []).map((c: PaperlessCustomField) => c.name)}
                onRename={(newName) => {
                  if (!newName || newName === key) return;
                  const cf = { ...suggestion.custom_fields };
                  const v = cf[key]; delete cf[key]; cf[newName] = v;
                  updateSuggestionField(docId, "custom_fields", cf);
                }}
                onChangeValue={(v) => updateSuggestionField(docId, "custom_fields", { ...suggestion.custom_fields, [key]: v || null })}
                onRemove={() => { const cf = { ...suggestion.custom_fields }; delete cf[key]; updateSuggestionField(docId, "custom_fields", cf); }}
              />
            );
          })}
        </div>
        {isApproved ? (
          <p className="success" style={{ marginTop: "0.5rem" }}>Approved and applied.</p>
        ) : (
          <div style={{ marginTop: "0.5rem" }}>
            <div style={{ display: "flex", gap: "1rem", marginBottom: "0.5rem", fontSize: "0.85rem" }}>
              <label style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: "0.25rem" }}>
                <input type="checkbox" checked={mergeTags}
                  onChange={e => setMergeTagsMap(prev => ({ ...prev, [docId]: e.target.checked }))} />
                Keep existing tags
              </label>
              {hasAnyNew && (
                <label style={{ cursor: "pointer", display: "flex", alignItems: "center", gap: "0.25rem" }}>
                  <input type="checkbox" checked={createMissing}
                    onChange={e => setCreateMissingMap(prev => ({ ...prev, [docId]: e.target.checked }))} />
                  Create missing values
                </label>
              )}
            </div>
            <div style={{ display: "flex", gap: "0.5rem" }}>
              <button className="btn btn-primary" disabled={isApproving}
                onClick={() => approveMut.mutate({ suggestion, mergeTags, createMissing })}>
                {isApproving ? "Approving…" : "Approve"}
              </button>
              <button className="btn" onClick={() => handleDismiss(docId)} disabled={isApproving}>Reject</button>
            </div>
          </div>
        )}
        {approveMut.isError && approveMut.variables?.suggestion.document_id === docId && (
          <p className="error" style={{ marginTop: "0.5rem" }}>Approval failed: {(approveMut.error as Error).message}</p>
        )}
      </div>
    );
  };

  return (
    <div>
      <h2>{t("analysis.title")}</h2>
      {paperlessUnavailable && (
        <div className="card"><p className="error">{t("analysis.paperlessUnavailable")}</p></div>
      )}
      <div className="card">
        <div className="form-group">
          <label htmlFor="title-search">Search documents</label>
          <input id="title-search" value={titleQuery} onChange={e => setTitleQuery(e.target.value)}
            onKeyDown={handleKeyDown} placeholder="Search by title or content…" />
        </div>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <div className="form-group" style={{ flex: 1, minWidth: "150px" }}>
            <label htmlFor="tag-filter">Tag</label>
            <select id="tag-filter" value={tagFilter} onChange={e => setTagFilter(e.target.value)}>
              <option value="">All tags</option>
              {(tags.data ?? []).map((t: PaperlessEntity) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </div>
          <div className="form-group" style={{ flex: 1, minWidth: "150px" }}>
            <label htmlFor="corr-filter">Correspondent</label>
            <select id="corr-filter" value={corrFilter} onChange={e => setCorrFilter(e.target.value)}>
              <option value="">All correspondents</option>
              {(correspondents.data ?? []).map((c: PaperlessEntity) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </div>
          <div className="form-group" style={{ flex: 1, minWidth: "150px" }}>
            <label htmlFor="dt-filter">Document type</label>
            <select id="dt-filter" value={dtFilter} onChange={e => setDtFilter(e.target.value)}>
              <option value="">All types</option>
              {(docTypes.data ?? []).map((d: PaperlessEntity) => <option key={d.id} value={d.id}>{d.name}</option>)}
            </select>
          </div>
        </div>
        {(customFields.data ?? []).length > 0 && (
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginTop: "0.5rem" }}>
            {(customFields.data ?? []).map((cf: PaperlessCustomField) => (
              <div className="form-group" style={{ flex: 1, minWidth: "150px" }} key={cf.id}>
                <label htmlFor={`cf-${cf.id}`}>{cf.name}</label>
                {cf.data_type === "boolean" ? (
                  <select id={`cf-${cf.id}`} value={customFieldFilters[String(cf.id)] ?? ""}
                    onChange={e => updateCustomFieldFilter(String(cf.id), e.target.value)}>
                    <option value="">All</option><option value="true">Yes</option><option value="false">No</option>
                  </select>
                ) : cf.data_type === "date" ? (
                  <input id={`cf-${cf.id}`} type="date" value={customFieldFilters[String(cf.id)] ?? ""}
                    onChange={e => updateCustomFieldFilter(String(cf.id), e.target.value)} />
                ) : ["integer", "float", "monetary"].includes(cf.data_type) ? (
                  <input id={`cf-${cf.id}`} type="number" value={customFieldFilters[String(cf.id)] ?? ""}
                    onChange={e => updateCustomFieldFilter(String(cf.id), e.target.value)} placeholder={`Filter by ${cf.name}…`} />
                ) : (
                  <input id={`cf-${cf.id}`} type="text" value={customFieldFilters[String(cf.id)] ?? ""}
                    onChange={e => updateCustomFieldFilter(String(cf.id), e.target.value)} placeholder={`Filter by ${cf.name}…`} />
                )}
              </div>
            ))}
          </div>
        )}
        <button className="btn btn-primary" onClick={handleSearch} disabled={paperlessUnavailable}>Search</button>
      </div>
      {docs.isLoading && <p>Searching…</p>}
      {docs.isError && <p className="error">Search failed. Check Paperless NGX connection.</p>}
      {docs.isSuccess && (
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", margin: "0.75rem 0 0.5rem" }}>
            <p style={{ margin: 0 }}>{docs.data.total} document{docs.data.total !== 1 ? "s" : ""} found</p>
            {docs.data.items.length > 0 && (
              <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
                <label style={{ fontSize: "0.85rem", cursor: "pointer", display: "flex", alignItems: "center", gap: "0.25rem" }}>
                  <input type="checkbox" checked={hideAnalyzed} onChange={e => setHideAnalyzed(e.target.checked)} />
                  Hide analyzed
                </label>
                <label style={{ fontSize: "0.85rem", cursor: "pointer", display: "flex", alignItems: "center", gap: "0.25rem" }}>
                  <input type="checkbox" checked={docs.data.items.length > 0 && docs.data.items.every((d: DocumentItem) => selectedDocs.has(d.id))} onChange={toggleSelectAll} />
                  Select all
                </label>
                <button className="btn btn-primary" onClick={handleBatchAnalyze} disabled={selectedDocs.size === 0 || batchRunning}>
                  {batchRunning ? "Analyzing…" : `Analyze Selected (${selectedDocs.size})`}
                </button>
              </div>
            )}
          </div>
          {(() => { let visibleIdx = 0; return docs.data.items.map((doc: DocumentItem) => {
            const isAnalyzing = analyzingDocs.has(doc.id);
            const result = analysisResults[doc.id];
            const error = analysisErrors[doc.id];
            const isDismissed = dismissed.has(doc.id);
            const isSelected = selectedDocs.has(doc.id);
            const wasAnalyzed = !!result || approvedDocs.has(doc.id) || isDismissed;
            if (hideAnalyzed && wasAnalyzed) return null;
            const cardIdx = visibleIdx++;
            return (
              <div key={doc.id} className={`card${cardIdx % 2 === 1 ? " card-alt" : ""}`} style={{ marginBottom: "0.5rem" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                  <div style={{ display: "flex", gap: "0.5rem", alignItems: "flex-start" }}>
                    <input type="checkbox" checked={isSelected} onChange={() => toggleDocSelection(doc.id)} style={{ marginTop: "0.3rem" }} />
                    <div>
                      <strong>{doc.title || `Document #${doc.id}`}</strong>
                      <div style={{ fontSize: "0.85rem", color: "#666", marginTop: "0.25rem" }}>
                        {doc.correspondent ? <span>Correspondent: {corrMap.get(doc.correspondent) ?? doc.correspondent} · </span> : null}
                        {doc.document_type ? <span>Type: {dtMap.get(doc.document_type) ?? doc.document_type} · </span> : null}
                        {doc.tags.length > 0 && <span>Tags: {doc.tags.map(t => tagMap.get(t) ?? t).join(", ")}</span>}
                      </div>
                    </div>
                  </div>
                  <button className="btn btn-primary" style={{ whiteSpace: "nowrap", marginLeft: "1rem" }}
                    onClick={() => analyzeMut.mutate(doc.id)} disabled={isAnalyzing || batchRunning}>
                    {isAnalyzing ? "Analyzing…" : "Analyze"}
                  </button>
                </div>
                {isAnalyzing && <p style={{ marginTop: "0.5rem", color: "#666", fontStyle: "italic" }}>Analyzing document…</p>}
                {error && <p className="error" style={{ marginTop: "0.5rem" }}>Analysis failed: {error}</p>}
                {result && !isDismissed && renderSuggestion(result, doc.id)}
              </div>
            );
          }); })()}
          {docs.data.total > 20 && (
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem" }}>
              <button className="btn" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>Previous</button>
              <span style={{ lineHeight: "2rem" }}>Page {page} of {Math.ceil(docs.data.total / 20)}</span>
              <button className="btn" disabled={page * 20 >= docs.data.total} onClick={() => setPage(p => p + 1)}>Next</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
