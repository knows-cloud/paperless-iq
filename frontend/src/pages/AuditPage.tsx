import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Title, Paper, Text, Group, Stack, Badge, Button,
  TextInput, Select, Table, Box,
} from "@mantine/core";
import { api } from "../api";
import { t } from "../i18n";

export default function AuditPage() {
  const [filters, setFilters] = useState<Record<string, string>>({});
  const { data, isLoading } = useQuery({ queryKey: ["audit", filters], queryFn: () => api.getAuditLog(filters) });
  const [importMsg, setImportMsg] = useState("");

  const handleExport = async () => {
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

  const items = (data?.items ?? []) as Array<Record<string, unknown>>;

  return (
    <Stack gap="md">
      <Title order={2}>{t("nav.audit")}</Title>

      <Paper withBorder p="md" radius="md">
        <Group mb="md" gap="sm">
          <TextInput
            placeholder={`${t("audit.colDoc")} ID`}
            size="sm"
            style={{ maxWidth: 160 }}
            onChange={e => setFilters(f => ({ ...f, document_id: e.target.value }))}
          />
          <Select
            size="sm"
            style={{ maxWidth: 180 }}
            defaultValue=""
            data={[
              { value: "", label: t("audit.allSources") },
              { value: "ai", label: t("audit.aiSource") },
              { value: "human", label: t("audit.humanSource") },
            ]}
            onChange={v => setFilters(f => ({ ...f, change_source: v ?? "" }))}
          />
        </Group>

        {isLoading ? (
          <Text size="sm" c="dimmed">{t("audit.loading")}</Text>
        ) : items.length === 0 ? (
          <Text size="sm" c="dimmed">{t("audit.empty")}</Text>
        ) : (
          <Box style={{ overflowX: "auto" }}>
            <Table striped highlightOnHover withTableBorder withColumnBorders fz="sm">
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>{t("audit.colDoc")}</Table.Th>
                  <Table.Th>{t("audit.colField")}</Table.Th>
                  <Table.Th maw={200}>{t("audit.colPrevious")}</Table.Th>
                  <Table.Th maw={200}>{t("audit.colNew")}</Table.Th>
                  <Table.Th>{t("audit.colSource")}</Table.Th>
                  <Table.Th>{t("audit.colTime")}</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {items.map((e, i) => (
                  <Table.Tr key={i}>
                    <Table.Td style={{ whiteSpace: "nowrap" }}>{String(e.document_id)}</Table.Td>
                    <Table.Td style={{ whiteSpace: "nowrap" }}>{String(e.field_name)}</Table.Td>
                    <Table.Td maw={200} style={{ overflow: "hidden", textOverflow: "ellipsis", wordBreak: "break-word" }}>
                      {String(e.previous_value ?? "—")}
                    </Table.Td>
                    <Table.Td maw={200} style={{ overflow: "hidden", textOverflow: "ellipsis", wordBreak: "break-word" }}>
                      {String(e.new_value ?? "—")}
                    </Table.Td>
                    <Table.Td>
                      <Badge color={e.change_source === "ai" ? "yellow" : "teal"} variant="light" size="sm">
                        {String(e.change_source)}
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
        )}
      </Paper>

      <Title order={3}>{t("audit.importExport")}</Title>
      <Paper withBorder p="md" radius="md">
        <Group gap="sm" align="center">
          <Button onClick={handleExport}>{t("audit.export")}</Button>
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
