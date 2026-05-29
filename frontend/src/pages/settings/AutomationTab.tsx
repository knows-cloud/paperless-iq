import { Switch, NumberInput, TextInput, Select, Paper, Text, Divider, Stack, Alert } from "@mantine/core";
import { useTranslation } from "react-i18next";

interface Props {
  s: Record<string, unknown>;
}

export function AutomationTab({ s }: Props) {
  const { t } = useTranslation();
  return (
    <Stack gap="md">
      <Paper withBorder p="md" radius="md">
        <Text fw={600} mb="md">{t("settings.tabs.automation")}</Text>
        <Stack gap="md">
          <Switch
            name="automation_enabled"
            label={t("common.enable")}
            defaultChecked={Boolean(s.automation_enabled)}
            description={t("automation.enable.description")}
          />
          <Switch
            name="auto_apply"
            label={t("automation.autoApply.label")}
            defaultChecked={Boolean(s.auto_apply)}
            description={
              <Text size="xs" c="orange">{t("automation.autoApply.description")}</Text>
            }
          />

          <Divider label={t("automation.schedule.divider")} labelPosition="left" />

          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
            <NumberInput
              label={t("automation.pollInterval.label")}
              name="poll_interval_seconds"
              min={1}
              defaultValue={Number(s.poll_interval_seconds ?? 30)}
              style={{ flex: 1, minWidth: "160px" }}
            />
            <NumberInput
              label={t("automation.batchSize.label")}
              name="batch_size"
              min={1}
              defaultValue={Number(s.batch_size ?? 10)}
              description={t("automation.batchSize.description")}
              style={{ flex: 1, minWidth: "160px" }}
            />
            <TextInput
              label={t("automation.cron.label")}
              name="schedule_cron"
              defaultValue={String(s.schedule_cron ?? "")}
              placeholder={t("automation.cron.placeholder")}
              description={t("automation.cron.description")}
              style={{ flex: 2, minWidth: "200px" }}
            />
          </div>
        </Stack>
      </Paper>

      <Paper withBorder p="md" radius="md">
        <Text fw={600} mb="xs">{t("automation.policies.title")}</Text>
        <Text size="sm" c="dimmed" mb="sm">{t("automation.policies.description")}</Text>
        <Alert color="orange" variant="light" mb="md">
          {t("automation.policies.alert")}
        </Alert>
        <Stack gap="md">
          <Select
            label={t("entity.tagsLabel")}
            name="tag_creation_policy"
            defaultValue={String(s.tag_creation_policy ?? "existing_only")}
            data={[
              { value: "existing_only", label: t("common.policy.existingOnly", { entity: t("entity.tags") }) },
              { value: "allow_new",     label: t("common.policy.allowNew",     { entity: t("entity.tags") }) },
            ]}
          />
          <Select
            label={t("entity.correspondentsLabel")}
            name="correspondent_creation_policy"
            defaultValue={String(s.correspondent_creation_policy ?? "existing_only")}
            data={[
              { value: "existing_only", label: t("common.policy.existingOnly", { entity: t("entity.correspondents") }) },
              { value: "allow_new",     label: t("common.policy.allowNew",     { entity: t("entity.correspondents") }) },
            ]}
          />
          <Select
            label={t("entity.documentTypesLabel")}
            name="doctype_creation_policy"
            defaultValue={String(s.doctype_creation_policy ?? "existing_only")}
            data={[
              { value: "existing_only", label: t("common.policy.existingOnly", { entity: t("entity.documentTypes") }) },
              { value: "allow_new",     label: t("common.policy.allowNew",     { entity: t("entity.documentTypes") }) },
            ]}
          />
        </Stack>
      </Paper>
    </Stack>
  );
}
