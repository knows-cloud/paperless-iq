import { useState, useEffect, useRef } from "react";
import {
  Title, Stack, Tabs, SegmentedControl, Select, Textarea, Button, Group,
  Text, Paper, Badge, Switch, Alert, Progress, Loader, Center,
  Modal, Checkbox, Radio, Divider, MultiSelect, Table, Anchor,
} from "@mantine/core";
import { useTranslation } from "react-i18next";
import {
  api, type GroomingEntity, type DedupCluster, type GenerateStatus,
  type ScanCandidate, type ScanStatus,
} from "../api";
import { GROOMING_ENTITY_TYPES } from "./settings/constants";

type EntityType = "tag" | "correspondent" | "document_type";

function formatDate(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleDateString();
}

// ── Descriptions Tab ───────────────────────────────────────────────────────

function DescriptionsTab({ entityType }: { entityType: EntityType }) {
  const { t } = useTranslation();
  const [entities, setEntities] = useState<GroomingEntity[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [descText, setDescText] = useState("");
  const [saving, setSaving] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [overwrite, setOverwrite] = useState(false);
  const [bulkConfirm, setBulkConfirm] = useState(false);
  const [bulkCount, setBulkCount] = useState(0);
  const [genStatus, setGenStatus] = useState<GenerateStatus | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const [msg, setMsg] = useState("");

  const selected = entities.find(e => e.entity_id === selectedId) ?? null;

  useEffect(() => {
    setLoading(true);
    setSelectedId(null);
    setDescText("");
    api.groomingListEntities(entityType)
      .then(setEntities)
      .catch(err => setMsg(t("grooming.error", { msg: err.message })))
      .finally(() => setLoading(false));
    // `t` is deliberately omitted: it changes identity on language switch, and
    // re-running this effect would clear the selection and any unsaved edit
    // just because the user changed language. `t` is only read in the error
    // path, where a stale translator is harmless.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entityType]);

  // null = nothing selected; "" = selected but no description yet.
  const selectedDescription = selected ? (selected.description ?? "") : null;

  // Depends on the description *string*, not `selected`: generation finishing
  // swaps `entities` without changing `selectedId`, which previously left the
  // editor showing pre-generation text. Keying on the string also means an
  // unrelated refresh of `entities` won't clobber an unsaved edit.
  useEffect(() => {
    if (selectedDescription === null) return;
    setDescText(selectedDescription);
  }, [selectedId, selectedDescription]);

  // Poll generation status while running
  useEffect(() => {
    if (genStatus?.running) {
      pollRef.current = setInterval(async () => {
        try {
          const s = await api.groomingGenerateStatus();
          setGenStatus(s);
          if (!s.running) {
            clearInterval(pollRef.current!);
            // Reload entities to show updated descriptions
            const updated = await api.groomingListEntities(entityType);
            setEntities(updated);
          }
        } catch { /* ignore */ }
      }, 2000);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [genStatus?.running, entityType]);

  async function handleSave() {
    if (!selected) return;
    setSaving(true);
    setMsg("");
    try {
      const updated = await api.groomingPatchEntity(entityType, selected.entity_id, { description: descText || null });
      setEntities(prev => prev.map(e => e.entity_id === updated.entity_id ? { ...e, ...updated } : e));
      setMsg(t("settings.saved"));
    } catch (err: unknown) {
      setMsg(t("grooming.error", { msg: (err as Error).message }));
    } finally {
      setSaving(false);
    }
  }

  async function handleGenerate() {
    if (!selected) return;
    setGenerating(true);
    setMsg("");
    try {
      const r = await api.groomingGenerate({ entity_type: entityType, entity_id: selected.entity_id });
      if (r.description) {
        setDescText(r.description);
        const updated = await api.groomingListEntities(entityType);
        setEntities(updated);
      }
    } catch (err: unknown) {
      setMsg(t("grooming.error", { msg: (err as Error).message }));
    } finally {
      setGenerating(false);
    }
  }

  async function handleGenerateAll() {
    try {
      const r = await api.groomingGenerate({ entity_type: entityType, overwrite });
      setBulkCount(r.count ?? 0);
      setGenStatus({ running: true, done: 0, total: r.count ?? 0, current_entity: "", cancelled: false });
      setBulkConfirm(false);
    } catch (err: unknown) {
      setMsg(t("grooming.error", { msg: (err as Error).message }));
    }
  }

  async function handleCancel() {
    await api.groomingGenerateCancel();
  }

  async function handleExcludeToggle(excluded: boolean) {
    if (!selected) return;
    const updated = await api.groomingPatchEntity(entityType, selected.entity_id, { excluded });
    setEntities(prev => prev.map(e => e.entity_id === updated.entity_id ? { ...e, ...updated } : e));
  }

  const selectData = entities.map(e => ({
    value: String(e.entity_id),
    label: e.name,
    disabled: false,
  }));

  return (
    <Stack gap="md">
      {msg && <Alert color={msg.startsWith("Error") ? "red" : "teal"} withCloseButton onClose={() => setMsg("")}>{msg}</Alert>}

      {loading ? (
        <Center h={120}><Loader /></Center>
      ) : (
        <>
          <Select
            placeholder={t("grooming.descriptions.selectPlaceholder")}
            data={selectData}
            value={selectedId !== null ? String(selectedId) : null}
            onChange={v => setSelectedId(v ? Number(v) : null)}
            searchable
            renderOption={({ option }) => {
              const entity = entities.find(e => String(e.entity_id) === option.value);
              return (
                <Group justify="space-between" w="100%">
                  <Text fw={entity?.description ? 700 : 400} fs={entity?.description ? undefined : "italic"}>
                    {option.label}
                  </Text>
                  {entity && (
                    <Text size="xs" c="dimmed">{entity.doc_count}</Text>
                  )}
                </Group>
              );
            }}
          />

          {selected && (
            <Stack gap="sm">
              <Textarea
                autosize
                minRows={3}
                maxRows={8}
                value={descText}
                onChange={e => setDescText(e.currentTarget.value)}
                placeholder={t("grooming.descriptions.noDescription")}
              />
              {selected.description_updated_at && (
                <Text size="xs" c="dimmed">
                  {selected.description_source === "llm"
                    ? t("grooming.descriptions.source.llm", { date: formatDate(selected.description_updated_at) })
                    : t("grooming.descriptions.source.user", { date: formatDate(selected.description_updated_at) })}
                </Text>
              )}
              <Group>
                <Button size="xs" loading={saving} onClick={handleSave}>
                  {t("grooming.descriptions.save")}
                </Button>
                <Button size="xs" variant="light" loading={generating} onClick={handleGenerate}>
                  {generating ? t("grooming.descriptions.generating") : t("grooming.descriptions.generate")}
                </Button>
              </Group>
              <Switch
                label={t("grooming.descriptions.excludeToggle")}
                checked={selected.excluded}
                disabled={selected.forced_excluded}
                onChange={e => handleExcludeToggle(e.currentTarget.checked)}
              />
              {selected.forced_excluded && (
                <Text size="xs" c="dimmed">{t("grooming.descriptions.excludeInboxTip")}</Text>
              )}
            </Stack>
          )}

          <Divider />

          {genStatus?.running ? (
            <Stack gap="xs">
              <Progress value={genStatus.total > 0 ? (genStatus.done / genStatus.total) * 100 : 0} animated />
              <Text size="sm" c="dimmed">
                {t("grooming.descriptions.progress", { done: genStatus.done, total: genStatus.total, entity: genStatus.current_entity })}
              </Text>
              <Button size="xs" color="red" variant="light" onClick={handleCancel}>
                {t("grooming.descriptions.cancel")}
              </Button>
            </Stack>
          ) : (
            <Group align="flex-end">
              <Button size="xs" variant="default" onClick={async () => {
                setBulkCount(entities.filter(e => overwrite || !e.description).length);
                setBulkConfirm(true);
              }}>
                {t("grooming.descriptions.generateAll")}
              </Button>
              <Checkbox
                size="xs"
                label={t("grooming.descriptions.overwrite")}
                checked={overwrite}
                onChange={e => setOverwrite(e.currentTarget.checked)}
              />
            </Group>
          )}

          <Modal
            opened={bulkConfirm}
            onClose={() => setBulkConfirm(false)}
            title={t("grooming.descriptions.generateAll")}
          >
            <Text mb="md">{t("grooming.descriptions.bulkConfirm", { count: bulkCount })}</Text>
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setBulkConfirm(false)}>
                {t("grooming.descriptions.cancel")}
              </Button>
              <Button onClick={handleGenerateAll}>
                {t("grooming.descriptions.bulkStart")}
              </Button>
            </Group>
          </Modal>
        </>
      )}
    </Stack>
  );
}

// ── Deduplicate Tab ────────────────────────────────────────────────────────

function DedupTab({ entityType }: { entityType: EntityType }) {
  const { t } = useTranslation();
  const [clusters, setClusters] = useState<DedupCluster[]>([]);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState("");

  // Per-cluster state: selected canonical id, checked remove ids
  const [canonicalMap, setCanonicalMap] = useState<Record<number, number>>({});
  const [removeMap, setRemoveMap] = useState<Record<number, Set<number>>>({});

  // Merge confirm modal
  const [mergeClusterIdx, setMergeClusterIdx] = useState<number | null>(null);
  const [merging, setMerging] = useState(false);

  async function handleFind() {
    setLoading(true);
    setMsg("");
    setClusters([]);
    setCanonicalMap({});
    setRemoveMap({});
    try {
      const result = await api.groomingDedupCandidates(entityType);
      setClusters(result);
      const cm: Record<number, number> = {};
      const rm: Record<number, Set<number>> = {};
      result.forEach((cluster, idx) => {
        // Preselect first entity as canonical
        cm[idx] = cluster.entities[0]?.entity_id ?? 0;
        rm[idx] = new Set();
      });
      setCanonicalMap(cm);
      setRemoveMap(rm);
    } catch (err: unknown) {
      setMsg(t("grooming.error", { msg: (err as Error).message }));
    } finally {
      setLoading(false);
    }
  }

  async function handleDismiss(clusterIdx: number) {
    const cluster = clusters[clusterIdx];
    const ids = cluster.entities.map(e => e.entity_id);
    try {
      for (let i = 0; i < ids.length; i++) {
        for (let j = i + 1; j < ids.length; j++) {
          await api.groomingDedupDismiss(entityType, ids[i], ids[j]);
        }
      }
      setClusters(prev => prev.filter((_, i) => i !== clusterIdx));
    } catch (err: unknown) {
      setMsg(t("grooming.error", { msg: (err as Error).message }));
    }
  }

  async function handleMerge() {
    if (mergeClusterIdx === null) return;
    const keepId = canonicalMap[mergeClusterIdx];
    const removeIds = Array.from(removeMap[mergeClusterIdx] ?? []);
    if (!keepId || removeIds.length === 0) return;
    setMerging(true);
    try {
      const result = await api.groomingMerge(entityType, keepId, removeIds);
      setMsg(t("grooming.dedup.mergeDone", { docs: result.documents_updated }));
      setClusters(prev => prev.filter((_, i) => i !== mergeClusterIdx));
      setMergeClusterIdx(null);
    } catch (err: unknown) {
      setMsg(t("grooming.error", { msg: (err as Error).message }));
    } finally {
      setMerging(false);
    }
  }

  const mergeCluster = mergeClusterIdx !== null ? clusters[mergeClusterIdx] : null;
  const mergeKeepName = mergeCluster?.entities.find(e => e.entity_id === canonicalMap[mergeClusterIdx!])?.name ?? "";
  const mergeRemoveCount = removeMap[mergeClusterIdx ?? -1]?.size ?? 0;

  return (
    <Stack gap="md">
      {msg && <Alert color={msg.startsWith("Error") ? "red" : "teal"} withCloseButton onClose={() => setMsg("")}>{msg}</Alert>}

      <Button onClick={handleFind} loading={loading}>
        {loading ? t("grooming.dedup.finding") : t("grooming.dedup.findBtn")}
      </Button>

      {!loading && clusters.length === 0 && msg === "" && (
        <Text c="dimmed" size="sm">{t("grooming.dedup.empty")}</Text>
      )}

      {clusters.map((cluster, idx) => (
        <Paper key={idx} withBorder p="md" radius="md">
          <Stack gap="xs">
            <Group justify="space-between">
              <Badge variant="light" color={cluster.signal === "embedding" ? "violet" : "blue"}>
                {t(`grooming.dedup.signal.${cluster.signal}`)} {(cluster.similarity * 100).toFixed(0)}%
              </Badge>
              <Group gap="xs">
                <Button
                  size="xs"
                  disabled={(removeMap[idx]?.size ?? 0) === 0}
                  onClick={() => setMergeClusterIdx(idx)}
                >
                  {t("grooming.dedup.mergeBtn")}
                </Button>
                <Button size="xs" variant="subtle" color="gray" onClick={() => handleDismiss(idx)}>
                  {t("grooming.dedup.dismissBtn")}
                </Button>
              </Group>
            </Group>

            {cluster.entities.map(entity => (
              <Group key={entity.entity_id} gap="sm" align="center">
                <Radio
                  value={String(entity.entity_id)}
                  checked={canonicalMap[idx] === entity.entity_id}
                  onChange={() => {
                    setCanonicalMap(prev => ({ ...prev, [idx]: entity.entity_id }));
                    // Uncheck from remove if now canonical
                    setRemoveMap(prev => {
                      const next = new Set(prev[idx]);
                      next.delete(entity.entity_id);
                      return { ...prev, [idx]: next };
                    });
                  }}
                  label={<Text size="sm" c="dimmed">{t("grooming.dedup.canonical")}</Text>}
                />
                <Checkbox
                  checked={removeMap[idx]?.has(entity.entity_id) ?? false}
                  disabled={canonicalMap[idx] === entity.entity_id}
                  onChange={e => {
                    const checked = e.currentTarget.checked;
                    setRemoveMap(prev => {
                      const next = new Set(prev[idx]);
                      if (checked) next.add(entity.entity_id);
                      else next.delete(entity.entity_id);
                      return { ...prev, [idx]: next };
                    });
                  }}
                  label={<Text size="sm" c="dimmed">{t("grooming.dedup.remove")}</Text>}
                />
                <Text fw={500}>{entity.name}</Text>
                {entity.has_description && <Badge size="xs" variant="dot" color="teal">desc</Badge>}
                {entity.embedding_stored && <Badge size="xs" variant="dot" color="violet">emb</Badge>}
              </Group>
            ))}
          </Stack>
        </Paper>
      ))}

      <Modal
        opened={mergeClusterIdx !== null}
        onClose={() => setMergeClusterIdx(null)}
        title={t("grooming.dedup.mergeConfirmTitle", { name: mergeKeepName })}
      >
        <Text size="sm" mb="md">{t("grooming.dedup.mergeConfirmBody", { docs: "?" })}</Text>
        <Group justify="flex-end">
          <Button variant="default" onClick={() => setMergeClusterIdx(null)}>
            {t("grooming.descriptions.cancel")}
          </Button>
          <Button color="red" loading={merging} onClick={handleMerge}>
            {t("grooming.dedup.mergeConfirmBtn", { count: mergeRemoveCount, name: mergeKeepName })}
          </Button>
        </Group>
      </Modal>
    </Stack>
  );
}

// ── Scan Tab ───────────────────────────────────────────────────────────────

const ACTION_COLORS: Record<string, string> = {
  add: "teal", remove: "red", replace: "blue", review: "yellow",
};

function ScanTab() {
  const { t } = useTranslation();
  const [selectedTypes, setSelectedTypes] = useState<string[]>(
    GROOMING_ENTITY_TYPES.map(et => et.value),
  );
  const [scanStatus, setScanStatus] = useState<ScanStatus | null>(null);
  const [candidates, setCandidates] = useState<ScanCandidate[] | null>(null);
  const [dryRunning, setDryRunning] = useState(false);
  const [starting, setStarting] = useState(false);
  const [msg, setMsg] = useState("");
  const [sortBy, setSortBy] = useState<"score" | "action" | "entity_name">("score");
  const [sortDesc, setSortDesc] = useState(true);
  const [vectorBackend, setVectorBackend] = useState("local");
  const [embedOnline, setEmbedOnline] = useState(true);
  const [embeddedEntities, setEmbeddedEntities] = useState<{ n: number; m: number } | null>(null);
  const [indexedDocs, setIndexedDocs] = useState<number | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    api.groomingScanStatus().then(setScanStatus).catch(() => {});
    api.getSettings().then(s => setVectorBackend(String((s as Record<string, unknown>).vector_store_backend ?? "local"))).catch(() => {});
    api.getStatus().then(s => {
      setEmbedOnline(s.embed_online);
      setIndexedDocs(s.total_documents);
    }).catch(() => {});
    Promise.all(GROOMING_ENTITY_TYPES.map(et => api.groomingListEntities(et.value).catch(() => [] as GroomingEntity[])))
      .then(lists => {
        const all = lists.flat().filter(e => !e.excluded);
        setEmbeddedEntities({ n: all.filter(e => e.embedding_stored).length, m: all.length });
      });
  }, []);

  // Poll scan status every 2 s while running
  useEffect(() => {
    if (scanStatus?.running) {
      pollRef.current = setInterval(async () => {
        try {
          const s = await api.groomingScanStatus();
          setScanStatus(s);
          if (!s.running && pollRef.current) clearInterval(pollRef.current);
        } catch { /* ignore */ }
      }, 2000);
    }
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [scanStatus?.running]);

  async function handleDryRun() {
    setDryRunning(true);
    setMsg("");
    setCandidates(null);
    try {
      const r = await api.groomingScan({ entity_types: selectedTypes, dry_run: true });
      setCandidates(r.candidates ?? []);
    } catch (err: unknown) {
      setMsg(t("grooming.error", { msg: (err as Error).message }));
    } finally {
      setDryRunning(false);
    }
  }

  async function handleScanNow() {
    setStarting(true);
    setMsg("");
    try {
      await api.groomingScan({ entity_types: selectedTypes, dry_run: false });
      setMsg(t("grooming.scan.started"));
      const s = await api.groomingScanStatus();
      setScanStatus(s);
    } catch (err: unknown) {
      setMsg(t("grooming.error", { msg: (err as Error).message }));
    } finally {
      setStarting(false);
    }
  }

  const disabledReason =
    vectorBackend === "bedrock_kb" ? t("grooming.scan.disabled.bedrock")
    : !embedOnline ? t("grooming.scan.disabled.embedDown")
    : embeddedEntities !== null && embeddedEntities.n === 0 ? t("grooming.scan.disabled.noEmbeddings")
    : null;

  const summary = scanStatus?.last_summary;

  const sortedCandidates = (candidates ?? []).slice().sort((a, b) => {
    const av = a[sortBy]; const bv = b[sortBy];
    const cmp = typeof av === "number" && typeof bv === "number"
      ? av - bv
      : String(av).localeCompare(String(bv));
    return sortDesc ? -cmp : cmp;
  });

  const sortHeader = (key: typeof sortBy, label: string) => (
    <Table.Th
      style={{ cursor: "pointer", userSelect: "none" }}
      onClick={() => {
        if (sortBy === key) setSortDesc(d => !d);
        else { setSortBy(key); setSortDesc(true); }
      }}
    >
      {label}{sortBy === key ? (sortDesc ? " ↓" : " ↑") : ""}
    </Table.Th>
  );

  return (
    <Stack gap="md">
      {msg && <Alert color={msg.startsWith("Error") ? "red" : "teal"} withCloseButton onClose={() => setMsg("")}>{msg}</Alert>}

      {disabledReason && <Alert color="yellow" variant="light">{disabledReason}</Alert>}

      {/* Status card */}
      <Paper withBorder p="md" radius="md">
        <Text fw={600} mb="xs">{t("grooming.scan.statusTitle")}</Text>
        {scanStatus?.last_run_at ? (
          <Text size="sm" c="dimmed">
            {t("grooming.scan.lastRun", { date: new Date(scanStatus.last_run_at).toLocaleString() })}
          </Text>
        ) : (
          <Text size="sm" c="dimmed">{t("grooming.scan.neverRun")}</Text>
        )}
        {summary && (
          <Text size="sm" mt={4}>
            {t("grooming.scan.summaryLine", {
              added: summary.added, removed: summary.removed, replaced: summary.replaced,
              review: summary.review,
              skipped: summary.skipped_dismissed + summary.skipped_pending,
              capped: summary.capped,
            })}
          </Text>
        )}
        {indexedDocs !== null && (
          <Text size="xs" c="dimmed" mt={4}>{t("grooming.scan.coverage", { docs: indexedDocs })}</Text>
        )}
        {embeddedEntities !== null && (
          <Text size="xs" c="dimmed">
            {t("grooming.scan.embeddedEntities", { n: embeddedEntities.n, m: embeddedEntities.m })}
          </Text>
        )}
      </Paper>

      {/* Controls */}
      <Group align="flex-end">
        <MultiSelect
          label={t("grooming.scan.entityTypes")}
          data={GROOMING_ENTITY_TYPES.map(et => ({ value: et.value, label: t(et.labelKey) }))}
          value={selectedTypes}
          onChange={setSelectedTypes}
          style={{ minWidth: 280 }}
        />
        <Button
          variant="default"
          loading={dryRunning}
          disabled={Boolean(disabledReason) || selectedTypes.length === 0 || Boolean(scanStatus?.running)}
          onClick={handleDryRun}
        >
          {t("grooming.scan.dryRunBtn")}
        </Button>
        <Button
          loading={starting}
          disabled={Boolean(disabledReason) || selectedTypes.length === 0 || Boolean(scanStatus?.running)}
          onClick={handleScanNow}
        >
          {t("grooming.scan.scanNowBtn")}
        </Button>
      </Group>

      {scanStatus?.running && (
        <Stack gap="xs">
          <Progress
            value={scanStatus.total > 0 ? (scanStatus.done / scanStatus.total) * 100 : 0}
            animated
          />
          <Text size="sm" c="dimmed">
            {t("grooming.scan.running", { entity: scanStatus.current_entity })}
          </Text>
        </Stack>
      )}

      {/* Dry-run preview table */}
      {candidates !== null && (
        candidates.length === 0 ? (
          <Text c="dimmed" size="sm">{t("grooming.scan.dryRunEmpty")}</Text>
        ) : (
          <>
            <Text size="sm" c="dimmed">{t("grooming.scan.dryRunCount", { count: candidates.length })}</Text>
            <Table striped highlightOnHover withTableBorder style={{ fontSize: "0.8rem" }}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t("grooming.scan.col.entityType")}</Table.Th>
                  {sortHeader("entity_name", t("grooming.scan.col.entity"))}
                  <Table.Th>{t("grooming.scan.col.document")}</Table.Th>
                  {sortHeader("action", t("grooming.scan.col.action"))}
                  {sortHeader("score", t("grooming.scan.col.score"))}
                  <Table.Th>{t("grooming.scan.col.percentile")}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {sortedCandidates.map((c, i) => (
                  <Table.Tr key={i}>
                    <Table.Td>{t(`grooming.entityType.${c.entity_type === "document_type" ? "documentType" : c.entity_type}`)}</Table.Td>
                    <Table.Td>
                      {c.entity_name}
                      {c.action === "replace" && c.replacement_entity_name && (
                        <Text span size="xs" c="dimmed"> → {c.replacement_entity_name}</Text>
                      )}
                    </Table.Td>
                    <Table.Td>
                      {c.deeplink_url ? (
                        <Anchor href={c.deeplink_url} target="_blank" size="sm">
                          {c.document_title || `#${c.document_id}`}
                        </Anchor>
                      ) : (c.document_title || `#${c.document_id}`)}
                    </Table.Td>
                    <Table.Td>
                      <Badge size="sm" variant="light" color={ACTION_COLORS[c.action] ?? "gray"}>
                        {t(`grooming.scan.action.${c.action}`)}
                      </Badge>
                    </Table.Td>
                    <Table.Td>{c.score.toFixed(2)}</Table.Td>
                    <Table.Td>{c.cohort_percentile !== null ? `${c.cohort_percentile}%` : "—"}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
          </>
        )
      )}
    </Stack>
  );
}

// ── LibraryPage ────────────────────────────────────────────────────────────

export default function LibraryPage() {
  const { t } = useTranslation();
  const [entityType, setEntityType] = useState<EntityType>("tag");
  const [activeTab, setActiveTab] = useState<string>("descriptions");

  const entityTypeOptions = GROOMING_ENTITY_TYPES.map(et => ({
    label: t(et.labelKey),
    value: et.value,
  }));

  return (
    <Stack gap="md">
      <Title order={2}>{t("nav.library")}</Title>

      <SegmentedControl
        value={entityType}
        onChange={v => setEntityType(v as EntityType)}
        data={entityTypeOptions}
      />

      <Tabs value={activeTab} onChange={v => setActiveTab(v ?? "descriptions")}>
        <Tabs.List mb="md">
          <Tabs.Tab value="descriptions">{t("grooming.tabs.descriptions")}</Tabs.Tab>
          <Tabs.Tab value="dedup">{t("grooming.tabs.dedup")}</Tabs.Tab>
          <Tabs.Tab value="scan">{t("grooming.tabs.scan")}</Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="descriptions" keepMounted={false}>
          <DescriptionsTab key={entityType} entityType={entityType} />
        </Tabs.Panel>

        <Tabs.Panel value="dedup" keepMounted={false}>
          <DedupTab key={entityType} entityType={entityType} />
        </Tabs.Panel>

        <Tabs.Panel value="scan" keepMounted={false}>
          <ScanTab />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
