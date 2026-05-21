import { useState, useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type PaperlessEntity, type PaperlessCustomField, type DocumentItem, type MetadataSuggestionResponse } from "../api";
import { t } from "../i18n";

// ---------------------------------------------------------------------------
// Persistent filter state (survives navigation)
// ---------------------------------------------------------------------------

const FILTERS_KEY = "piq_analysis_filters";

interface AnalysisFilters {
  titleQuery: string;
  tagIds: string[];
  corrIds: string[];
  dtIds: string[];
  cfValues: Record<string, string>;   // fieldId → value
  cfAdded: string[];                  // fieldIds explicitly added by the user
}

const DEFAULT_FILTERS: AnalysisFilters = {
  titleQuery: "", tagIds: [], corrIds: [], dtIds: [],
  cfValues: {}, cfAdded: [],
};

function loadFilters(): AnalysisFilters {
  try {
    const s = localStorage.getItem(FILTERS_KEY);
    return s ? { ...DEFAULT_FILTERS, ...JSON.parse(s) } : DEFAULT_FILTERS;
  } catch { return DEFAULT_FILTERS; }
}

function saveFilters(f: AnalysisFilters) {
  try { localStorage.setItem(FILTERS_KEY, JSON.stringify(f)); } catch {}
}

// ---------------------------------------------------------------------------
// MultiEntityFilter — chip-based multi-select for tags / correspondents / etc.
// ---------------------------------------------------------------------------

const CHIP_BASE: React.CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: "4px",
  padding: "2px 8px", borderRadius: "12px", fontSize: "0.8rem",
  background: "var(--chip-filled-bg)", border: "1px solid var(--chip-filled-border)",
  color: "var(--chip-filled-text)",
};

function MultiEntityFilter({
  options, selected, onChange, placeholder,
}: {
  options: PaperlessEntity[];
  selected: string[];
  onChange: (ids: string[]) => void;
  placeholder: string;
}) {
  const selectedSet = new Set(selected);
  const available = options.filter(o => !selectedSet.has(String(o.id)));
  const getLabel = (id: string) => options.find(o => String(o.id) === id)?.name ?? `#${id}`;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.35rem" }}>
      {available.length > 0 ? (
        <select
          value=""
          onChange={e => { if (e.target.value) onChange([...selected, e.target.value]); }}
          style={{ fontSize: "0.82rem", padding: "0.3rem 0.5rem" }}
        >
          <option value="">
            {selected.length === 0 ? `— ${placeholder} —` : `＋ Add ${placeholder.toLowerCase()}`}
          </option>
          {available.map(o => <option key={o.id} value={String(o.id)}>{o.name}</option>)}
        </select>
      ) : selected.length > 0 ? (
        <span style={{ fontSize: "0.78rem", color: "var(--text-on-card-muted)", fontStyle: "italic" }}>
          All {placeholder.toLowerCase()}s selected
        </span>
      ) : null}
      {selected.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.3rem" }}>
          {selected.map(id => (
            <span key={id} style={CHIP_BASE}>
              {getLabel(id)}
              <button
                type="button"
                onClick={() => onChange(selected.filter(s => s !== id))}
                style={{ background: "none", border: "none", cursor: "pointer", padding: 0, color: "rgba(255,255,255,0.7)", fontSize: "1rem", lineHeight: 1, marginLeft: "1px" }}
              >×</button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function ManualPage() {
  const [filters, setFilters] = useState<AnalysisFilters>(loadFilters);
  const [page, setPage] = useState(1);
  const [shouldSearch, setShouldSearch] = useState(false);

  const [analysisResults, setAnalysisResults] = useState<Record<number, MetadataSuggestionResponse>>({});
  const [analysisErrors, setAnalysisErrors] = useState<Record<number, string>>({});
  const [analyzingDocs, setAnalyzingDocs] = useState<Set<number>>(new Set());
  const [dismissed, setDismissed] = useState<Set<number>>(new Set());
  const [queuedDocs, setQueuedDocs] = useState<Set<number>>(new Set());
  const [queuingDocs, setQueuingDocs] = useState<Set<number>>(new Set());
  const [selectedDocs, setSelectedDocs] = useState<Set<number>>(new Set());
  const [batchRunning, setBatchRunning] = useState(false);
  const [hideAnalyzed, setHideAnalyzed] = useState(false);

  const tagsQ = useQuery({ queryKey: ["tags"], queryFn: api.getTags, retry: false });
  const correspondents = useQuery({ queryKey: ["correspondents"], queryFn: api.getCorrespondents, retry: false });
  const docTypes = useQuery({ queryKey: ["docTypes"], queryFn: api.getDocumentTypes, retry: false });
  const customFields = useQuery({ queryKey: ["customFields"], queryFn: api.getCustomFields, retry: false });

  // Persist filters whenever they change
  const updateFilters = useCallback((patch: Partial<AnalysisFilters>) => {
    setFilters(prev => {
      const next = { ...prev, ...patch };
      saveFilters(next);
      return next;
    });
  }, []);

  const clearFilters = useCallback(() => {
    const cleared = { ...DEFAULT_FILTERS };
    setFilters(cleared);
    saveFilters(cleared);
    setShouldSearch(false);
  }, []);

  const hasActiveFilters =
    filters.titleQuery.trim() ||
    filters.tagIds.length > 0 ||
    filters.corrIds.length > 0 ||
    filters.dtIds.length > 0 ||
    filters.cfAdded.some(id => filters.cfValues[id]);

  const buildParams = () => {
    const p: Record<string, string | string[]> = { page: String(page), page_size: "20" };
    if (filters.titleQuery.trim()) p.query = filters.titleQuery.trim();
    if (filters.tagIds.length) p.tag_ids = filters.tagIds;
    if (filters.corrIds.length) p.correspondent_ids = filters.corrIds;
    if (filters.dtIds.length) p.document_type_ids = filters.dtIds;
    for (const id of filters.cfAdded) {
      const v = filters.cfValues[id];
      if (v) p[`custom_fields__${id}`] = v;
    }
    return p;
  };

  const docs = useQuery({
    queryKey: ["documents", filters, page],
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

  const handleBatchAnalyze = useCallback(async () => {
    if (selectedDocs.size === 0) return;
    setBatchRunning(true);
    await Promise.all(Array.from(selectedDocs).map(id => analyzeOne(id)));
    setBatchRunning(false);
    setSelectedDocs(new Set());
  }, [selectedDocs, analyzeOne]);

  /** Queue a suggestion for review. Shows success flash for 1.8 s then auto-removes. */
  const handleQueue = useCallback(async (suggestion: MetadataSuggestionResponse, docId: number) => {
    setQueuingDocs(prev => new Set(prev).add(docId));
    try {
      await api.enqueueSuggestion(suggestion);
      setQueuedDocs(prev => new Set(prev).add(docId));
      setTimeout(() => {
        setDismissed(prev => new Set(prev).add(docId));
        setAnalysisResults(prev => { const next = { ...prev }; delete next[docId]; return next; });
        setQueuedDocs(prev => { const next = new Set(prev); next.delete(docId); return next; });
      }, 1800);
    } catch (err: unknown) {
      setAnalysisErrors(prev => ({ ...prev, [docId]: (err as Error).message }));
    } finally {
      setQueuingDocs(prev => { const next = new Set(prev); next.delete(docId); return next; });
    }
  }, []);

  /** Queue all suggestions that haven't been queued or dismissed yet. */
  const handleQueueAll = useCallback(async () => {
    const toQueue = Object.keys(analysisResults)
      .map(Number)
      .filter(id => !queuedDocs.has(id) && !dismissed.has(id));
    await Promise.all(toQueue.map(id => handleQueue(analysisResults[id], id)));
  }, [analysisResults, queuedDocs, dismissed, handleQueue]);

  const handleSearch = () => { setPage(1); setShouldSearch(true); setSelectedDocs(new Set()); };
  const handleKeyDown = (e: React.KeyboardEvent) => { if (e.key === "Enter") handleSearch(); };
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

  const paperlessUnavailable = tagsQ.isError;
  const tagMap = new Map((tagsQ.data ?? []).map((t: PaperlessEntity) => [t.id, t.name]));
  const corrMap = new Map((correspondents.data ?? []).map((c: PaperlessEntity) => [c.id, c.name]));
  const dtMap = new Map((docTypes.data ?? []).map((d: PaperlessEntity) => [d.id, d.name]));

  /** Count of analyzed results ready to be queued (not yet queued/dismissed). */
  const readyToQueue = useMemo(
    () => Object.keys(analysisResults).map(Number).filter(id => !queuedDocs.has(id) && !dismissed.has(id)),
    [analysisResults, queuedDocs, dismissed]
  );

  // ---------------------------------------------------------------------------
  // Compact read-only suggestion preview
  // ---------------------------------------------------------------------------

  const renderSuggestion = (suggestion: MetadataSuggestionResponse, docId: number) => {
    const customFieldEntries = Object.entries(suggestion.custom_fields ?? {});
    const isQueuing = queuingDocs.has(docId);
    const isQueued = queuedDocs.has(docId);
    const hasFields =
      suggestion.title || suggestion.tags.length > 0 || suggestion.correspondent ||
      suggestion.document_type || suggestion.storage_path || customFieldEntries.length > 0;

    const rowStyle: React.CSSProperties = { display: "flex", gap: "0.5rem", alignItems: "flex-start", fontSize: "0.82rem" };
    const labelStyle: React.CSSProperties = { color: "var(--text-on-card-muted)", minWidth: "110px", flexShrink: 0 };
    const valueStyle: React.CSSProperties = { color: "var(--text-on-card)", fontWeight: 500 };

    return (
      <div style={{
        marginTop: "0.5rem", padding: "0.75rem 1rem",
        background: "rgba(0,0,0,0.04)", borderRadius: "6px",
        border: "1px solid var(--gray-200)",
      }}>
        <strong style={{ fontSize: "0.82rem", color: "var(--text-on-card-secondary)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
          {t("analysis.suggestedMetadata")}
        </strong>

        {!hasFields ? (
          <p style={{ color: "var(--text-on-card-muted)", fontStyle: "italic", fontSize: "0.82rem", marginTop: "0.4rem" }}>
            {t("analysis.noMetadata")}
          </p>
        ) : (
          <div style={{ marginTop: "0.5rem", display: "flex", flexDirection: "column", gap: "0.3rem" }}>
            {suggestion.title && (
              <div style={rowStyle}>
                <span style={labelStyle}>{t("analysis.title_field")}</span>
                <span style={valueStyle}>{suggestion.title}</span>
              </div>
            )}
            {suggestion.tags.length > 0 && (
              <div style={rowStyle}>
                <span style={labelStyle}>{t("analysis.tags_field")}</span>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "0.25rem" }}>
                  {suggestion.tags.map((tag, i) => (
                    <span key={i} style={{
                      background: "var(--petrol-600)", color: "#fff",
                      borderRadius: "10px", padding: "1px 8px", fontSize: "0.75rem",
                    }}>{tag}</span>
                  ))}
                </div>
              </div>
            )}
            {suggestion.correspondent && (
              <div style={rowStyle}>
                <span style={labelStyle}>{t("analysis.correspondent_field")}</span>
                <span style={{ color: "var(--text-on-card)" }}>{suggestion.correspondent}</span>
              </div>
            )}
            {suggestion.document_type && (
              <div style={rowStyle}>
                <span style={labelStyle}>{t("analysis.docType_field")}</span>
                <span style={{ color: "var(--text-on-card)" }}>{suggestion.document_type}</span>
              </div>
            )}
            {suggestion.storage_path && (
              <div style={rowStyle}>
                <span style={labelStyle}>{t("analysis.storagePath_field")}</span>
                <span style={{ color: "var(--text-on-card)" }}>{suggestion.storage_path}</span>
              </div>
            )}
            {customFieldEntries.map(([key, val]) => (
              <div key={key} style={rowStyle}>
                <span style={labelStyle}>{key}</span>
                <span style={{ color: "var(--text-on-card)" }}>{String(val ?? "")}</span>
              </div>
            ))}
          </div>
        )}

        {isQueued ? (
          <p className="success" style={{ marginTop: "0.6rem", fontSize: "0.85rem" }}>
            {t("analysis.queued")}
          </p>
        ) : (
          <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.75rem" }}>
            <button className="btn btn-primary" disabled={isQueuing}
              onClick={() => handleQueue(suggestion, docId)}>
              {isQueuing ? t("analysis.queuing") : t("analysis.queueForReview")}
            </button>
            <button className="btn" disabled={isQueuing}
              onClick={() => handleDismiss(docId)}>
              {t("analysis.dismiss")}
            </button>
          </div>
        )}
      </div>
    );
  };

  // Custom fields available to add (not yet added)
  const cfAvailableToAdd = (customFields.data ?? []).filter(
    (cf: PaperlessCustomField) => !filters.cfAdded.includes(String(cf.id))
  );

  return (
    <div>
      <h2>{t("analysis.title")}</h2>
      {paperlessUnavailable && (
        <div className="card"><p className="error">{t("analysis.paperlessUnavailable")}</p></div>
      )}

      {/* ── Filter panel ── */}
      <div className="card">
        {/* Title search */}
        <div className="form-group">
          <label htmlFor="title-search">{t("analysis.search")}</label>
          <input id="title-search" value={filters.titleQuery}
            onChange={e => updateFilters({ titleQuery: e.target.value })}
            onKeyDown={handleKeyDown}
            placeholder={t("analysis.searchPlaceholder")} />
        </div>

        {/* Multi-select row: Tags | Correspondent | Document Type */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "0.75rem", marginBottom: "0.75rem" }}>
          <div className="form-group" style={{ margin: 0 }}>
            <label>{t("analysis.tag")}</label>
            <MultiEntityFilter
              options={tagsQ.data ?? []}
              selected={filters.tagIds}
              onChange={tagIds => updateFilters({ tagIds })}
              placeholder={t("analysis.allTags")}
            />
          </div>
          <div className="form-group" style={{ margin: 0 }}>
            <label>{t("analysis.correspondent")}</label>
            <MultiEntityFilter
              options={correspondents.data ?? []}
              selected={filters.corrIds}
              onChange={corrIds => updateFilters({ corrIds })}
              placeholder={t("analysis.allCorrespondents")}
            />
          </div>
          <div className="form-group" style={{ margin: 0 }}>
            <label>{t("analysis.docType")}</label>
            <MultiEntityFilter
              options={docTypes.data ?? []}
              selected={filters.dtIds}
              onChange={dtIds => updateFilters({ dtIds })}
              placeholder={t("analysis.allTypes")}
            />
          </div>
        </div>

        {/* On-demand custom field filters */}
        {filters.cfAdded.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem", marginBottom: "0.75rem" }}>
            {filters.cfAdded.map(cfId => {
              const cf = (customFields.data ?? []).find((c: PaperlessCustomField) => String(c.id) === cfId);
              if (!cf) return null;
              const val = filters.cfValues[cfId] ?? "";
              const setValue = (v: string) => updateFilters({ cfValues: { ...filters.cfValues, [cfId]: v } });
              const removeField = () => {
                const nextAdded = filters.cfAdded.filter(id => id !== cfId);
                const nextValues = { ...filters.cfValues };
                delete nextValues[cfId];
                updateFilters({ cfAdded: nextAdded, cfValues: nextValues });
              };
              return (
                <div key={cfId} className="form-group" style={{ margin: 0, minWidth: "180px", flex: "1 1 180px" }}>
                  <label style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span>{cf.name}</span>
                    <button type="button" onClick={removeField}
                      style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-on-card-muted)", fontSize: "1rem", lineHeight: 1, padding: 0 }}
                      title="Remove this filter">×</button>
                  </label>
                  {cf.data_type === "boolean" ? (
                    <select value={val} onChange={e => setValue(e.target.value)}>
                      <option value="">All</option>
                      <option value="true">Yes</option>
                      <option value="false">No</option>
                    </select>
                  ) : cf.data_type === "date" ? (
                    <input type="date" value={val} onChange={e => setValue(e.target.value)} />
                  ) : ["integer", "float", "monetary"].includes(cf.data_type) ? (
                    <input type="number" value={val} onChange={e => setValue(e.target.value)} placeholder={`Filter by ${cf.name}…`} />
                  ) : (
                    <input type="text" value={val} onChange={e => setValue(e.target.value)} placeholder={`Filter by ${cf.name}…`} />
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* Add field filter + actions row */}
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
          {cfAvailableToAdd.length > 0 && (
            <select
              value=""
              onChange={e => {
                if (e.target.value)
                  updateFilters({ cfAdded: [...filters.cfAdded, e.target.value] });
              }}
              style={{ fontSize: "0.82rem", padding: "0.3rem 0.5rem" }}
            >
              <option value="">＋ Add field filter…</option>
              {cfAvailableToAdd.map((cf: PaperlessCustomField) => (
                <option key={cf.id} value={String(cf.id)}>{cf.name}</option>
              ))}
            </select>
          )}

          <button className="btn btn-primary" onClick={handleSearch} disabled={paperlessUnavailable}>
            {t("analysis.searchBtn")}
          </button>

          {hasActiveFilters && (
            <button
              className="btn"
              onClick={clearFilters}
              style={{ fontSize: "0.82rem", color: "var(--text-on-card-muted)" }}
            >
              ✕ Clear all filters
            </button>
          )}
        </div>
      </div>

      {/* ── Results ── */}
      {docs.isLoading && <p>{t("analysis.searching")}</p>}
      {docs.isError && <p className="error">{t("analysis.searchFailed")}</p>}
      {docs.isSuccess && (
        <div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", margin: "0.75rem 0 0.5rem", flexWrap: "wrap", gap: "0.5rem" }}>
            <p style={{ margin: 0, color: "var(--text-on-body-secondary)" }}>
              {t("analysis.docsFound", { count: docs.data.total })}
            </p>
            {docs.data.items.length > 0 && (
              <div style={{ display: "flex", gap: "0.75rem", alignItems: "center", flexWrap: "wrap" }}>
                <label style={{ fontSize: "0.85rem", cursor: "pointer", display: "flex", alignItems: "center", gap: "0.25rem", color: "var(--text-on-body-secondary)" }}>
                  <input type="checkbox" checked={hideAnalyzed} onChange={e => setHideAnalyzed(e.target.checked)} />
                  {t("analysis.hideAnalyzed")}
                </label>
                <label style={{ fontSize: "0.85rem", cursor: "pointer", display: "flex", alignItems: "center", gap: "0.25rem", color: "var(--text-on-body-secondary)" }}>
                  <input type="checkbox"
                    checked={docs.data.items.length > 0 && docs.data.items.every((d: DocumentItem) => selectedDocs.has(d.id))}
                    onChange={toggleSelectAll} />
                  {t("analysis.selectAll")}
                </label>
                <button className="btn btn-primary" onClick={handleBatchAnalyze} disabled={selectedDocs.size === 0 || batchRunning}>
                  {batchRunning ? t("analysis.analyzing") : t("analysis.analyzeSelected", { count: String(selectedDocs.size) })}
                </button>
                {readyToQueue.length >= 2 && (
                  <button className="btn btn-primary" onClick={handleQueueAll} disabled={queuingDocs.size > 0}>
                    {t("analysis.queueAll", { count: String(readyToQueue.length) })}
                  </button>
                )}
              </div>
            )}
          </div>

          {(() => {
            let visibleIdx = 0;
            return docs.data.items.map((doc: DocumentItem) => {
              const isAnalyzing = analyzingDocs.has(doc.id);
              const result = analysisResults[doc.id];
              const error = analysisErrors[doc.id];
              const isDismissed = dismissed.has(doc.id);
              const wasAnalyzed = !!result || isDismissed;
              if (hideAnalyzed && wasAnalyzed) return null;
              const cardIdx = visibleIdx++;
              return (
                <div key={doc.id} className={`card${cardIdx % 2 === 1 ? " card-alt" : ""}`} style={{ marginBottom: "0.5rem" }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                    <div style={{ display: "flex", gap: "0.5rem", alignItems: "flex-start" }}>
                      <input type="checkbox" checked={selectedDocs.has(doc.id)} onChange={() => toggleDocSelection(doc.id)} style={{ marginTop: "0.3rem" }} />
                      <div>
                        <strong style={{ color: "var(--text-on-card)" }}>{doc.title || `Document #${doc.id}`}</strong>
                        <div style={{ fontSize: "0.82rem", color: "var(--text-on-card-muted)", marginTop: "0.2rem" }}>
                          {doc.correspondent ? <span>{corrMap.get(doc.correspondent) ?? doc.correspondent} · </span> : null}
                          {doc.document_type ? <span>{dtMap.get(doc.document_type) ?? doc.document_type}{doc.tags.length > 0 ? " · " : ""}</span> : null}
                          {doc.tags.length > 0 && <span>{doc.tags.map(tg => tagMap.get(tg) ?? tg).join(", ")}</span>}
                        </div>
                      </div>
                    </div>
                    <button
                      className="btn btn-primary"
                      style={{ whiteSpace: "nowrap", marginLeft: "1rem", flexShrink: 0 }}
                      onClick={() => analyzeOne(doc.id)}
                      disabled={isAnalyzing || batchRunning}
                    >
                      {isAnalyzing ? t("analysis.analyzing") : t("analysis.analyze")}
                    </button>
                  </div>
                  {isAnalyzing && (
                    <p style={{ marginTop: "0.5rem", color: "var(--text-on-card-muted)", fontStyle: "italic", fontSize: "0.85rem" }}>
                      {t("analysis.analyzingDoc")}
                    </p>
                  )}
                  {error && (
                    <p className="error" style={{ marginTop: "0.5rem" }}>
                      {t("analysis.analysisFailed")} {error}
                    </p>
                  )}
                  {result && !isDismissed && renderSuggestion(result, doc.id)}
                </div>
              );
            });
          })()}

          {docs.data.total > 20 && (
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem", alignItems: "center" }}>
              <button className="btn" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>←</button>
              <span style={{ lineHeight: "2rem", fontSize: "0.85rem", color: "var(--text-on-body-secondary)" }}>
                {page} / {Math.ceil(docs.data.total / 20)}
              </span>
              <button className="btn" disabled={page * 20 >= docs.data.total} onClick={() => setPage(p => p + 1)}>→</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
