import { Switch, NumberInput, Paper, Text, Stack } from "@mantine/core";
import { useTranslation } from "react-i18next";

interface Props {
  s: Record<string, unknown>;
}

export function MetadataRulesTab({ s }: Props) {
  const { t } = useTranslation();
  return (
    <Stack gap="md">
      <Paper withBorder p="md" radius="md">
        <Text fw={600} mb="xs">{t("metadataRules.title")}</Text>
        <Text size="sm" c="dimmed" mb="md">{t("metadataRules.description")}</Text>
        <Stack gap="md">
          <Switch
            name="smart_entity_selection"
            label={t("common.enable")}
            defaultChecked={Boolean(s.smart_entity_selection ?? true)}
          />
          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
            <NumberInput
              label={t("metadataRules.similarDocs.label")}
              name="similar_docs_count"
              min={1}
              max={50}
              defaultValue={Number(s.similar_docs_count ?? 10)}
              description={t("metadataRules.similarDocs.description")}
              style={{ flex: 1, minWidth: "180px" }}
            />
            <NumberInput
              label={t("metadataRules.frequencyFallback.label")}
              name="frequency_fallback_count"
              min={0}
              max={100}
              defaultValue={Number(s.frequency_fallback_count ?? 20)}
              description={t("metadataRules.frequencyFallback.description")}
              style={{ flex: 1, minWidth: "180px" }}
            />
          </div>
        </Stack>
      </Paper>
    </Stack>
  );
}
