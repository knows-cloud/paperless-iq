import { Textarea, TextInput, Select, Button, Checkbox, Paper, Text, Stack, Group } from "@mantine/core";
import { api, type PaperlessCustomField } from "../../api";
import { METADATA_FIELDS } from "./constants";

interface Props {
  s: Record<string, unknown>;
  promptText: string;
  setPromptText: (v: string) => void;
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
  translateLang, setTranslateLang,
  translating, setTranslating,
  fieldDescs, setFieldDescs,
  selectedCustomFields, toggleCustomField,
  cfList, customFieldsIsError,
}: Props) {
  return (
    <Stack gap="md">
      <Paper withBorder p="md" radius="md">
        <Text fw={600} mb="md">System Prompt</Text>
        <Stack gap="md">
          <Textarea
            label="Global prompt — system instruction sent to the LLM with every document"
            name="global_prompt_template"
            rows={10}
            value={promptText}
            onChange={e => setPromptText(e.target.value)}
            styles={{ input: { fontFamily: "monospace", fontSize: "0.85rem" } }}
          />
          <Group gap="xs" align="flex-end">
            <Text size="xs" c="dimmed" style={{ flex: 1 }}>Use {"{{content}}"} as placeholder for document text.</Text>
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
              Translate
            </Button>
          </Group>
          <TextInput
            label="LLM Output Language"
            name="target_language"
            defaultValue={String(s.target_language ?? "")}
            placeholder="e.g. de, fr, es (leave empty for English)"
            description="Language the LLM should use for metadata values (title, tags, etc.). Leave empty for English."
          />
        </Stack>
      </Paper>

      <Paper withBorder p="md" radius="md">
        <Text fw={600} mb="xs">Field Instructions</Text>
        <Text size="sm" c="dimmed" mb="md">
          Give the LLM specific instructions for each metadata field. Leave blank to let it decide based on the system prompt alone.
        </Text>
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

          <Text fw={500} size="sm" mt="sm">Custom Fields</Text>
          {cfList.length === 0 && (
            <Text size="sm" c="dimmed">
              {customFieldsIsError ? "Cannot load custom fields from Paperless NGX." : "No custom fields found."}
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
                    placeholder={`Instructions for custom field "${cf.name}"`}
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
