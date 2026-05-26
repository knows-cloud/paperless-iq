import { Switch, NumberInput, TextInput, Select, Paper, Text, Divider, Stack, Alert, PasswordInput, Group, Button, Badge } from "@mantine/core";

interface Props {
  s: Record<string, unknown>;
  webhookSecretSet: boolean;
  webhookSecretInput: string | null;
  onWebhookSecretChange: (v: string | null) => void;
}

function generateSecret(): string {
  const arr = new Uint8Array(24);
  window.crypto.getRandomValues(arr);
  return Array.from(arr).map(b => b.toString(16).padStart(2, "0")).join("");
}

export function AutomationTab({ s, webhookSecretSet, webhookSecretInput, onWebhookSecretChange }: Props) {
  return (
    <Stack gap="md">
      <Paper withBorder p="md" radius="md">
        <Text fw={600} mb="md">Automation</Text>
        <Stack gap="md">
          <Switch
            name="automation_enabled"
            label="Enable automation"
            defaultChecked={Boolean(s.automation_enabled)}
            description="Automatically poll for new documents with the inbox tag and analyze them in the background."
          />
          <Switch
            name="auto_apply"
            label="Auto-apply suggestions (skip approval queue)"
            defaultChecked={Boolean(s.auto_apply)}
            description={
              <Text size="xs" c="orange">
                AI suggestions are applied immediately without human review. Combined with "Allow new" creation policies,
                this will create new tags, correspondents, and types automatically.
              </Text>
            }
          />

          <Divider label="Schedule" labelPosition="left" />

          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
            <NumberInput
              label="Poll Interval (seconds)"
              name="poll_interval_seconds"
              min={1}
              defaultValue={Number(s.poll_interval_seconds ?? 30)}
              style={{ flex: 1, minWidth: "160px" }}
            />
            <NumberInput
              label="Batch Size"
              name="batch_size"
              min={1}
              defaultValue={Number(s.batch_size ?? 10)}
              description="Documents processed per polling cycle."
              style={{ flex: 1, minWidth: "160px" }}
            />
            <TextInput
              label="Cron Schedule"
              name="schedule_cron"
              defaultValue={String(s.schedule_cron ?? "")}
              placeholder="e.g. 0 */6 * * *  (every 6 hours)"
              description="Optional cron expression to trigger processing on a fixed schedule."
              style={{ flex: 2, minWidth: "200px" }}
            />
          </div>
        </Stack>
      </Paper>

      <Paper withBorder p="md" radius="md">
        <Text fw={600} mb="xs">Creation Policies</Text>
        <Text size="sm" c="dimmed" mb="sm">
          Controls whether the LLM can suggest values that don't yet exist in Paperless NGX.
          "Existing only" filters them out; "Allow new" keeps them and creates the entity when the suggestion is applied.
        </Text>
        <Alert color="orange" variant="light" mb="md">
          Only relevant when auto-apply is enabled. For manual review, new values are always created when you approve.
          With auto-apply and "Allow new", entities are created automatically without review.
        </Alert>
        <Stack gap="md">
          <Select
            label="Tags"
            name="tag_creation_policy"
            defaultValue={String(s.tag_creation_policy ?? "existing_only")}
            data={[
              { value: "existing_only", label: "Existing only — remove unknown tags from suggestions" },
              { value: "allow_new", label: "Allow new — keep unknown tags, create automatically" },
            ]}
          />
          <Select
            label="Correspondents"
            name="correspondent_creation_policy"
            defaultValue={String(s.correspondent_creation_policy ?? "existing_only")}
            data={[
              { value: "existing_only", label: "Existing only — remove unknown correspondents" },
              { value: "allow_new", label: "Allow new — keep unknown correspondents, create automatically" },
            ]}
          />
          <Select
            label="Document Types"
            name="doctype_creation_policy"
            defaultValue={String(s.doctype_creation_policy ?? "existing_only")}
            data={[
              { value: "existing_only", label: "Existing only — remove unknown document types" },
              { value: "allow_new", label: "Allow new — keep unknown types, create automatically" },
            ]}
          />
        </Stack>
      </Paper>
      <Paper withBorder p="md" radius="md">
        <Group justify="space-between" mb="xs">
          <Text fw={600}>Webhook Security</Text>
          {webhookSecretSet && webhookSecretInput === null
            ? <Badge color="teal" variant="light">Secret set</Badge>
            : webhookSecretInput === ""
            ? <Badge color="orange" variant="light">Will be cleared on save</Badge>
            : webhookSecretInput
            ? <Badge color="blue" variant="light">New secret pending save</Badge>
            : <Badge color="gray" variant="light">No secret</Badge>
          }
        </Group>
        <Text size="sm" c="dimmed" mb="sm">
          Paperless NGX sends the secret in the <strong>X-Webhook-Secret</strong> header.
          Leave blank to keep the current value; generate or paste a new one to rotate it.
        </Text>
        <Stack gap="xs">
          <PasswordInput
            placeholder={webhookSecretSet && webhookSecretInput === null ? "Secret is set — enter new value to rotate" : "No secret set"}
            value={webhookSecretInput ?? ""}
            onChange={e => onWebhookSecretChange(e.currentTarget.value || null)}
          />
          <Group gap="xs">
            <Button
              size="xs"
              variant="light"
              onClick={() => onWebhookSecretChange(generateSecret())}
            >
              Generate
            </Button>
            {(webhookSecretSet || webhookSecretInput) && (
              <Button
                size="xs"
                variant="subtle"
                color="red"
                onClick={() => onWebhookSecretChange("")}
              >
                Clear
              </Button>
            )}
            {webhookSecretInput !== null && (
              <Button
                size="xs"
                variant="subtle"
                color="gray"
                onClick={() => onWebhookSecretChange(null)}
              >
                Cancel
              </Button>
            )}
          </Group>
        </Stack>
      </Paper>
    </Stack>
  );
}
