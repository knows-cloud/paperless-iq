import React, { useState, useMemo, useEffect, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Title, Paper, Text, Group, Stack, Badge, Button, TextInput,
  Box, Alert, Anchor, Loader, Switch, Tabs,
} from "@mantine/core";
import { api, type PaperlessEntity, type PaperlessCustomField, type VisionAnalysisResult, type GroomingEvidence, type GroomingEvidenceAction } from "../api";
import TagInput from "../TagInput";
import AutocompleteInput from "../AutocompleteInput";
import CfNameEditor from "../CfNameEditor";
import VisionAnalysisFlow from "../VisionAnalysisFlow";
import { ContentDiffModal } from "../components/ContentDiffModal";
import { useTranslation } from "react-i18next";

// Fields compared to collapse identical suggestions and flag what differs.
const COMPARE_FIELDS = ["title", "tags", "correspondent", "document_type", "storage_path", "custom_fields"] as const;

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

function parseEvidence(raw: Record<string, unknown>): GroomingEvidence | null {
  if (raw.analysis_mode !== "grooming" || !raw.evidence_json) return null;
  try {
    return JSON.parse(String(raw.evidence_json)) as GroomingEvidence;
  } catch {
    return null;
  }
}

// All-adds grooming suggestions can't clobber: the card defaults the document's
// current tags to included, so tags gained after the scan survive approval.
function isAddOnly(evidence: GroomingEvidence | null): boolean {
  return evidence !== null
    && evidence.actions.length > 0
    && evidence.actions.every(a => a.action === "add");
}

const EVIDENCE_ICONS: Record<string, string> = { add: "＋", remove: "−", replace: "⇄", review: "?" };
const EVIDENCE_COLORS: Record<string, string> = { add: "teal", remove: "red", replace: "blue", review: "yellow" };

function EvidenceRow({ action }: { action: GroomingEvidenceAction }) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const passage = action.best_passage || "";
  const truncated = passage.length > 150 && !expanded;
  return (
    <Group gap="xs" align="flex-start" wrap="nowrap">
      <Badge size="sm" variant="light" color={EVIDENCE_COLORS[action.action] ?? "gray"} style={{ flexShrink: 0 }}>
        {EVIDENCE_ICONS[action.action] ?? "·"} {action.entity_name}
        {action.action === "replace" && action.replacement_entity_name ? ` → ${action.replacement_entity_name}` : ""}
      </Badge>
      {action.action === "review" && (
        <Badge size="sm" variant="filled" color="yellow" style={{ flexShrink: 0 }}>
          {t("queue.needsDecision")}
        </Badge>
      )}
      <Text size="xs" c="dimmed" style={{ minWidth: 0 }}>
        {t("queue.evidenceSimilarity", { score: action.score.toFixed(2) })}
        {action.cohort_percentile !== null && action.cohort_percentile !== undefined
          ? ` · ${t("queue.evidencePercentile", { pct: action.cohort_percentile })}`
          : ""}
        {passage && (
          <>
            {" · "}
            <Text span size="xs" fs="italic">
              "{truncated ? passage.slice(0, 150) + "…" : passage}"
            </Text>
            {passage.length > 150 && (
              <Anchor size="xs" ml={4} onClick={() => setExpanded(e => !e)}>
                {expanded ? t("queue.evidenceLess") : t("queue.evidenceMore")}
              </Anchor>
            )}
          </>
        )}
      </Text>
    </Group>
  );
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
  // Shared query key → react-query dedupes across all document cards (one network call).
  const visionSupportQ = useQuery({ queryKey: ["ollamaVisionSupport"], queryFn: api.getOllamaVisionSupport, staleTime: 5 * 60_000, retry: false });
  const ollamaVisionWarning = visionSupportQ.data?.supported === false;

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
  // suggestion. Within a group: chronological (oldest → newest, newest selected
  // by default); identical suggestions are collapsed into one tab (keeping the
  // newest, with a ×N count); the fields that differ across the distinct
  // suggestions are flagged so the user can spot what actually changed.
  const groups = useMemo(() => {
    const fieldVal = (raw: Record<string, unknown>, f: string): string => {
      if (f === "tags") return JSON.stringify([...((raw.tags as string[]) ?? [])].sort());
      if (f === "custom_fields") return JSON.stringify(raw.custom_fields ?? {});
      return JSON.stringify((raw[f] as unknown) ?? null);
    };
    const contentKey = (raw: Record<string, unknown>) => COMPARE_FIELDS.map(f => fieldVal(raw, f)).join("|");

    const byDoc = new Map<number, Array<Record<string, unknown>>>();
    for (const raw of items) {
      const docId = Number(raw.document_id);
      const arr = byDoc.get(docId);
      if (arr) arr.push(raw); else byDoc.set(docId, [raw]);
    }

    return [...byDoc.entries()].map(([documentId, rawList]) => {
      const sorted = rawList.slice().sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)));
      // Collapse identical suggestions, keeping the newest of each cluster.
      const clusters = new Map<string, Array<Record<string, unknown>>>();
      for (const raw of sorted) {
        const k = contentKey(raw);
        const arr = clusters.get(k);
        if (arr) arr.push(raw); else clusters.set(k, [raw]);
      }
      const suggestions = [...clusters.values()]
        .map(arr => arr[arr.length - 1])
        .sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)));
      const dupCounts: Record<string, number> = {};
      for (const arr of clusters.values()) dupCounts[String(arr[arr.length - 1].id)] = arr.length;
      const varyingFields = new Set<string>();
      if (suggestions.length > 1) {
        for (const f of COMPARE_FIELDS) {
          if (new Set(suggestions.map(raw => fieldVal(raw, f))).size > 1) varyingFields.add(f);
        }
      }
      return { documentId, suggestions, dupCounts, varyingFields };
    });
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
    mutationFn: ({ id, item, docId, includeCurrentByDefault }: { id: string; item: QueueItem; docId: number; includeCurrentByDefault?: boolean }) => {
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
        const inCurrent = currentTags.includes(tag);
        const override = overrides[tag];
        // Default: keep if LLM included it; override takes precedence.
        // Add-only grooming suggestions also keep current tags by default —
        // the scan only adds, so nothing the user applied meanwhile is dropped.
        const shouldInclude = override !== undefined
          ? override
          : inSuggested || (Boolean(includeCurrentByDefault) && inCurrent);
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
        const dupCounts = group.dupCounts;
        const varyingFields = group.varyingFields;
        const headerRaw = suggestions[0];
        const fieldLabels: Record<string, string> = {
          title: t("common.title"),
          tags: t("analysis.tags_field"),
          correspondent: t("analysis.correspondent"),
          document_type: t("analysis.docType"),
          storage_path: t("analysis.storagePath_field"),
          custom_fields: t("analysis.customFields"),
        };
        // Marker appended to a field's label when that field differs across the
        // document's distinct suggestions.
        const varyMark = (f: string) =>
          varyingFields.has(f)
            ? <Badge size="xs" color="yellow" variant="light" ml={6} title={t("queue.variesIn")}>≠</Badge>
            : null;
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
                    const dup = dupCounts[String(raw.id)] ?? 1;
                    return (
                      <Tabs.Tab
                        key={String(raw.id)}
                        value={String(raw.id)}
                        rightSection={isNewest ? (
                          <Badge size="xs" variant="light" color="teal">{t("queue.newest")}</Badge>
                        ) : undefined}
                      >
                        {(fmtDateTime(raw.created_at) || `#${i + 1}`) + (dup > 1 ? ` ×${dup}` : "")}
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
                const evidence = parseEvidence(raw);
                const groomingAddOnly = isAddOnly(evidence);
                return (
                  <Tabs.Panel key={id} value={id}>
                    {/* Per-suggestion actions */}
                    <Group gap="xs" mb="sm" wrap="wrap">
                      <Text size="xs" c="dimmed">
                        {evidence
                          ? `${t("queue.groomingProvenance")} · ${fmtDateTime(evidence.scanned_at)}`
                          : `${String(raw.llm_provider ?? "")} · ${String(raw.llm_model ?? "")} · ${fmtDateTime(raw.created_at)}`}
                      </Text>
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
                        ollamaVisionWarning={ollamaVisionWarning}
                        onResult={result => handleVisionResult(raw, result)}
                        size="xs"
                      />
                    </Group>

                    {varyingFields.size > 0 && (
                      <Text size="xs" c="dimmed" mb="xs">
                        {t("queue.variesIn")}: {[...varyingFields].map(f => fieldLabels[f]).join(", ")}
                      </Text>
                    )}

                    {/* Grooming scan evidence */}
                    {evidence && evidence.actions.length > 0 && (
                      <Paper withBorder p="xs" radius="sm" mb="sm" bg="var(--mantine-color-default-hover)">
                        <Text size="xs" fw={600} c="dimmed" mb={6}>{t("queue.groomingEvidence")}</Text>
                        <Stack gap={6}>
                          {evidence.actions.map((a, i) => <EvidenceRow key={i} action={a} />)}
                        </Stack>
                      </Paper>
                    )}

            {/* Edit form */}
            <Stack gap="xs">
              <TextInput
                label={<>Title {varyMark("title")}</>}
                size="xs"
                value={item.title ?? ""}
                onChange={e => updateField(id, raw, "title", e.target.value || null)}
              />

              <Box>
                <Text size="xs" fw={600} c="dimmed" mb={4}>Tags {varyMark("tags")}</Text>
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
                      // Default: keep tag if LLM included it in suggested set.
                      // Add-only grooming suggestions also keep current tags.
                      const effectiveInclude = override !== undefined
                        ? override
                        : inSuggested || (groomingAddOnly && inCurrent);

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
                            const naturalDefault = inSuggested || (groomingAddOnly && inCurrent);
                            setTagOverrides(prev => {
                              const prevItem = { ...(prev[id] ?? {}) };
                              // If toggling back to the natural default, remove the override
                              if (newInclude === naturalDefault) {
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
                <Text size="xs" fw={600} c="dimmed" mb={4}>{t("analysis.correspondent")} {varyMark("correspondent")}</Text>
                <AutocompleteInput value={item.correspondent ?? ""} suggestions={(corrsQ.data ?? []).map((c: PaperlessEntity) => c.name)}
                  onChange={v => updateField(id, raw, "correspondent", v || null)}
                  style={isNewCorr ? { color: "var(--mantine-color-red-6)", fontWeight: 700 } : undefined} />
                {isNewCorr && <Text size="xs" c="red" mt={2}>{t("analysis.newHint")}</Text>}
              </Box>

              <Box>
                <Text size="xs" fw={600} c="dimmed" mb={4}>{t("analysis.docType")} {varyMark("document_type")}</Text>
                <AutocompleteInput value={item.document_type ?? ""} suggestions={(dtQ.data ?? []).map((d: PaperlessEntity) => d.name)}
                  onChange={v => updateField(id, raw, "document_type", v || null)}
                  style={isNewDt ? { color: "var(--mantine-color-red-6)", fontWeight: 700 } : undefined} />
                {isNewDt && <Text size="xs" c="red" mt={2}>{t("analysis.newHint")}</Text>}
              </Box>

              <Box>
                <Text size="xs" fw={600} c="dimmed" mb={4}>{t("analysis.storagePath_field")} {varyMark("storage_path")}</Text>
                <AutocompleteInput value={item.storage_path ?? ""} suggestions={(spQ.data ?? []).map((s: PaperlessEntity) => s.name)}
                  onChange={v => updateField(id, raw, "storage_path", v || null)} />
              </Box>

              {cfEntries.length > 0 && (
                <Box>
                  <Text size="xs" fw={600} c="dimmed" mb={4}>{t("analysis.customFields")} {varyMark("custom_fields")}</Text>
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
                  onClick={() => approve.mutate({ id, item, docId: item.document_id, includeCurrentByDefault: groomingAddOnly })}
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
