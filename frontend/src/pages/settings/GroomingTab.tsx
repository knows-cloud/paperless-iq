import { Stack, Paper, Text, Switch, MultiSelect, NumberInput, TextInput, Divider } from "@mantine/core";
import { useTranslation } from "react-i18next";
import { InfoLabel } from "../../components/InfoLabel";
import { GROOMING_ENTITY_TYPES } from "./constants";

interface Props {
  groomingEnabled: boolean;
  setGroomingEnabled: (v: boolean) => void;
  groomingEntityTypes: string[];
  setGroomingEntityTypes: (v: string[]) => void;
  groomingDedupNameThreshold: number;
  setGroomingDedupNameThreshold: (v: number) => void;
  groomingDedupEmbedThreshold: number;
  setGroomingDedupEmbedThreshold: (v: number) => void;
  groomingDescSampleDocs: number;
  setGroomingDescSampleDocs: (v: number) => void;
  groomingDescSnippetChars: number;
  setGroomingDescSnippetChars: (v: number) => void;
  groomingAddThreshold: number;
  setGroomingAddThreshold: (v: number) => void;
  groomingRemoveThreshold: number;
  setGroomingRemoveThreshold: (v: number) => void;
  groomingRemovePercentile: number;
  setGroomingRemovePercentile: (v: number) => void;
  groomingMinSupportingChunks: number;
  setGroomingMinSupportingChunks: (v: number) => void;
  groomingScanTopK: number;
  setGroomingScanTopK: (v: number) => void;
  groomingMaxSuggestionsPerScan: number;
  setGroomingMaxSuggestionsPerScan: (v: number) => void;
  groomingScanCron: string;
  setGroomingScanCron: (v: string) => void;
  groomingResuggestAfterDays: number;
  setGroomingResuggestAfterDays: (v: number) => void;
}

export function GroomingTab({
  groomingEnabled, setGroomingEnabled,
  groomingEntityTypes, setGroomingEntityTypes,
  groomingDedupNameThreshold, setGroomingDedupNameThreshold,
  groomingDedupEmbedThreshold, setGroomingDedupEmbedThreshold,
  groomingDescSampleDocs, setGroomingDescSampleDocs,
  groomingDescSnippetChars, setGroomingDescSnippetChars,
  groomingAddThreshold, setGroomingAddThreshold,
  groomingRemoveThreshold, setGroomingRemoveThreshold,
  groomingRemovePercentile, setGroomingRemovePercentile,
  groomingMinSupportingChunks, setGroomingMinSupportingChunks,
  groomingScanTopK, setGroomingScanTopK,
  groomingMaxSuggestionsPerScan, setGroomingMaxSuggestionsPerScan,
  groomingScanCron, setGroomingScanCron,
  groomingResuggestAfterDays, setGroomingResuggestAfterDays,
}: Props) {
  const { t } = useTranslation();

  return (
    <Stack gap="md">
      {/* General */}
      <Paper withBorder p="md" radius="md">
        <Text fw={600} mb="md">{t("grooming.settings.general.title")}</Text>
        <Stack gap="md">
          <Switch
            label={<InfoLabel label={t("grooming.settings.general.enabled.label")} tip={t("grooming.settings.general.enabled.tip")} />}
            checked={groomingEnabled}
            onChange={e => setGroomingEnabled(e.currentTarget.checked)}
          />
          <MultiSelect
            label={<InfoLabel label={t("grooming.settings.general.entityTypes.label")} tip={t("grooming.settings.general.entityTypes.tip")} />}
            value={groomingEntityTypes}
            onChange={setGroomingEntityTypes}
            data={GROOMING_ENTITY_TYPES.map(e => ({ value: e.value, label: t(e.labelKey) }))}
          />
        </Stack>
      </Paper>

      {/* Description generation */}
      <Paper withBorder p="md" radius="md">
        <Text fw={600} mb="md">{t("grooming.settings.descriptions.title")}</Text>
        <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
          <NumberInput
            label={<InfoLabel label={t("grooming.settings.descriptions.sampleDocs.label")} tip={t("grooming.settings.descriptions.sampleDocs.tip")} />}
            value={groomingDescSampleDocs}
            onChange={v => setGroomingDescSampleDocs(Number(v))}
            min={1}
            max={50}
            style={{ flex: 1, minWidth: "160px" }}
          />
          <NumberInput
            label={<InfoLabel label={t("grooming.settings.descriptions.snippetChars.label")} tip={t("grooming.settings.descriptions.snippetChars.tip")} />}
            value={groomingDescSnippetChars}
            onChange={v => setGroomingDescSnippetChars(Number(v))}
            min={100}
            max={2000}
            style={{ flex: 1, minWidth: "160px" }}
          />
        </div>
      </Paper>

      {/* Deduplication thresholds */}
      <Paper withBorder p="md" radius="md">
        <Text fw={600} mb="md">{t("grooming.settings.dedup.title")}</Text>
        <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
          <NumberInput
            label={<InfoLabel label={t("grooming.settings.dedup.nameThreshold.label")} tip={t("grooming.settings.dedup.nameThreshold.tip")} />}
            value={groomingDedupNameThreshold}
            onChange={v => setGroomingDedupNameThreshold(Number(v))}
            min={0}
            max={1}
            step={0.05}
            decimalScale={2}
            style={{ flex: 1, minWidth: "160px" }}
          />
          <NumberInput
            label={<InfoLabel label={t("grooming.settings.dedup.embedThreshold.label")} tip={t("grooming.settings.dedup.embedThreshold.tip")} />}
            value={groomingDedupEmbedThreshold}
            onChange={v => setGroomingDedupEmbedThreshold(Number(v))}
            min={0}
            max={1}
            step={0.05}
            decimalScale={2}
            style={{ flex: 1, minWidth: "160px" }}
          />
        </div>
      </Paper>

      {/* Scan / suggestion thresholds */}
      <Paper withBorder p="md" radius="md">
        <Text fw={600} mb="md">{t("grooming.settings.scan.title")}</Text>
        <Stack gap="md">
          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
            <NumberInput
              label={<InfoLabel label={t("grooming.settings.scan.addThreshold.label")} tip={t("grooming.settings.scan.addThreshold.tip")} />}
              value={groomingAddThreshold}
              onChange={v => setGroomingAddThreshold(Number(v))}
              min={0}
              max={1}
              step={0.05}
              decimalScale={2}
              style={{ flex: 1, minWidth: "160px" }}
            />
            <NumberInput
              label={<InfoLabel label={t("grooming.settings.scan.removeThreshold.label")} tip={t("grooming.settings.scan.removeThreshold.tip")} />}
              value={groomingRemoveThreshold}
              onChange={v => setGroomingRemoveThreshold(Number(v))}
              min={0}
              max={1}
              step={0.05}
              decimalScale={2}
              style={{ flex: 1, minWidth: "160px" }}
            />
            <NumberInput
              label={<InfoLabel label={t("grooming.settings.scan.removePercentile.label")} tip={t("grooming.settings.scan.removePercentile.tip")} />}
              value={groomingRemovePercentile}
              onChange={v => setGroomingRemovePercentile(Number(v))}
              min={1}
              max={50}
              style={{ flex: 1, minWidth: "160px" }}
            />
          </div>
          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
            <NumberInput
              label={<InfoLabel label={t("grooming.settings.scan.minSupportingChunks.label")} tip={t("grooming.settings.scan.minSupportingChunks.tip")} />}
              value={groomingMinSupportingChunks}
              onChange={v => setGroomingMinSupportingChunks(Number(v))}
              min={1}
              max={20}
              style={{ flex: 1, minWidth: "160px" }}
            />
            <NumberInput
              label={<InfoLabel label={t("grooming.settings.scan.topK.label")} tip={t("grooming.settings.scan.topK.tip")} />}
              value={groomingScanTopK}
              onChange={v => setGroomingScanTopK(Number(v))}
              min={10}
              max={500}
              style={{ flex: 1, minWidth: "160px" }}
            />
            <NumberInput
              label={<InfoLabel label={t("grooming.settings.scan.maxSuggestions.label")} tip={t("grooming.settings.scan.maxSuggestions.tip")} />}
              value={groomingMaxSuggestionsPerScan}
              onChange={v => setGroomingMaxSuggestionsPerScan(Number(v))}
              min={1}
              max={500}
              style={{ flex: 1, minWidth: "160px" }}
            />
          </div>
          <Divider label={t("grooming.settings.scan.scheduleDivider")} labelPosition="left" />
          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
            <TextInput
              label={<InfoLabel label={t("grooming.settings.scan.cron.label")} tip={t("grooming.settings.scan.cron.tip")} />}
              value={groomingScanCron}
              onChange={e => setGroomingScanCron(e.target.value)}
              placeholder="0 2 * * *"
              style={{ flex: 2, minWidth: "200px" }}
            />
            <NumberInput
              label={<InfoLabel label={t("grooming.settings.scan.resuggestDays.label")} tip={t("grooming.settings.scan.resuggestDays.tip")} />}
              value={groomingResuggestAfterDays}
              onChange={v => setGroomingResuggestAfterDays(Number(v))}
              min={0}
              max={365}
              style={{ flex: 1, minWidth: "160px" }}
            />
          </div>
        </Stack>
      </Paper>
    </Stack>
  );
}
