import { useState, useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Title, Paper, Text, Group, Stack, Badge, Button, TextInput,
  MultiSelect, Select, Checkbox, Box, Loader, Alert, Pagination, SimpleGrid,
  NumberInput, ActionIcon,
} from "@mantine/core";
import { api, type PaperlessEntity, type PaperlessCustomField, type DocumentItem, type MetadataSuggestionResponse, type VisionAnalysisResult } from "../api";
import VisionAnalysisFlow from "../VisionAnalysisFlow";
import { useTranslation } from "react-i18next";

const FILTERS_KEY = "piq_analysis_filters";

interface AnalysisFilters {
  titleQuery: string;
  tagIds: string[];
  corrIds: string[];
  dtIds: string[];
  cfValues: Record<string, string>;
  cfAdded: string[];
}

const DEFAULT_FILTERS: AnalysisFilters = { titleQuery: "", tagIds: [], corrIds: [], dtIds: [], cfValues: {}, cfAdded: [] };

function loadFilters(): AnalysisFilters {
  try { const s = localStorage.getItem(FILTERS_KEY); return s ? { ...DEFAULT_FILTERS, ...JSON.parse(s) } : DEFAULT_FILTERS; }
  catch { return DEFAULT_FILTERS; }
}
function saveFilters(f: AnalysisFilters) { try { localStorage.setItem(FILTERS_KEY, JSON.stringify(f)); } catch {} }

export default function ManualPage() {
  const { t } = useTranslation();
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
  const settingsQ = useQuery({ queryKey: ["settings"], queryFn: api.getSettings, staleTime: 60_000 });
  const pageWarningThreshold = Number((settingsQ.data as Record<string, unknown> | undefined)?.vision_max_pages_warning ?? 5);

  const handleVisionResult = useCallback((docId: number, result: VisionAnalysisResult) => {
    setAnalysisResults(prev => ({ ...prev, [docId]: result.suggestion }));
  }, []);

  const updateFilters = useCallback((patch: Partial<AnalysisFilters>) => {
    setFilters(prev => { const next = { ...prev, ...patch }; saveFilters(next); return next; });
  }, []);

  const clearFilters = useCallback(() => { setFilters(DEFAULT_FILTERS); saveFilters(DEFAULT_FILTERS); setShouldSearch(false); }, []);

  const hasActiveFilters = filters.titleQuery.trim() || filters.tagIds.length > 0 || filters.corrIds.length > 0 || filters.dtIds.length > 0 || filters.cfAdded.some(id => filters.cfValues[id]);

  const buildParams = () => {
    const p: Record<string, string | string[]> = { page: String(page), page_size: "20" };
    if (filters.titleQuery.trim()) p.query = filters.titleQuery.trim();
    if (filters.tagIds.length) p.tag_ids = filters.tagIds;
    if (filters.corrIds.length) p.correspondent_ids = filters.corrIds;
    if (filters.dtIds.length) p.document_type_ids = filters.dtIds;
    for (const id of filters.cfAdded) { const v = filters.cfValues[id]; if (v) p[`custom_fields__${id}`] = v; }
    return p;
  };

  const docs = useQuery({ queryKey: ["documents", filters, page], queryFn: () => api.getDocuments(buildParams()), enabled: shouldSearch, retry: false });

  const analyzeOne = useCallback(async (docId: number) => {
    setAnalyzingDocs(prev => new Set(prev).add(docId));
    setAnalysisErrors(prev => { const next = { ...prev }; delete next[docId]; return next; });
    try { const result = await api.analyze(docId); setAnalysisResults(prev => ({ ...prev, [docId]: result })); }
    catch (err: unknown) { setAnalysisErrors(prev => ({ ...prev, [docId]: (err as Error).message })); }
    finally { setAnalyzingDocs(prev => { const next = new Set(prev); next.delete(docId); return next; }); }
  }, []);

  const handleBatchAnalyze = useCallback(async () => {
    if (selectedDocs.size === 0) return;
    setBatchRunning(true);
    await Promise.all(Array.from(selectedDocs).map(id => analyzeOne(id)));
    setBatchRunning(false);
    setSelectedDocs(new Set());
  }, [selectedDocs, analyzeOne]);

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
    } catch (err: unknown) { setAnalysisErrors(prev => ({ ...prev, [docId]: (err as Error).message })); }
    finally { setQueuingDocs(prev => { const next = new Set(prev); next.delete(docId); return next; }); }
  }, []);

  const handleQueueAll = useCallback(async () => {
    const toQueue = Object.keys(analysisResults).map(Number).filter(id => !queuedDocs.has(id) && !dismissed.has(id));
    await Promise.all(toQueue.map(id => handleQueue(analysisResults[id], id)));
  }, [analysisResults, queuedDocs, dismissed, handleQueue]);

  const handleSearch = () => { setPage(1); setShouldSearch(true); setSelectedDocs(new Set()); };
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
  const readyToQueue = useMemo(() => Object.keys(analysisResults).map(Number).filter(id => !queuedDocs.has(id) && !dismissed.has(id)), [analysisResults, queuedDocs, dismissed]);

  const toSelectData = (items: PaperlessEntity[]) => (items ?? []).map(o => ({ value: String(o.id), label: o.name }));
  const cfAvailableToAdd = (customFields.data ?? []).filter((cf: PaperlessCustomField) => !filters.cfAdded.includes(String(cf.id)));

  const renderSuggestion = (suggestion: MetadataSuggestionResponse, docId: number) => {
    const cfEntries = Object.entries(suggestion.custom_fields ?? {});
    const isQueuing = queuingDocs.has(docId);
    const isQueued = queuedDocs.has(docId);
    const hasFields = suggestion.title || suggestion.tags.length > 0 || suggestion.correspondent || suggestion.document_type || suggestion.storage_path || cfEntries.length > 0;

    return (
      <Paper withBorder p="sm" radius="sm" mt="sm" bg="var(--mantine-color-default-hover)">
        <Text size="xs" fw={700} tt="uppercase" c="dimmed" mb="xs">{t("analysis.suggestedMetadata")}</Text>
        {!hasFields ? (
          <Text size="sm" c="dimmed" fs="italic">{t("analysis.noMetadata")}</Text>
        ) : (
          <Stack gap={4}>
            {suggestion.title && <Group gap="sm"><Text size="xs" c="dimmed" w={110}>{t("analysis.title_field")}</Text><Text size="sm" fw={500}>{suggestion.title}</Text></Group>}
            {suggestion.tags.length > 0 && (
              <Group gap="sm" align="flex-start">
                <Text size="xs" c="dimmed" w={110}>{t("analysis.tags_field")}</Text>
                <Group gap={4}>{suggestion.tags.map((tag, i) => <Badge key={i} size="sm">{tag}</Badge>)}</Group>
              </Group>
            )}
            {suggestion.correspondent && <Group gap="sm"><Text size="xs" c="dimmed" w={110}>{t("analysis.correspondent_field")}</Text><Text size="sm">{suggestion.correspondent}</Text></Group>}
            {suggestion.document_type && <Group gap="sm"><Text size="xs" c="dimmed" w={110}>{t("analysis.docType_field")}</Text><Text size="sm">{suggestion.document_type}</Text></Group>}
            {suggestion.storage_path && <Group gap="sm"><Text size="xs" c="dimmed" w={110}>{t("analysis.storagePath_field")}</Text><Text size="sm">{suggestion.storage_path}</Text></Group>}
            {cfEntries.map(([key, val]) => <Group key={key} gap="sm"><Text size="xs" c="dimmed" w={110}>{key}</Text><Text size="sm">{String(val ?? "")}</Text></Group>)}
          </Stack>
        )}
        <Group gap="xs" mt="sm">
          {isQueued ? (
            <Text size="sm" c="teal">{t("analysis.queued")}</Text>
          ) : (
            <>
              <Button size="xs" loading={isQueuing} onClick={() => handleQueue(suggestion, docId)}>{t("analysis.queueForReview")}</Button>
              <Button size="xs" variant="default" disabled={isQueuing} onClick={() => handleDismiss(docId)}>{t("analysis.dismiss")}</Button>
            </>
          )}
        </Group>
      </Paper>
    );
  };

  return (
    <Stack gap="md">
      <Title order={2}>{t("analysis.title")}</Title>

      {paperlessUnavailable && (
        <Alert color="red" variant="light">{t("analysis.paperlessUnavailable")}</Alert>
      )}

      {/* Filter panel */}
      <Paper withBorder p="md" radius="md">
        <Stack gap="sm">
          <TextInput
            label={t("analysis.search")}
            placeholder={t("analysis.searchPlaceholder")}
            value={filters.titleQuery}
            onChange={e => updateFilters({ titleQuery: e.currentTarget.value })}
            onKeyDown={e => e.key === "Enter" && handleSearch()}
          />

          <SimpleGrid cols={3} spacing="sm">
            <MultiSelect
              label={t("analysis.tag")}
              placeholder={t("analysis.allTags")}
              data={toSelectData(tagsQ.data ?? [])}
              value={filters.tagIds}
              onChange={tagIds => updateFilters({ tagIds })}
              searchable clearable
            />
            <MultiSelect
              label={t("analysis.correspondent")}
              placeholder={t("analysis.allCorrespondents")}
              data={toSelectData(correspondents.data ?? [])}
              value={filters.corrIds}
              onChange={corrIds => updateFilters({ corrIds })}
              searchable clearable
            />
            <MultiSelect
              label={t("analysis.docType")}
              placeholder={t("analysis.allTypes")}
              data={toSelectData(docTypes.data ?? [])}
              value={filters.dtIds}
              onChange={dtIds => updateFilters({ dtIds })}
              searchable clearable
            />
          </SimpleGrid>

          {/* Custom field filters */}
          {filters.cfAdded.length > 0 && (
            <SimpleGrid cols={3} spacing="sm">
              {filters.cfAdded.map(cfId => {
                const cf = (customFields.data ?? []).find((c: PaperlessCustomField) => String(c.id) === cfId);
                if (!cf) return null;
                const val = filters.cfValues[cfId] ?? "";
                const setValue = (v: string) => updateFilters({ cfValues: { ...filters.cfValues, [cfId]: v } });
                const removeField = () => {
                  const nextAdded = filters.cfAdded.filter(id => id !== cfId);
                  const nextValues = { ...filters.cfValues }; delete nextValues[cfId];
                  updateFilters({ cfAdded: nextAdded, cfValues: nextValues });
                };
                return (
                  <Box key={cfId}>
                    <Group justify="space-between" mb={4}>
                      <Text size="xs" fw={500}>{cf.name}</Text>
                      <ActionIcon size="xs" variant="subtle" color="gray" onClick={removeField}>×</ActionIcon>
                    </Group>
                    {cf.data_type === "boolean" ? (
                      <Select value={val} onChange={v => setValue(v ?? "")} data={[{ value: "", label: "All" }, { value: "true", label: "Yes" }, { value: "false", label: "No" }]} />
                    ) : ["integer", "float", "monetary"].includes(cf.data_type) ? (
                      <NumberInput value={val} onChange={v => setValue(String(v))} placeholder={`Filter by ${cf.name}…`} />
                    ) : (
                      <TextInput value={val} onChange={e => setValue(e.currentTarget.value)} placeholder={`Filter by ${cf.name}…`} />
                    )}
                  </Box>
                );
              })}
            </SimpleGrid>
          )}

          <Group gap="sm">
            {cfAvailableToAdd.length > 0 && (
              <Select
                placeholder="＋ Add field filter…"
                data={cfAvailableToAdd.map((cf: PaperlessCustomField) => ({ value: String(cf.id), label: cf.name }))}
                value={null}
                onChange={v => { if (v) updateFilters({ cfAdded: [...filters.cfAdded, v] }); }}
                w={220}
              />
            )}
            <Button onClick={handleSearch} disabled={paperlessUnavailable}>{t("analysis.searchBtn")}</Button>
            {hasActiveFilters && (
              <Button variant="subtle" color="gray" onClick={clearFilters}>✕ Clear all filters</Button>
            )}
          </Group>
        </Stack>
      </Paper>

      {/* Results */}
      {docs.isLoading && <Loader size="sm" />}
      {docs.isError && <Alert color="red" variant="light">{t("analysis.searchFailed")}</Alert>}

      {docs.isSuccess && (
        <Stack gap="sm">
          <Group justify="space-between" align="center" wrap="wrap">
            <Text size="sm" c="dimmed">{t("analysis.docsFound", { count: docs.data.total })}</Text>
            {docs.data.items.length > 0 && (
              <Group gap="sm" wrap="wrap">
                <Checkbox size="xs" label={t("analysis.hideAnalyzed")} checked={hideAnalyzed} onChange={e => setHideAnalyzed(e.currentTarget.checked)} />
                <Checkbox
                  size="xs" label={t("analysis.selectAll")}
                  checked={docs.data.items.length > 0 && docs.data.items.every((d: DocumentItem) => selectedDocs.has(d.id))}
                  onChange={toggleSelectAll}
                />
                <Button size="xs" disabled={selectedDocs.size === 0 || batchRunning} loading={batchRunning} onClick={handleBatchAnalyze}>
                  {t("analysis.analyzeSelected", { count: String(selectedDocs.size) })}
                </Button>
                {readyToQueue.length >= 2 && (
                  <Button size="xs" disabled={queuingDocs.size > 0} onClick={handleQueueAll}>
                    {t("analysis.queueAll", { count: String(readyToQueue.length) })}
                  </Button>
                )}
              </Group>
            )}
          </Group>

          {docs.data.items.map((doc: DocumentItem) => {
            const isAnalyzing = analyzingDocs.has(doc.id);
            const result = analysisResults[doc.id];
            const error = analysisErrors[doc.id];
            const isDismissed = dismissed.has(doc.id);
            const wasAnalyzed = !!result || isDismissed;
            if (hideAnalyzed && wasAnalyzed) return null;
            return (
              <Paper key={doc.id} withBorder p="md" radius="md">
                <Group justify="space-between" align="flex-start" wrap="nowrap">
                  <Group align="flex-start" gap="sm" wrap="nowrap" style={{ flex: 1, minWidth: 0 }}>
                    <Checkbox mt={2} checked={selectedDocs.has(doc.id)} onChange={() => toggleDocSelection(doc.id)} />
                    <Box style={{ minWidth: 0 }}>
                      <Text fw={600} size="sm">{doc.title || `Document #${doc.id}`}</Text>
                      <Text size="xs" c="dimmed">
                        {doc.correspondent ? `${corrMap.get(doc.correspondent) ?? doc.correspondent} · ` : ""}
                        {doc.document_type ? `${dtMap.get(doc.document_type) ?? doc.document_type}${doc.tags.length > 0 ? " · " : ""}` : ""}
                        {doc.tags.length > 0 && doc.tags.map(tg => tagMap.get(tg) ?? tg).join(", ")}
                      </Text>
                    </Box>
                  </Group>
                  <Group gap="xs" style={{ flexShrink: 0 }}>
                    <Button size="xs" loading={isAnalyzing} disabled={batchRunning} onClick={() => analyzeOne(doc.id)}>
                      {t("analysis.analyze")}
                    </Button>
                    <VisionAnalysisFlow
                      documentId={doc.id}
                      pageWarningThreshold={pageWarningThreshold}
                      onResult={result => handleVisionResult(doc.id, result)}
                      size="xs"
                      disabled={batchRunning}
                    />
                  </Group>
                </Group>
                {isAnalyzing && <Text size="sm" c="dimmed" fs="italic" mt="xs">{t("analysis.analyzingDoc")}</Text>}
                {error && <Text size="sm" c="red" mt="xs">{t("analysis.analysisFailed")} {error}</Text>}
                {result && !isDismissed && renderSuggestion(result, doc.id)}
              </Paper>
            );
          })}

          {docs.data.total > 20 && (
            <Group justify="center">
              <Pagination total={Math.ceil(docs.data.total / 20)} value={page} onChange={setPage} size="sm" />
            </Group>
          )}
        </Stack>
      )}
    </Stack>
  );
}
