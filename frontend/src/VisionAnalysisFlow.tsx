/**
 * VisionAnalysisFlow — reusable trigger for full-document vision analysis.
 *
 * Handles:
 *   1. Options modal (include_content checkbox)
 *   2. Page-count fetch + warning modal (Keep / Limit / Cancel) when count > threshold
 *   3. Vision API call with loading state
 *   4. ContentDiffModal (side-by-side OCR vs extracted) when include_content is true
 */

import { useState } from "react";
import {
  Button, Modal, Stack, Checkbox, Text, Group, Loader, ScrollArea,
  Box, Alert,
} from "@mantine/core";
import { api, type VisionAnalysisResult } from "./api";
import { useTranslation } from "react-i18next";

interface Props {
  documentId: number;
  /** Threshold from settings (vision_max_pages_warning). */
  pageWarningThreshold: number;
  /** Called with the result when analysis completes. */
  onResult: (result: VisionAnalysisResult) => void;
  size?: "xs" | "sm" | "md";
  disabled?: boolean;
  /** Whether the configured provider is Ollama AND the model lacks vision. */
  ollamaVisionWarning?: boolean;
}

type FlowStep =
  | "idle"
  | "options"       // options modal (include_content checkbox)
  | "fetchingCount" // fetching page count in background
  | "pageWarning"   // page-count warning modal
  | "analyzing"     // LLM call in progress
  | "diff";         // content diff modal

export default function VisionAnalysisFlow({
  documentId,
  pageWarningThreshold,
  onResult,
  size = "sm",
  disabled = false,
  ollamaVisionWarning = false,
}: Props) {
  const { t } = useTranslation();
  const [step, setStep] = useState<FlowStep>("idle");
  const [includeContent, setIncludeContent] = useState(false);
  const [pageCount, setPageCount] = useState<number | null>(null);
  const [_maxPages, setMaxPages] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [diffResult, setDiffResult] = useState<VisionAnalysisResult | null>(null);
  const [updatingContent, setUpdatingContent] = useState(false);

  const reset = () => {
    setStep("idle");
    setIncludeContent(false);
    setPageCount(null);
    setMaxPages(null);
    setError(null);
    setDiffResult(null);
  };

  const runAnalysis = async (mp: number | null) => {
    setMaxPages(mp);
    setStep("analyzing");
    setError(null);
    try {
      const result = await api.analyzeVision({
        document_id: documentId,
        include_content: includeContent,
        max_pages: mp,
      });
      if (includeContent && result.extracted_content) {
        setDiffResult(result);
        setStep("diff");
      } else {
        onResult(result);
        reset();
      }
    } catch (err: unknown) {
      setError((err as Error).message);
      setStep("options");
    }
  };

  const handleConfirmOptions = async () => {
    setStep("fetchingCount");
    setError(null);
    try {
      const { page_count } = await api.getDocumentPageCount(documentId);
      setPageCount(page_count);
      if (page_count > pageWarningThreshold) {
        setStep("pageWarning");
      } else {
        await runAnalysis(null);
      }
    } catch (err: unknown) {
      setError((err as Error).message);
      setStep("options");
    }
  };

  const handleReplaceContent = async () => {
    if (!diffResult?.extracted_content) return;
    setUpdatingContent(true);
    try {
      await api.updateDocumentContent(documentId, diffResult.extracted_content);
    } catch {
      // Non-fatal — metadata was already applied
    } finally {
      setUpdatingContent(false);
      onResult(diffResult);
      reset();
    }
  };

  return (
    <>
      {/* Trigger button */}
      <Button
        size={size}
        variant="light"
        disabled={disabled}
        onClick={() => setStep("options")}
      >
        {t("vision.analyzeFullDocument")}
      </Button>

      {/* ── Options modal ── */}
      <Modal
        opened={step === "options" || step === "fetchingCount"}
        onClose={reset}
        title={t("vision.analyzeFullDocument")}
        size="sm"
      >
        <Stack gap="md">
          {ollamaVisionWarning && (
            <Alert color="orange" variant="light">
              {t("vision.ollamaVisionWarning")}
            </Alert>
          )}
          <Text size="sm" c="dimmed">
            {t("vision.optionsDescription")}
          </Text>
          <Checkbox
            label={t("vision.includeContent")}
            description={t("vision.includeContentDescription")}
            checked={includeContent}
            onChange={e => setIncludeContent(e.currentTarget.checked)}
          />
          {error && <Text size="sm" c="red">{error}</Text>}
          <Group justify="flex-end" gap="xs">
            <Button variant="default" size="sm" onClick={reset}>
              {t("common.cancel")}
            </Button>
            <Button
              size="sm"
              onClick={handleConfirmOptions}
              loading={step === "fetchingCount"}
            >
              {t("common.analyze")}
            </Button>
          </Group>
        </Stack>
      </Modal>

      {/* ── Page-count warning modal ── */}
      <Modal
        opened={step === "pageWarning"}
        onClose={reset}
        title={t("vision.pageLimitWarningTitle")}
        size="sm"
      >
        <Stack gap="md">
          <Text size="sm">
            {t("vision.pageLimitWarning", {
              count: String(pageCount ?? "?"),
              threshold: String(pageWarningThreshold),
            })}
          </Text>
          <Text size="sm" c="dimmed">{t("vision.pageLimitCostNote")}</Text>
          <Group justify="flex-end" gap="xs">
            <Button variant="default" size="sm" onClick={reset}>
              {t("common.cancel")}
            </Button>
            <Button
              variant="light"
              size="sm"
              onClick={() => runAnalysis(pageWarningThreshold)}
            >
              {t("vision.limitPages", { n: String(pageWarningThreshold) })}
            </Button>
            <Button size="sm" onClick={() => runAnalysis(null)}>
              {t("vision.sendAll", { count: String(pageCount ?? "?") })}
            </Button>
          </Group>
        </Stack>
      </Modal>

      {/* ── Analyzing spinner ── */}
      <Modal
        opened={step === "analyzing"}
        onClose={() => {}}
        withCloseButton={false}
        title={t("common.analyzing")}
        size="sm"
      >
        <Group gap="sm" p="md">
          <Loader size="sm" />
          <Text size="sm">{t("vision.analyzingDescription")}</Text>
        </Group>
      </Modal>

      {/* ── Content diff modal ── */}
      <Modal
        opened={step === "diff"}
        onClose={() => { onResult(diffResult!); reset(); }}
        title={t("vision.contentDiffTitle")}
        size="xl"
      >
        <Stack gap="md">
          <Text size="sm" c="dimmed">{t("vision.contentDiffDescription")}</Text>
          <Group align="flex-start" gap="md" grow>
            <Box style={{ flex: 1 }}>
              <Text size="xs" fw={600} c="dimmed" mb={4}>{t("vision.originalOcr")}</Text>
              <ScrollArea h={400}>
                <Box
                  p="xs"
                  style={{
                    background: "var(--mantine-color-default-border)",
                    borderRadius: "var(--mantine-radius-sm)",
                    fontFamily: "monospace",
                    fontSize: "var(--mantine-font-size-xs)",
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                  }}
                >
                  {diffResult?.original_ocr_content || t("vision.noContent")}
                </Box>
              </ScrollArea>
            </Box>
            <Box style={{ flex: 1 }}>
              <Text size="xs" fw={600} c="teal" mb={4}>{t("vision.visionExtracted")}</Text>
              <ScrollArea h={400}>
                <Box
                  p="xs"
                  style={{
                    background: "var(--mantine-color-teal-0)",
                    borderRadius: "var(--mantine-radius-sm)",
                    fontFamily: "monospace",
                    fontSize: "var(--mantine-font-size-xs)",
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                  }}
                >
                  {diffResult?.extracted_content || t("vision.noContent")}
                </Box>
              </ScrollArea>
            </Box>
          </Group>
          <Group justify="flex-end" gap="xs">
            <Button
              variant="default"
              size="sm"
              onClick={() => { onResult(diffResult!); reset(); }}
            >
              {t("vision.keepOriginal")}
            </Button>
            <Button
              size="sm"
              loading={updatingContent}
              onClick={handleReplaceContent}
            >
              {t("vision.replaceContent")}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
}
