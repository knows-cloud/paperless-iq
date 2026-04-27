import { useState, useCallback } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { api, type PaperlessEntity, type PaperlessCustomField, type DocumentItem, type MetadataSuggestionResponse } from "../api";

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

  const tags = useQuery({ queryKey: ["tags"], queryFn: api.getTags, retry: false });
  const correspondents = useQuery({ queryKey: ["correspondents"], queryFn: api.getCorrespondents, retry: false });
  const docTypes = useQuery({ queryKey: ["docTypes"], queryFn: api.getDocumentTypes, retry: false });
  const customFields = useQuery({ queryKey: ["customFields"], queryFn: api.getCustomFields, retry: false });

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
    } catch (err: unknown) {
      setAnalysisErrors(prev => ({ ...prev, [docId]: (err as Error).message }));
    } finally {
      setAnalyzingDocs(prev => { const next = new Set(prev); next.delete(docId); return next; });
    }
  }, []);

  const analyzeMut = useMutation({
    mutationFn: (id: number) => analyzeOne(id),
  });

  const handleBatchAnalyze = useCallback(async () => {
    if (selectedDocs.size === 0) return;
    setBatchRunning(true);
    const ids = Array.from(selectedDocs);
    for (const id of ids) {
      await analyzeOne(id);
    }
    setBatchRunning(false);
    setSelectedDocs(new Set());
  }, [selectedDocs, analyzeOne]);

  const approveMut = useMutation({
    mutationFn: async (suggestion: MetadataSuggestionResponse) => {
      const enqueued = await api.enqueueSuggestion(suggestion);
      await api.approveItem(enqueued.id);
      return enqueued;
    },
    onSuccess: (_data, suggestion) => {
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
    setSelectedDocs(prev => {
      const next = new Set(prev);
      if (next.has(docId)) next.delete(docId); else next.add(docId);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (!docs.data) return;
    const allIds = docs.data.items.map((d: DocumentItem) => d.id);
    const allSelected = allIds.every((id: number) => selectedDocs.has(id));
    if (allSelected) {
      setSelectedDocs(new Set());
    } else {
      setSelectedDocs(new Set(allIds));
    }
  };

  const paperlessUnavailable = tags.isError;
  const tagMap = new Map((tags.data ?? []).map((t: PaperlessEntity) => [t.id, t.name]));
  const corrMap = new Map((correspondents.data ?? []).map((c: PaperlessEntity) => [c.id, c.name]));
  const dtMap = new Map((docTypes.data ?? []).map((d: PaperlessEntity) => [d.id, d.name]));

  const renderSuggestion = (suggestion: MetadataSuggestionResponse, docId: number) => {
    const fields: Array<{ label: string; value: string }> = [];
    if (suggestion.title) fields.push({ label: "Title", value: suggestion.title });
    if (suggestion.tags.length > 0) fields.push({ label: "Tags", value: suggestion.tags.join(", ") });
    if (suggestion.correspondent) fields.push({ label: "Correspondent", value: suggestion.correspondent });
    if (suggestion.document_type) fields.push({ label: "Document Type", value: suggestion.document_type });
    if (suggestion.storage_path) fields.push({ label: "Storage Path", value: suggestion.storage_path });
    const customFieldEntries = Object.entries(suggestion.custom_fields ?? {});
    const isApproved = approvedDocs.has(docId);
    const isApproving = approveMut.isPending && approveMut.variables?.document_id === docId;

    return (
      <div style={{ marginTop: "0.5rem", padding: "0.75rem", background: "#f8f9fa", borderRadius: "6px", border: "1px solid #e0e0e0" }}>
        <strong style={{ fontSize: "0.9rem" }}>Suggested Metadata</strong>
        <div style={{ marginTop: "0.5rem", fontSize: "0.85rem" }}>
          {fields.map(f => (
            <div key={f.label} style={{ display: "flex", gap: "0.5rem", marginBottom: "0.25rem" }}>
              <span style={{ fontWeight: 600, minWidth: "120px", color: "#555" }}>{f.label}:</span>
              <span>{f.value}</span>
            </div>
          ))}
          {customFieldEntries.map(([key, val]) => (
            <div key={key} style={{ display: "flex", gap: "0.5rem", marginBottom: "0.25rem" }}>
              <span style={{ fontWeight: 600, minWidth: "120px", color: "#555" }}>{key}:</span>
              <span>{String(val)}</span>
            </div>
          ))}
        </div>
        {isApproved ? (
          <p className="success" style={{ marginTop: "0.5rem" }}>Approved and enqueued.</p>
        ) : (
          <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem" }}>
            <button className="btn btn-primary" onClick={() => approveMut.mutate(suggestion)} disabled={isApproving}>
              {isApproving ? "Approving…" : "Approve"}
            </button>
            <button className="btn" onClick={() => handleDismiss(docId)} disabled={isApproving}>Reject</button>
          </div>
        )}
        {approveMut.isError && approveMut.variables?.document_id === docId && (
          <p className="error" style={{ marginTop: "0.5rem" }}>Approval failed: {(approveMut.error as Error).message}</p>
        )}
      </div>
    );
  };

  return (
    <div>
      <h2>Document Search &amp; Analysis</h2>

      {paperlessUnavailable && (
        <div className="card">
          <p className="error">
            Cannot connect to Paperless NGX. Make sure PAPERLESS_URL and PAPERLESS_TOKEN are configured.
          </p>
        </div>
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
                    <option value="">All</option>
                    <option value="true">Yes</option>
                    <option value="false">No</option>
                  </select>
                ) : cf.data_type === "date" ? (
                  <input id={`cf-${cf.id}`} type="date" value={customFieldFilters[String(cf.id)] ?? ""}
                    onChange={e => updateCustomFieldFilter(String(cf.id), e.target.value)} />
                ) : ["integer", "float", "monetary"].includes(cf.data_type) ? (
                  <input id={`cf-${cf.id}`} type="number" value={customFieldFilters[String(cf.id)] ?? ""}
                    onChange={e => updateCustomFieldFilter(String(cf.id), e.target.value)}
                    placeholder={`Filter by ${cf.name}…`} />
                ) : (
                  <input id={`cf-${cf.id}`} type="text" value={customFieldFilters[String(cf.id)] ?? ""}
                    onChange={e => updateCustomFieldFilter(String(cf.id), e.target.value)}
                    placeholder={`Filter by ${cf.name}…`} />
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
              <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
                <label style={{ fontSize: "0.85rem", cursor: "pointer", display: "flex", alignItems: "center", gap: "0.25rem" }}>
                  <input type="checkbox"
                    checked={docs.data.items.length > 0 && docs.data.items.every((d: DocumentItem) => selectedDocs.has(d.id))}
                    onChange={toggleSelectAll} />
                  Select all
                </label>
                <button className="btn btn-primary"
                  onClick={handleBatchAnalyze}
                  disabled={selectedDocs.size === 0 || batchRunning}>
                  {batchRunning ? `Analyzing ${analyzingDocs.size > 0 ? "…" : ""}` : `Analyze Selected (${selectedDocs.size})`}
                </button>
              </div>
            )}
          </div>
          {docs.data.items.map((doc: DocumentItem) => {
            const isAnalyzing = analyzingDocs.has(doc.id);
            const result = analysisResults[doc.id];
            const error = analysisErrors[doc.id];
            const isDismissed = dismissed.has(doc.id);
            const isSelected = selectedDocs.has(doc.id);

            return (
              <div key={doc.id} className="card" style={{ marginBottom: "0.5rem" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                  <div style={{ display: "flex", gap: "0.5rem", alignItems: "flex-start" }}>
                    <input type="checkbox" checked={isSelected} onChange={() => toggleDocSelection(doc.id)}
                      style={{ marginTop: "0.3rem" }} />
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
                    onClick={() => analyzeMut.mutate(doc.id)}
                    disabled={isAnalyzing || batchRunning}>
                    {isAnalyzing ? "Analyzing…" : "Analyze"}
                  </button>
                </div>
                {isAnalyzing && (
                  <p style={{ marginTop: "0.5rem", color: "#666", fontStyle: "italic" }}>Analyzing document…</p>
                )}
                {error && (
                  <p className="error" style={{ marginTop: "0.5rem" }}>Analysis failed: {error}</p>
                )}
                {result && !isDismissed && renderSuggestion(result, doc.id)}
              </div>
            );
          })}
          {docs.data.total > 20 && (
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem" }}>
              <button className="btn" disabled={page <= 1} onClick={() => { setPage(p => p - 1); }}>Previous</button>
              <span style={{ lineHeight: "2rem" }}>Page {page} of {Math.ceil(docs.data.total / 20)}</span>
              <button className="btn" disabled={page * 20 >= docs.data.total} onClick={() => { setPage(p => p + 1); }}>Next</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
