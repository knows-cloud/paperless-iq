import { useQuery } from "@tanstack/react-query";
import {
  Title, Paper, Text, Group, Stack, Badge, Progress,
  Box,
} from "@mantine/core";
import { api } from "../api";
import { t } from "../i18n";

export default function ProcessingPage() {
  const status = useQuery({ queryKey: ["status"], queryFn: api.getStatus, refetchInterval: 3000, retry: false });
  const tracking = useQuery({ queryKey: ["tracking"], queryFn: api.getTrackingStats, refetchInterval: 10000, retry: false });
  const d = status.data;
  const proc = d?.processing as Record<string, unknown> | undefined;
  const tr = tracking.data;

  const embeddingDone = (proc?.embedding_done as number) ?? 0;
  const embeddingTotal = Math.max(1, (proc?.embedding_total as number) ?? 1);
  const embeddingPct = Math.min(100, Math.round((embeddingDone / embeddingTotal) * 100));

  return (
    <Stack gap="md">
      <Title order={2}>{t("processing.title")}</Title>

      {/* System Status */}
      <Paper withBorder p="md" radius="md">
        <Text fw={600} size="sm" mb="sm">{t("processing.systemStatus")}</Text>
        <Group gap="xl">
          <Group gap="xs">
            <Text size="sm" c="dimmed">{t("processing.llm")}:</Text>
            <Badge color={d?.llm_online ? "teal" : "red"} variant="light">
              {d?.llm_online ? t("processing.online") : t("processing.offline")}
            </Badge>
          </Group>
          <Group gap="xs">
            <Text size="sm" c="dimmed">{t("processing.embedding")}:</Text>
            <Badge color={d?.embed_online ? "teal" : "red"} variant="light">
              {d?.embed_online ? t("processing.online") : t("processing.offline")}
            </Badge>
          </Group>
          <Group gap="xs">
            <Text size="sm" c="dimmed">{t("processing.approvalQueue")}:</Text>
            <Text size="sm" fw={600}>{d?.queue_pending ?? 0} {t("processing.pending")}</Text>
          </Group>
        </Group>
      </Paper>

      {/* Processing Queue */}
      <Paper withBorder p="md" radius="md">
        <Text fw={600} size="sm" mb="sm">{t("processing.queue")}</Text>
        {proc?.active_task ? (
          <Group gap="sm">
            <Box
              w={8} h={8}
              style={{ borderRadius: "50%", background: "var(--mantine-color-teal-5)", animation: "pulse 1.5s infinite", flexShrink: 0 }}
            />
            <Text size="sm" fw={500}>{String(proc.active_task)}</Text>
            {proc.active_priority != null && (
              <Badge variant="light" size="sm">{String(proc.active_priority)}</Badge>
            )}
          </Group>
        ) : (
          <Text size="sm" c="dimmed">{t("processing.idle")}</Text>
        )}
        {((proc?.pending_tasks as string[]) ?? []).length > 0 && (
          <Box mt="sm">
            <Text size="xs" fw={500} c="dimmed" mb={4}>{t("processing.waiting")}</Text>
            <Stack gap={2}>
              {((proc?.pending_tasks as string[]) ?? []).map((label, i) => (
                <Text key={i} size="sm" px="xs" py={2} style={{ borderRadius: "var(--mantine-radius-sm)", background: i % 2 === 1 ? "var(--mantine-color-default-hover)" : "transparent" }}>
                  {label}
                </Text>
              ))}
            </Stack>
          </Box>
        )}
      </Paper>

      {/* Vector Store Indexing */}
      <Paper withBorder p="md" radius="md">
        <Text fw={600} size="sm" mb="sm">{t("processing.vectorStore")}</Text>
        {proc?.embedding_active ? (
          <Stack gap="xs">
            <Group justify="space-between">
              <Text size="sm">{t("processing.indexingDocs")}</Text>
              <Text size="sm" fw={600}>{embeddingDone} / {embeddingTotal}</Text>
            </Group>
            <Progress value={embeddingPct} color="teal" animated />
          </Stack>
        ) : (
          <Text size="sm" c="dimmed">
            {d?.embedded_chunks
              ? t("processing.chunksIndexed", { chunks: String(d.embedded_chunks), docs: String(d.total_documents) })
              : t("processing.noDocsYet")}
          </Text>
        )}
      </Paper>

      {/* Document Tracking */}
      <Paper withBorder p="md" radius="md">
        <Text fw={600} size="sm" mb="sm">{t("processing.tracking")}</Text>
        {tr && (
          <Stack gap="md">
            <Group gap="xl">
              <Group gap="xs">
                <Text size="sm" c="dimmed">{t("processing.trackedLabel")}</Text>
                <Text size="sm" fw={600}>{tr.tracked_documents}</Text>
              </Group>
              <Group gap="xs">
                <Text size="sm" c="dimmed">{t("processing.approvedLabel")}</Text>
                <Text size="sm" fw={600} c="teal">{tr.suggestions_approved}</Text>
              </Group>
              <Group gap="xs">
                <Text size="sm" c="dimmed">{t("processing.rejectedLabel")}</Text>
                <Text size="sm" fw={600} c="red">{tr.suggestions_rejected}</Text>
              </Group>
              <Group gap="xs">
                <Text size="sm" c="dimmed">{t("processing.pendingLabel")}</Text>
                <Text size="sm" fw={600}>{tr.suggestions_pending}</Text>
              </Group>
            </Group>
            <Text size="xs" c="dimmed">{t("processing.trackingHint")}</Text>
          </Stack>
        )}
      </Paper>

      <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }`}</style>
    </Stack>
  );
}
