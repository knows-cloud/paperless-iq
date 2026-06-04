import React, { useState, useMemo, useEffect, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Title, Paper, Text, Group, Stack, Badge, Button, TextInput,
  Box, Alert, Anchor, Loader, Switch, Tabs,
} from "@mantine/core";
import { api, type PaperlessEntity, type PaperlessCustomField, type VisionAnalysisResult } from "../api";
import TagInput from "../TagInput";
import AutocompleteInput from "../AutocompleteInput";
import CfNameEditor from "../CfNameEditor";
import VisionAnalysisFlow from "../VisionAnalysisFlow";
import { ContentDiffModal } from "../components/ContentDiffModal";
import { useTranslation } from "react-i18next";

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
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data, isLoading } = useQuery({ queryKey: ["queue"], queryFn: () => api.getQueue({ status: "pending" }) });
  const statusQ = useQuery({ queryKey: ["status"], queryFn: api.getStatus, retry: false, staleTime: 60_000 });
  const tagsQ = useQuery({ queryKey: ["tags"], queryFn: api.getTags, retry: false });
  const corrsQ = useQuery({ queryKey: ["correspondents"], queryFn: api.getCorrespondents, retry: false });
  const dtQ = useQuery({ queryKey: ["docTypes"], queryFn: api.getDocumentTypes, retry: false });
  const cfQ = useQuery({ queryKey: ["customFields"], queryFn: api.getCustomFields, retry: false });
  const spQ = useQuery({ queryKey: ["storagePaths"], queryFn: api.getStoragePaths, retry: false });

  const paperlessUrl = (statusQ.data?.paperless_public_url || statusQ.data?.paperless_url || "").replace(/\/$/, "");
  const settingsQ = useQuery({ queryKey: ["settings"], queryFn: api.getSettings, staleTime: 60_000 });
  const pageWarningThreshold = Number((settingsQ.data as Record<string, unknown> | undefined)?.vision_max_pages_warning ?? 5);

  const corrNames = useMemo(() => new Set((corrsQ.data ?? []).map((c: PaperlessEntity) => c.name.toLowerCase())), [corrsQ.data]);
  const dtNames = useMemo(() => new Set((dtQ.data ?? []).map((d: PaperlessEntity) => d.name.toLowerCase())), [dtQ.data]);
  const cfNames = useMemo(() => new Set((cfQ.data ?? []).map((c: PaperlessCustomField) => c.name.toLowerCase())), [cfQ.data]);

  const [edits, setEdits] = useState<Record<string, QueueItem>>({});
  // tagOverrides[suggestionId][tagName] = true (force keep/add) | false (force remove)
  const [tagOverrides, setTagOverrides] = useState<Record<string, Record<string, boolean>>>({});
  const [existingTagsMap, setExistingTagsMap] = useState<Record<number, string[]>>({});
  const [showEmptyConfirm, setShowEmptyConfirm] = useState(false);
  const [reanalyzingIds, setReanalyzingIds] = useState<Set<string>>(new Set());
  const [contentView, setContentView] = useState<{ extracted: string | null; original: string | null } | null>(null);
  const [contentApply, setContentApply] = useState<Record<string, boolean>>({});
  const [openPreviews, setOpenPreviews] = useState<Set<number>>(new Set());
  const [previewUrls, setPreviewUrls] = useState<Record<number, string>>({});
  const [previewErrors, setPreviewErrors] = useState<Record<number, string>>({});
  const [previewLoading, setPreviewLoading] = useState<Set<number>>(new Set());

  useEffect(() => {
    const urls = previewUrls;
    return () => { Object.values(urls).forEach(u => URL.revokeObjectURL(u)); };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const items = (data?.items ?? []) as Array<Record<string, unknown>>;

  // Group pending suggestions by document — one card per document, a tab per
  // suggestion. Within a group, order chronologically (oldest → newest) so the
  // tabs read left-to-right by age; the newest is selected by default.
  const groups = useMemo(() => {
    const m = new Map<number, Array<Record<string, unknown>>>();
    for (const raw of items) {
      const docId = Number(raw.document_id);
      const arr = m.get(docId);
      if (arr) arr.push(raw); else m.set(docId, [raw]);
    }
    return [...m.entries()].map(([documentId, suggestions]) => ({
      documentId,
      suggestions: suggestions
        .slice()
        .sort((a, b) => String(a.created_at).localeCompare(String(b.created_at))),
    }));
  }, [items]);

  // Compact local date/time for tab labels and the per-suggestion header.
  const fmtDateTime = (iso: unknown): string => {
    const d = new Date(String(iso));
    return isNaN(d.getTime())
      ? ""
      : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  };

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

  const togglePreview = useCallback(async (docId: number) => {
    if (openPreviews.has(docId)) {
      setOpenPreviews(prev => { const next = new Set(prev); next.delete(docId); return next; });
      return;
    }
    setOpenPreviews(prev => new Set(prev).add(docId));
    if (previewUrls[docId] || previewLoading.has(docId)) return;
    setPreviewLoading(prev => new Set(prev).add(docId));
    try {
      const blob = await api.getDocumentPreview(docId);
      setPreviewUrls(prev => ({ ...prev, [docId]: URL.createObjectURL(blob) }));
    } catch (err: unknown) {
      setPreviewErrors(prev => ({ ...prev, [docId]: (err as Error).message }));
    } finally {
      setPreviewLoading(prev => { const next = new Set(prev); next.delete(docId); return next; });
    }
  }, [openPreviews, previewUrls, previewLoading]);

  const approve = useMutation({
    mutationFn: ({ id, item, docId }: { id: string; item: QueueItem; docId: number }) => {
      const currentTags = existingTagsMap[docId] ?? [];
      const suggestedTags = item.tags; // LLM output
      const overrides = tagOverrides[id] ?? {};

      // Build the complete final tag set:
      // - Start from union of current + suggested + user-added (override=true not in either)
      const allTagNames = new Set([...currentTags, ...suggestedTags]);
      for (const [tag, include] of Object.entries(overrides)) {
        if (include) allTagNames.add(tag);
      }

      const finalTags: string[] = [];
      for (const tag of allTagNames) {
        const inSuggested = suggestedTags.includes(tag);
        const override = overrides[tag];
        // Default: keep if LLM included it; override takes precedence
        const shouldInclude = override !== undefined ? override : inSuggested;
        if (shouldInclude) finalTags.push(tag);
      }

      return api.approveItem(id, {
        edits: {
          title: item.title,
          tags: finalTags,
          correspondent: item.correspondent,
          document_type: item.document_type,
          storage_path: item.storage_path,
          custom_fields: item.custom_fields,
        },
        merge_tags: false, // we send the complete desired set
        // Default ON; backend only writes content when the suggestion actually has it.
        apply_content: contentApply[id] ?? true,
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
    onSuccess: () => qc.invalidateQueries({ queryKey: ["queue"] }),
  });

  const handleReanalyze = async (id: string) => {
    setReanalyzingIds(prev => new Set(prev).add(id));
    try { await api.reanalyzeItem(id); qc.invalidateQueries({ queryKey: ["queue"] }); } catch { /* ignore */ }
    setReanalyzingIds(prev => { const n = new Set(prev); n.delete(id); return n; });
  };

  const handleVisionResult = useCallback((raw: Record<string, unknown>, result: VisionAnalysisResult) => {
    const s = result.suggestion;
    const id = String(raw.id);
    // Replace the displayed metadata fields with the vision suggestion values.
    setEdits(prev => ({
      ...prev,
      [id]: {
        id,
        document_id: s.document_id,
        title: s.title,
        tags: s.tags,
        correspondent: s.correspondent,
        document_type: s.document_type,
        storage_path: s.storage_path,
        custom_fields: s.custom_fields as Record<string, unknown>,
      },
    }));
    // Refresh the queue so the new vision suggestion appears.
    qc.invalidateQueries({ queryKey: ["queue"] });
  }, [qc]);

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

  if (isLoading) return <Loader size="sm" mt="xl" />;

  return (
    <Stack gap="md">
      <Group justify="space-between" align="center">
        <Title order={2}>{t("queue.title")}</Title>
        {items.length > 0 && (
          <Group gap="xs">
            <Button onClick={() => reanalyzeAll.mutate()} loading={reanalyzeAll.isPending} size="sm">
              {t("queue.reanalyzeAll", { count: String(items.length) })}
            </Button>
            <Button color="red" variant="light" size="sm" onClick={() => setShowEmptyConfirm(true)}>
              {t("queue.emptyQueue")}
            </Button>
          </Group>
        )}
      </Group>

      {showEmptyConfirm && (
        <Alert color="orange" variant="light">
          <Text fw={600} size="sm" mb={4}>{t("queue.emptyConfirm")}</Text>
          <Text size="sm" c="dimmed" mb="sm">{t("queue.emptyConfirmDetail", { count: String(items.length) })}</Text>
          <Group gap="xs">
            <Button color="red" size="xs" onClick={() => emptyQueue.mutate()} loading={emptyQueue.isPending}>
              {t("queue.emptyConfirmYes")}
            </Button>
            <Button variant="default" size="xs" onClick={() => setShowEmptyConfirm(false)}>{t("common.cancel")}</Button>
          </Group>
        </Alert>
      )}

      {items.length === 0 && !showEmptyConfirm && (
        <Text c="dimmed">{t("queue.empty")}</Text>
      )}

      {groups.map((group) => {
        const documentId = group.documentId;
        const suggestions = group.suggestions;
        const headerRaw = suggestions[0];
        const headerTitle = (headerRaw.title as string) || `${t("queue.document")} #${documentId}`;
        const previewOpen = openPreviews.has(documentId);
        const previewUrl = previewUrls[documentId];
        const previewErr = previewErrors[documentId];
        const previewIsLoading = previewLoading.has(documentId);

        return (
          <Paper key={documentId} withBorder p="md" radius="md">
            {/* Document header */}
            <Group justify="space-between" align="flex-start" wrap="nowrap" mb="sm">
              <Box style={{ flex: 1, minWidth: 0 }}>
                <Text fw={600}>{headerTitle}</Text>
                <Text size="xs" c="dimmed">
                  #{documentId}
                  {paperlessUrl && (
                    <Anchor href={`${paperlessUrl}/documents/${documentId}/details`} target="_blank" size="xs" ml={6}>
                      {t("queue.openInPaperless")}
                    </Anchor>
                  )}
                  {suggestions.length > 1 && (
                    <Badge ml={8} size="xs" variant="light" color="blue">
                      {t("queue.pendingCount", { count: String(suggestions.length) })}
                    </Badge>
                  )}
                </Text>
              </Box>
              <Button size="xs" variant="default" onClick={() => togglePreview(documentId)}>
                {previewOpen ? `✕ ${t("queue.hidePreview")}` : `📄 ${t("queue.preview")}`}
              </Button>
            </Group>

            {/* Preview panel */}
            {previewOpen && (
              <Box mb="sm" style={{ borderRadius: "var(--mantine-radius-sm)", overflow: "hidden", border: "1px solid var(--mantine-color-default-border)" }}>
                {previewIsLoading ? (
                  <Box p="xl" style={{ textAlign: "center" }}><Loader size="sm" /></Box>
                ) : previewErr ? (
                  <Group p="sm" gap="sm">
                    <Text size="sm" c="red">{t("queue.previewError")} {previewErr}</Text>
                    {paperlessUrl && (
                      <Anchor href={`${paperlessUrl}/documents/${documentId}/details`} target="_blank" size="sm">
                        {t("queue.openInPaperless")}
                      </Anchor>
                    )}
                  </Group>
                ) : previewUrl ? (
                  <iframe src={previewUrl} title={`Preview #${documentId}`} style={{ width: "100%", height: 640, border: "none", display: "block" }} />
                ) : null}
              </Box>
            )}

            <Tabs defaultValue={String(suggestions[suggestions.length - 1].id)}>
              {suggestions.length > 1 && (
                <Tabs.List mb="sm">
                  {suggestions.map((raw, i) => {
                    const isNewest = i === suggestions.length - 1;
                    return (
                      <Tabs.Tab
                        key={String(raw.id)}
                        value={String(raw.id)}
                        rightSection={isNewest ? (
                          <Badge size="xs" variant="light" color="teal">{t("queue.newest")}</Badge>
                        ) : undefined}
                      >
                        {fmtDateTime(raw.created_at) || `#${i + 1}`}
                      </Tabs.Tab>
                    );
                  })}
                </Tabs.List>
              )}
              {suggestions.map((raw) => {
                const item = getItem(raw);
                const id = item.id;
                const isNewCorr = item.correspondent ? !corrNames.has(item.correspondent.toLowerCase()) : false;
                const isNewDt = item.document_type ? !dtNames.has(item.document_type.toLowerCase()) : false;
                const cfEntries = Object.entries(item.custom_fields ?? {});
                const isNewCf = (name: string) => !cfNames.has(name.toLowerCase());
                const currentTags = existingTagsMap[item.document_id] ?? [];
                const suggestedTags = item.tags;
                const overrides = tagOverrides[id] ?? {};
                const isReanalyzing = reanalyzingIds.has(id);
                return (
                  <Tabs.Panel key={id} value={id}>
                    {/* Per-suggestion actions */}
                    <Group gap="xs" mb="sm" wrap="wrap">
                      <Text size="xs" c="dimmed">{String(raw.llm_provider ?? "")} · {String(raw.llm_model ?? "")} · {fmtDateTime(raw.created_at)}</Text>
                      <Box style={{ flex: 1 }} />
                      <Button size="xs" variant="default" onClick={() => handleReanalyze(id)} loading={isReanalyzing}>
                        {t("queue.reanalyze")}
                      </Button>
                      {Boolean(raw.extracted_content) && (
                        <Button size="xs" variant="default" onClick={() => setContentView({ extracted: (raw.extracted_content as string) ?? null, original: (raw.original_ocr_content as string) ?? null })}>
                          {t("vision.viewContent")}
                        </Button>
                      )}
                      <VisionAnalysisFlow
                        documentId={item.document_id}
                        pageWarningThreshold={pageWarningThreshold}
                        onResult={result => handleVisionResult(raw, result)}
                        size="xs"
                      />
                    </Group>

            {/* Edit form */}
            <Stack gap="xs">
              <TextInput
                label="Title"
                size="xs"
                value={item.title ?? ""}
                onChange={e => updateField(id, raw, "title", e.target.value || null)}
              />

              <Box>
                <Text size="xs" fw={600} c="dimmed" mb={4}>Tags</Text>
                <Group gap={4} mb={4}>
                  {(() => {
                    // Build unified set: current ∪ suggested ∪ user-added (override=true)
                    const allTagNames = new Set([...currentTags, ...suggestedTags]);
                    for (const [tag, include] of Object.entries(overrides)) {
                      if (include) allTagNames.add(tag);
                    }
                    return [...allTagNames].flatMap(tag => {
                      const inCurrent = currentTags.includes(tag);
                      const inSuggested = suggestedTags.includes(tag);
                      const override = overrides[tag];
                      // Default: keep tag if LLM included it in suggested set
                      const effectiveInclude = override !== undefined ? override : inSuggested;

                      // Green suggestion the user removed → hide entirely
                      if (!effectiveInclude && !inCurrent) return [];

                      // Color and style based on final state
                      let color: string;
                      let extraStyle: React.CSSProperties = {};
                      if (effectiveInclude && inCurrent) {
                        color = "gray";  // unchanged — currently there, LLM keeps it
                      } else if (effectiveInclude) {
                        color = "teal";  // to be added — not currently there
                      } else {
                        color = "gray";  // to be removed — currently there, LLM drops it
                        extraStyle = { textDecoration: "line-through", opacity: 0.55 };
                      }

                      return [(
                        <Badge
                          key={tag}
                          color={color}
                          variant="light"
                          size="sm"
                          style={{ cursor: "pointer", ...extraStyle }}
                          onClick={() => {
                            const newInclude = !effectiveInclude;
                            setTagOverrides(prev => {
                              const prevItem = { ...(prev[id] ?? {}) };
                              // If toggling back to the natural default, remove the override
                              if (newInclude === inSuggested) {
                                delete prevItem[tag];
                              } else {
                                prevItem[tag] = newInclude;
                              }
                              return { ...prev, [id]: prevItem };
                            });
                          }}
                        >
                          {tag}
                        </Badge>
                      )];
                    });
                  })()}
                </Group>
                <TagInput
                  allTags={(tagsQ.data ?? []).map((t: PaperlessEntity) => t.name)}
                  placeholder={t("analysis.addTag")}
                  onAdd={tag => {
                    setTagOverrides(prev => ({
                      ...prev,
                      [id]: { ...(prev[id] ?? {}), [tag]: true },
                    }));
                  }}
                />
              </Box>

              <Box>
                <Text size="xs" fw={600} c="dimmed" mb={4}>{t("analysis.correspondent")}</Text>
                <AutocompleteInput value={item.correspondent ?? ""} suggestions={(corrsQ.data ?? []).map((c: PaperlessEntity) => c.name)}
                  onChange={v => updateField(id, raw, "correspondent", v || null)}
                  style={isNewCorr ? { color: "var(--mantine-color-red-6)", fontWeight: 700 } : undefined} />
                {isNewCorr && <Text size="xs" c="red" mt={2}>{t("analysis.newHint")}</Text>}
              </Box>

              <Box>
                <Text size="xs" fw={600} c="dimmed" mb={4}>{t("analysis.docType")}</Text>
                <AutocompleteInput value={item.document_type ?? ""} suggestions={(dtQ.data ?? []).map((d: PaperlessEntity) => d.name)}
                  onChange={v => updateField(id, raw, "document_type", v || null)}
                  style={isNewDt ? { color: "var(--mantine-color-red-6)", fontWeight: 700 } : undefined} />
                {isNewDt && <Text size="xs" c="red" mt={2}>{t("analysis.newHint")}</Text>}
              </Box>

              <Box>
                <Text size="xs" fw={600} c="dimmed" mb={4}>{t("analysis.storagePath_field")}</Text>
                <AutocompleteInput value={item.storage_path ?? ""} suggestions={(spQ.data ?? []).map((s: PaperlessEntity) => s.name)}
                  onChange={v => updateField(id, raw, "storage_path", v || null)} />
              </Box>

              {cfEntries.length > 0 && (
                <Box>
                  <Text size="xs" fw={600} c="dimmed" mb={4}>{t("analysis.customFields")}</Text>
                  {cfEntries.map(([key, val]) => (
                    <CfNameEditor key={key} name={key} value={val} isNew={isNewCf(key)}
                      suggestions={(cfQ.data ?? []).map((c: PaperlessCustomField) => c.name)}
                      onRename={newName => { if (!newName || newName === key) return; const cf = { ...item.custom_fields }; const v = cf[key]; delete cf[key]; cf[newName] = v; updateField(id, raw, "custom_fields", cf); }}
                      onChangeValue={v => updateField(id, raw, "custom_fields", { ...item.custom_fields, [key]: v || null })}
                      onRemove={() => { const cf = { ...item.custom_fields }; delete cf[key]; updateField(id, raw, "custom_fields", cf); }} />
                  ))}
                </Box>
              )}
            </Stack>

            {/* Approve / Reject */}
            <Box mt="md">
              {Boolean(raw.extracted_content) && (
                <Switch
                  size="sm"
                  mb="xs"
                  checked={contentApply[id] ?? true}
                  onChange={e => setContentApply(prev => ({ ...prev, [id]: e.currentTarget.checked }))}
                  label={t("queue.applyContent")}
                />
              )}
              <Group gap="xs">
                <Button size="sm"
                  onClick={() => approve.mutate({ id, item, docId: item.document_id })}
                  loading={approve.isPending && approve.variables?.id === id}>
                  {t("common.approve")}
                </Button>
                <Button size="sm" variant="default"
                  onClick={() => reject.mutate(id)}
                  loading={reject.isPending && reject.variables === id}>
                  {t("common.reject")}
                </Button>
              </Group>
              {approve.isError && approve.variables?.id === id && (
                <Text size="xs" c="red" mt="xs">
                  {t("common.approvalFailed")} {(approve.error as Error).message}
                </Text>
              )}
            </Box>
                  </Tabs.Panel>
                );
              })}
            </Tabs>
          </Paper>
        );
      })}

      <ContentDiffModal
        opened={contentView !== null}
        onClose={() => setContentView(null)}
        originalOcr={contentView?.original}
        extracted={contentView?.extracted}
        footer={
          <Button size="sm" variant="default" onClick={() => setContentView(null)}>
            {t("common.close")}
          </Button>
        }
      />
    </Stack>
  );
}
