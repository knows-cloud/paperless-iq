import { TextInput, Select, Button, Paper, Text, Divider, Stack, Group } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { type PaperlessEntity, type ConnectionTestResult } from "../../api";

interface Props {
  paperlessPublicUrl: string;
  setPaperlessPublicUrl: (v: string) => void;
  paperlessIqInternalUrl: string;
  setPaperlessIqInternalUrl: (v: string) => void;
  inboxTagId: string;
  setInboxTagId: (v: string) => void;
  tagList: PaperlessEntity[];
  tagsError: boolean;
  connectionTestResult: ConnectionTestResult | null;
  testingConnection: boolean;
  onTestConnection: () => void;
  webhookResult: { ok: boolean; detail: string } | null;
  registeringWebhook: boolean;
  onRegisterWebhook: () => void;
}

export function ConnectionTab({
  paperlessPublicUrl, setPaperlessPublicUrl,
  paperlessIqInternalUrl, setPaperlessIqInternalUrl,
  inboxTagId, setInboxTagId,
  tagList, tagsError,
  connectionTestResult, testingConnection, onTestConnection,
  webhookResult, registeringWebhook, onRegisterWebhook,
}: Props) {
  const { t } = useTranslation();
  return (
    <Paper withBorder p="md" radius="md">
      <Text fw={600} mb="md">{t("connection.title")}</Text>
      <Stack gap="md">
        <TextInput
          label={t("connection.publicUrl.label")}
          type="url"
          value={paperlessPublicUrl}
          onChange={e => setPaperlessPublicUrl(e.target.value)}
          placeholder={t("connection.publicUrl.placeholder")}
          description={t("connection.publicUrl.description")}
        />
        <Group align="center" gap="md">
          <Button variant="default" onClick={onTestConnection} loading={testingConnection}>
            {t("connection.testBtn")}
          </Button>
          {connectionTestResult && (
            <Text
              size="sm"
              c={connectionTestResult.status === "ok" ? "teal" : "red"}
            >
              {connectionTestResult.status === "ok"
                ? (connectionTestResult.version
                    ? t("connection.okVersion", { version: connectionTestResult.version })
                    : t("connection.ok"))
                : `✗ ${connectionTestResult.detail ?? t("connection.unknownError")}`}
            </Text>
          )}
        </Group>

        <Divider label={t("connection.inboxTag.divider")} labelPosition="left" />

        <Select
          label={t("connection.inboxTag.label")}
          placeholder={t("connection.inboxTag.placeholder")}
          data={tagList.map(tag => ({ value: String(tag.id), label: tag.name }))}
          value={inboxTagId || null}
          onChange={v => setInboxTagId(v ?? "")}
          searchable
          clearable
          error={tagsError ? t("connection.inboxTag.error") : undefined}
        />

        <Divider label={t("connection.webhook.divider")} labelPosition="left" />

        <TextInput
          label={t("connection.internalUrl.label")}
          type="url"
          name="paperless_iq_internal_url"
          value={paperlessIqInternalUrl}
          onChange={e => setPaperlessIqInternalUrl(e.target.value)}
          placeholder={t("connection.internalUrl.placeholder")}
          description={t("connection.internalUrl.description")}
        />
        <Group align="center" gap="md">
          <Button variant="default" onClick={onRegisterWebhook} loading={registeringWebhook}>
            {t("connection.registerWebhook")}
          </Button>
          {webhookResult && (
            <Text size="sm" c={webhookResult.ok ? "teal" : "red"}>
              {webhookResult.ok ? `✓ ${webhookResult.detail}` : `✗ ${webhookResult.detail}`}
            </Text>
          )}
        </Group>
      </Stack>
    </Paper>
  );
}
