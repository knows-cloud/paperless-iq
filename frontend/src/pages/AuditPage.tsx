import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Title, Paper, Text, Group, Stack, Badge, Button,
  TextInput, Select, Table, Box, Pagination, Alert,
} from "@mantine/core";
import { api } from "../api";
import { t } from "../i18n";

const PAGE_SIZE = 50;

const ACTION_TYPES = [
  { value: "", label: "All action types" },
  { value: "field_change", label: "Field change" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Rejected" },
  { value: "analysis_triggered", label: "Analysis triggered" },
  { value: "reindex", label: "Reindex" },
  { value: "webhook_received", label: "Webhook received" },
];

function actorBadgeColor(actor: string): string {
  if (actor.startsWith("user:")) return "teal";
  if (actor === "automation") return "grape";
  if (actor === "webhook") return "indigo";
  if (actor === "manual_analysis" || actor === "vision_analysis") return "orange";
  if (actor === "system") return "gray";
  if (actor === "ai") return "yellow";
  if (actor === "human") return "teal";
  return "gray";
}

function actionBadgeColor(action: string): string {
  if (action === "approved") return "teal";
  if (action === "rejected") return "red";
  if (action === "field_change") return "blue";
  if (action === "reindex") return "violet";
  if (action === "webhook_received") return "indigo";
  if (action === "analysis_triggered") return "orange";
  return "gray";
}

export default function AuditPage() {
  const [page, setPage] = useState(1);
  const [docId, setDocId] = useState("");
  const [docTitle, setDocTitle] = useState("");
  const [actor, setActor] = useState("");
  const [actionType, setActionType] = useState("");
  const [fieldName, setFieldName] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [exportError, setExportError] = useState<string | null>(null);
  const [importMsg, setImportMsg] = useState("");

  const filterParams: Record<string, string> = { page: String(page), page_size: String(PAGE_SIZE) };
  if (docId) filterParams.document_id = docId;
  if (docTitle) filterParams.document_title = docTitle;
  if (actor) filterParams.change_source = actor;
  if (actionType) filterParams.action_type = actionType;
  if (fieldName) filterParams.field_name = fieldName;
  if (dateFrom) filterParams.date_from = new Date(dateFrom).toISOString();
  if (dateTo) filterParams.date_to = new Date(dateTo).toISOString();

  const { data, isLoading } = useQuery({
    queryKey: ["audit", filterParams],
    queryFn: () => api.getAuditLog(filterParams),
  });

  const items = (data?.items ?? []) as Array<Record<string, unknown>>;
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  function resetFilters() {
    setDocId(""); setDocTitle(""); setActor(""); setActionType("");
    setFieldName(""); setDateFrom(""); setDateTo(""); setPage(1);
  }

  async function handleExportAudit(fmt: "csv" | "json") {
    setExportError(null);
    try {
      const exportParams: Record<string, string> = {};
      if (docId) exportParams.document_id = docId;
      if (docTitle) exportParams.document_title = docTitle;
      if (actor) exportParams.change_source = actor;
      if (actionType) exportParams.action_type = actionType;
      if (fieldName) exportParams.field_name = fieldName;
      if (dateFrom) exportParams.date_from = new Date(dateFrom).toISOString();
      if (dateTo) exportParams.date_to = new Date(dateTo).toISOString();
      const blob = await api.exportAuditLog(exportParams, fmt);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `audit_log.${fmt}`; a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setExportError((e as Error).message);
    }
  }

  const handleExportConfig = async () => {
    const config = await api.exportConfig();
    const blob = new Blob([JSON.stringify(config, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "paperless-iq-config.json"; a.click();
    URL.revokeObjectURL(url);
  };

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    try {
      const parsed = JSON.parse(text);
      const result = await api.importConfig(parsed);
      setImportMsg(t("audit.importSuccess", { applied: String(result.applied.length), skipped: String(result.skipped.length) }));
    } catch (err) { setImportMsg(`${t("audit.importFailed")} ${(err as Error).message}`); }
  };

  return (
    <Stack gap="md">
      <Title order={2}>{t("nav.audit")}</Title>

      <Paper withBorder p="md" radius="md">
        <Group mb="sm" gap="sm" wrap="wrap">
          <TextInput
            placeholder="Doc ID"
            size="sm"
            style={{ maxWidth: 90 }}
            value={docId}
            onChange={e => { setDocId(e.target.value); setPage(1); }}
          />
          <TextInput
            placeholder="Document title (substring)"
            size="sm"
            style={{ maxWidth: 200 }}
            value={docTitle}
            onChange={e => { setDocTitle(e.target.value); setPage(1); }}
          />
          <TextInput
            placeholder="Actor / source"
            size="sm"
            style={{ maxWidth: 150 }}
            value={actor}
            onChange={e => { setActor(e.target.value); setPage(1); }}
          />
          <Select
            size="sm"
            style={{ maxWidth: 200 }}
            value={actionType}
            data={ACTION_TYPES}
            onChange={v => { setActionType(v ?? ""); setPage(1); }}
          />
          <TextInput
            placeholder="Field name"
            size="sm"
            style={{ maxWidth: 130 }}
            value={fieldName}
            onChange={e => { setFieldName(e.target.value); setPage(1); }}
          />
          <div>
            <Text size="xs" c="dimmed" mb={2}>From date</Text>
            <input
              type="date"
              value={dateFrom}
              onChange={e => { setDateFrom(e.target.value); setPage(1); }}
              style={{ fontSize: 13, padding: "5px 8px", borderRadius: 6, border: "1px solid var(--mantine-color-default-border)", background: "var(--mantine-color-body)", color: "var(--mantine-color-text)" }}
            />
          </div>
          <div>
            <Text size="xs" c="dimmed" mb={2}>To date</Text>
            <input
              type="date"
              value={dateTo}
              onChange={e => { setDateTo(e.target.value); setPage(1); }}
              style={{ fontSize: 13, padding: "5px 8px", borderRadius: 6, border: "1px solid var(--mantine-color-default-border)", background: "var(--mantine-color-body)", color: "var(--mantine-color-text)" }}
            />
          </div>
          <Button size="sm" variant="subtle" onClick={resetFilters}>Clear</Button>
        </Group>

        <Group mb="sm" gap="xs">
          <Button size="xs" variant="light" color="teal" onClick={() => handleExportAudit("csv")}>
            Export CSV
          </Button>
          <Button size="xs" variant="light" color="blue" onClick={() => handleExportAudit("json")}>
            Export JSON
          </Button>
          {total > 0 && (
            <Text size="xs" c="dimmed">{total} entries</Text>
          )}
        </Group>

        {exportError && <Alert color="red" variant="light" mb="sm">{exportError}</Alert>}

        {isLoading ? (
          <Text size="sm" c="dimmed">{t("audit.loading")}</Text>
        ) : items.length === 0 ? (
          <Text size="sm" c="dimmed">{t("audit.empty")}</Text>
        ) : (
          <>
            <Box style={{ overflowX: "auto" }}>
              <Table striped highlightOnHover withTableBorder withColumnBorders fz="sm">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Doc</Table.Th>
                    <Table.Th>Title</Table.Th>
                    <Table.Th>Action</Table.Th>
                    <Table.Th>Field</Table.Th>
                    <Table.Th maw={180}>Previous</Table.Th>
                    <Table.Th maw={180}>New</Table.Th>
                    <Table.Th>Actor</Table.Th>
                    <Table.Th>Time</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {items.map((e, i) => (
                    <Table.Tr key={i}>
                      <Table.Td style={{ whiteSpace: "nowrap" }}>{String(e.document_id || "")}</Table.Td>
                      <Table.Td style={{ maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {String(e.document_title ?? "—")}
                      </Table.Td>
                      <Table.Td>
                        <Badge color={actionBadgeColor(String(e.action_type ?? ""))} variant="light" size="sm">
                          {String(e.action_type ?? "field_change")}
                        </Badge>
                      </Table.Td>
                      <Table.Td style={{ whiteSpace: "nowrap" }}>
                        {String(e.field_name) === "_event" ? "—" : String(e.field_name)}
                      </Table.Td>
                      <Table.Td maw={180} style={{ overflow: "hidden", textOverflow: "ellipsis", wordBreak: "break-word" }}>
                        {String(e.previous_value ?? "—")}
                      </Table.Td>
                      <Table.Td maw={180} style={{ overflow: "hidden", textOverflow: "ellipsis", wordBreak: "break-word" }}>
                        {String(e.new_value ?? "—")}
                      </Table.Td>
                      <Table.Td>
                        <Badge color={actorBadgeColor(String(e.change_source ?? ""))} variant="light" size="sm">
                          {String(e.change_source ?? "")}
                        </Badge>
                      </Table.Td>
                      <Table.Td style={{ whiteSpace: "nowrap" }} c="dimmed">
                        {new Date(String(e.changed_at)).toLocaleString()}
                      </Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Box>
            {totalPages > 1 && (
              <Group justify="center" mt="sm">
                <Pagination total={totalPages} value={page} onChange={setPage} size="sm" />
              </Group>
            )}
          </>
        )}
      </Paper>

      <Title order={3}>{t("audit.importExport")}</Title>
      <Paper withBorder p="md" radius="md">
        <Group gap="sm" align="center">
          <Button onClick={handleExportConfig}>{t("audit.export")}</Button>
          <Button variant="default" component="label">
            {t("audit.import")}
            <input type="file" accept=".json" onChange={handleImport} style={{ display: "none" }} />
          </Button>
        </Group>
        {importMsg && (
          <Text size="sm" c="teal" mt="sm">{importMsg}</Text>
        )}
      </Paper>
    </Stack>
  );
}
