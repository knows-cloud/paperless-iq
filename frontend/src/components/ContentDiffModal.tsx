/**
 * ContentDiffModal — side-by-side view of a document's current OCR text and the
 * content transcribed by full-document (vision) analysis.
 *
 * Presentational only: callers supply the two texts and the footer actions
 * (e.g. Keep / Replace in the analysis flow, or just Close in the queue).
 */

import type { ReactNode } from "react";
import { Modal, Stack, Text, Group, ScrollArea, Box } from "@mantine/core";
import { useTranslation } from "react-i18next";

interface Props {
  opened: boolean;
  onClose: () => void;
  originalOcr: string | null | undefined;
  extracted: string | null | undefined;
  /** Action buttons rendered in the footer. */
  footer?: ReactNode;
}

const paneStyle = (tint: boolean) => ({
  background: tint ? "var(--mantine-color-teal-0)" : "var(--mantine-color-default-border)",
  borderRadius: "var(--mantine-radius-sm)",
  fontFamily: "monospace",
  fontSize: "var(--mantine-font-size-xs)",
  whiteSpace: "pre-wrap" as const,
  wordBreak: "break-word" as const,
});

export function ContentDiffModal({ opened, onClose, originalOcr, extracted, footer }: Props) {
  const { t } = useTranslation();
  return (
    <Modal opened={opened} onClose={onClose} title={t("vision.contentDiffTitle")} size="xl">
      <Stack gap="md">
        <Text size="sm" c="dimmed">{t("vision.contentDiffDescription")}</Text>
        <Group align="flex-start" gap="md" grow>
          <Box style={{ flex: 1 }}>
            <Text size="xs" fw={600} c="dimmed" mb={4}>{t("vision.originalOcr")}</Text>
            <ScrollArea h={400}>
              <Box p="xs" style={paneStyle(false)}>
                {originalOcr || t("vision.noContent")}
              </Box>
            </ScrollArea>
          </Box>
          <Box style={{ flex: 1 }}>
            <Text size="xs" fw={600} c="teal" mb={4}>{t("vision.visionExtracted")}</Text>
            <ScrollArea h={400}>
              <Box p="xs" style={paneStyle(true)}>
                {extracted || t("vision.noContent")}
              </Box>
            </ScrollArea>
          </Box>
        </Group>
        {footer && <Group justify="flex-end" gap="xs">{footer}</Group>}
      </Stack>
    </Modal>
  );
}
