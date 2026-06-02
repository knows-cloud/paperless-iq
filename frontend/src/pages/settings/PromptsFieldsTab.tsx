import { Textarea, TextInput, Select, Button, Paper, Text, Stack, Group } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { api, type PaperlessCustomField } from "../../api";
import { METADATA_FIELDS } from "./constants";
import { Checkbox } from "@mantine/core";

interface Props {
  s: Record<string, unknown>;
  promptText: string;
  setPromptText: (v: string) => void;
  discoveryPrompt: string;
  setDiscoveryPrompt: (v: string) => void;
  translateLang: string;
  setTranslateLang: (v: string) => void;
  translating: boolean;
  setTranslating: (v: boolean) => void;
  fieldDescs: Record<string, string>;
  setFieldDescs: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  selectedCustomFields: number[];
  toggleCustomField: (cfId: number) => void;
  cfList: PaperlessCustomField[];
  customFieldsIsError: boolean;
}

export function PromptsFieldsTab({
  s,
  promptText, setPromptText,
  discoveryPrompt, setDiscoveryPrompt,
  translateLang, setTranslateLang,
  translating, setTranslating,
  fieldDescs, setFieldDescs,
  selectedCustomFields, toggleCustomField,
  cfList, customFieldsIsError,
}: Props) {
  const { t } = useTranslation();
  return (
    <Stack gap="md">
      <Paper withBorder p="md" radius="md">
        <Text fw={600} mb="md">{t("prompts.title")}</Text>
        <Stack gap="md">
          <Textarea
            label={t("prompts.global.label")}
            name="global_prompt_template"
            rows={10}
            value={promptText}
            onChange={e => setPromptText(e.target.value)}
            styles={{ input: { fontFamily: "monospace", fontSize: "0.85rem" } }}
          />
          <Group gap="xs" align="flex-end">
            <Text size="xs" c="dimmed" style={{ flex: 1 }}>{t("prompts.global.hint")}</Text>
            <Select
              size="xs"
              style={{ width: "auto" }}
              value={translateLang}
              onChange={v => setTranslateLang(v ?? "de")}
              data={[
                { value: "de", label: "Deutsch" },
                { value: "fr", label: "Français" },
                { value: "es", label: "Español" },
                { value: "it", label: "Italiano" },
                { value: "en", label: "English" },
              ]}
            />
            <Button
              size="xs"
              variant="default"
              loading={translating}
              disabled={!promptText.trim()}
              onClick={async () => {
                setTranslating(true);
                try {
                  const r = await api.translatePrompt(promptText, translateLang);
                  setPromptText(r.translated);
                } catch (e) { alert((e as Error).message); }
                setTranslating(false);
              }}
            >
              {t("prompts.translate")}
            </Button>
          </Group>
          <TextInput
            label={t("prompts.outputLang.label")}
            name="target_language"
            defaultValue={String(s.target_language ?? "")}
            placeholder={t("prompts.outputLang.placeholder")}
            description={t("prompts.outputLang.description")}
          />
        </Stack>
      </Paper>

      <Paper withBorder p="md" radius="md">
        <Text fw={600} mb="md">{t("prompts.discovery.title")}</Text>
        <Stack gap="md">
          <Textarea
            label={t("prompts.discovery.label")}
            name="discovery_system_prompt"
            rows={8}
            value={discoveryPrompt}
            onChange={e => setDiscoveryPrompt(e.target.value)}
            placeholder={t("prompts.discovery.placeholder")}
            styles={{ input: { fontFamily: "monospace", fontSize: "0.85rem" } }}
          />
          <Text size="xs" c="dimmed">{t("prompts.discovery.hint")}</Text>
        </Stack>
      </Paper>

      <Paper withBorder p="md" radius="md">
        <Text fw={600} mb="xs">{t("prompts.fields.title")}</Text>
        <Text size="sm" c="dimmed" mb="md">{t("prompts.fields.description")}</Text>
        <Stack gap="sm">
          {METADATA_FIELDS.map(f => (
            <Textarea
              key={f.key}
              label={f.label}
              name={`field_desc_${f.key}`}
              rows={2}
              value={fieldDescs[f.key] ?? ""}
              onChange={e => setFieldDescs(prev => ({ ...prev, [f.key]: e.target.value }))}
              placeholder={f.description}
            />
          ))}

          <Text fw={500} size="sm" mt="sm">{t("analysis.customFields")}</Text>
          {cfList.length === 0 && (
            <Text size="sm" c="dimmed">
              {customFieldsIsError ? t("prompts.fields.customFieldsError") : t("prompts.fields.noCustomFields")}
            </Text>
          )}
          {cfList.map(cf => {
            const isSelected = selectedCustomFields.includes(cf.id);
            return (
              <div key={cf.id}>
                <Checkbox
                  label={<>{cf.name} <Text span size="xs" c="dimmed">({cf.data_type})</Text></>}
                  checked={isSelected}
                  onChange={() => toggleCustomField(cf.id)}
                  mb={isSelected ? "xs" : 0}
                />
                {isSelected && (
                  <Textarea
                    name={`field_desc_cf:${cf.id}`}
                    rows={2}
                    value={fieldDescs[`cf:${cf.id}`] ?? ""}
                    onChange={e => setFieldDescs(prev => ({ ...prev, [`cf:${cf.id}`]: e.target.value }))}
                    placeholder={t("prompts.fields.customPlaceholder", { name: cf.name })}
                  />
                )}
              </div>
            );
          })}
        </Stack>
      </Paper>
    </Stack>
  );
}
