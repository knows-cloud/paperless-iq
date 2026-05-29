import { useQuery } from "@tanstack/react-query";
import { Group, Tooltip, Box } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { api } from "./api";

function Dot({ ok, pulse, label }: { ok: boolean; pulse?: boolean; label: string }) {
  return (
    <Tooltip label={label} withArrow>
      <Box
        w={10}
        h={10}
        style={{
          borderRadius: "50%",
          background: ok ? "var(--mantine-color-teal-5)" : "var(--mantine-color-red-5)",
          boxShadow: ok
            ? "0 0 5px var(--mantine-color-teal-5)"
            : "0 0 5px var(--mantine-color-red-5)",
          animation: pulse ? "statusPulse 1.2s infinite" : undefined,
          cursor: "default",
        }}
      />
    </Tooltip>
  );
}

export default function StatusPanel() {
  const { t } = useTranslation();
  const { data } = useQuery({
    queryKey: ["status"],
    queryFn: api.getStatus,
    refetchInterval: 10000,
    retry: false,
  });

  const d = data ?? { llm_online: false, embed_online: false, queue_pending: 0, embedded_chunks: 0, total_documents: 0, processing: {} };
  const proc = (d.processing ?? {}) as Record<string, unknown>;
  const queueSize = (proc.queue_size as number) ?? 0;
  const embeddingActive = (proc.embedding_active as boolean) ?? false;
  const embeddingDone = (proc.embedding_done as number) ?? 0;
  const embeddingTotal = (proc.embedding_total as number) ?? 0;
  const chunksOk = d.embedded_chunks > 0;

  const statusStr = (online: boolean) => online ? t("processing.online") : t("processing.offline");

  return (
    <Group
      px="md"
      py="xs"
      justify="space-around"
      style={{ borderTop: "1px solid var(--mantine-color-default-border)", borderBottom: "1px solid var(--mantine-color-default-border)" }}
    >
      <Dot ok={d.llm_online}  label={t("statusPanel.llm",       { status: statusStr(d.llm_online) })} />
      <Dot ok={d.embed_online} label={t("statusPanel.embedding",  { status: statusStr(d.embed_online) })} />
      <Dot ok={queueSize <= 15} label={t("statusPanel.queue",     { count: String(queueSize) })} />
      <Dot ok={chunksOk} pulse={embeddingActive} label={t("statusPanel.vectorDb", { chunks: String(d.embedded_chunks), done: String(embeddingDone), total: String(embeddingTotal) })} />
      <style>{`
        @keyframes statusPulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.2; }
        }
      `}</style>
    </Group>
  );
}
