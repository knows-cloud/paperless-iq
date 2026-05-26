import { Switch, NumberInput, Paper, Text, Stack } from "@mantine/core";

interface Props {
  s: Record<string, unknown>;
}

export function MetadataRulesTab({ s }: Props) {
  return (
    <Stack gap="md">
      <Paper withBorder p="md" radius="md">
        <Text fw={600} mb="xs">Smart Entity Selection</Text>
        <Text size="sm" c="dimmed" mb="md">
          When enabled, Paperless IQ finds processed documents similar to the one being analyzed
          and sends only their tags, correspondents, and types to the LLM as candidates.
          This reduces prompt size and significantly improves suggestion accuracy.
        </Text>
        <Stack gap="md">
          <Switch
            name="smart_entity_selection"
            label="Enable smart entity selection"
            defaultChecked={Boolean(s.smart_entity_selection ?? true)}
          />
          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
            <NumberInput
              label="Similar documents to consider"
              name="similar_docs_count"
              min={1}
              max={50}
              defaultValue={Number(s.similar_docs_count ?? 10)}
              description="How many similar processed documents to draw entity candidates from."
              style={{ flex: 1, minWidth: "180px" }}
            />
            <NumberInput
              label="Frequency fallback count"
              name="frequency_fallback_count"
              min={0}
              max={100}
              defaultValue={Number(s.frequency_fallback_count ?? 20)}
              description="Top-N most-used entities added as fallback (handles cold-start and rare categories)."
              style={{ flex: 1, minWidth: "180px" }}
            />
          </div>
        </Stack>
      </Paper>

    </Stack>
  );
}
