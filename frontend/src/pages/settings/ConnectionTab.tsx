import { TextInput, Select, Button, Paper, Text, Divider, Stack, Group } from "@mantine/core";
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
  return (
    <Paper withBorder p="md" radius="md">
      <Text fw={600} mb="md">Paperless NGX Connection</Text>
      <Stack gap="md">
        <TextInput
          label="Public URL"
          type="url"
          value={paperlessPublicUrl}
          onChange={e => setPaperlessPublicUrl(e.target.value)}
          placeholder="https://paperless.myhome.com or http://192.168.1.10:8000"
          description="The URL your browser uses to reach Paperless NGX. Used for 'Open in Paperless' links. Leave empty to fall back to the internal PAPERLESS_URL."
        />
        <Group align="center" gap="md">
          <Button variant="default" onClick={onTestConnection} loading={testingConnection}>
            Test Connection
          </Button>
          {connectionTestResult && (
            <Text
              size="sm"
              c={connectionTestResult.status === "ok" ? "teal" : "red"}
            >
              {connectionTestResult.status === "ok"
                ? `✓ Connected${connectionTestResult.version ? ` (Paperless NGX ${connectionTestResult.version})` : ""}`
                : `✗ ${connectionTestResult.detail ?? "Unknown error"}`}
            </Text>
          )}
        </Group>

        <Divider label="Inbox Tag" labelPosition="left" />

        <Select
          label="Documents with this tag are picked up for processing"
          placeholder="— Search for a tag —"
          data={tagList.map(t => ({ value: String(t.id), label: t.name }))}
          value={inboxTagId || null}
          onChange={v => setInboxTagId(v ?? "")}
          searchable
          clearable
          error={tagsError ? "Cannot load tags from Paperless NGX." : undefined}
        />

        <Divider label="Live Reindex Webhook" labelPosition="left" />

        <TextInput
          label="Paperless IQ internal URL"
          type="url"
          name="paperless_iq_internal_url"
          value={paperlessIqInternalUrl}
          onChange={e => setPaperlessIqInternalUrl(e.target.value)}
          placeholder="http://paperless-iq:8000"
          description="How Paperless NGX reaches Paperless IQ on the internal network. Leave empty to use the URL detected from the browser request."
        />
        <Group align="center" gap="md">
          <Button variant="default" onClick={onRegisterWebhook} loading={registeringWebhook}>
            Register Webhook
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
