import { useEffect, useState } from "react";
import { Anchor, Badge, Group, Text, Tooltip } from "@mantine/core";
import { IconArrowUpCircle } from "@tabler/icons-react";
import { useTranslation } from "react-i18next";
import { api } from "../api";
import type { VersionInfo } from "../api";

export default function VersionBadge() {
  const { t } = useTranslation();
  const [info, setInfo] = useState<VersionInfo | null>(null);

  useEffect(() => {
    api.getVersion().then(setInfo).catch(() => {});
  }, []);

  if (!info) return null;

  return (
    <Group gap={6} wrap="nowrap" align="center">
      <Text size="xs" c="dimmed">v{info.version}</Text>
      {info.update_available && info.releases_url && (
        <Tooltip label={t("version.updateTooltip", { latest: info.latest_version })} withArrow>
          <Anchor href={info.releases_url} target="_blank" rel="noopener noreferrer" style={{ lineHeight: 1 }}>
            <Badge
              size="xs"
              variant="light"
              color="teal"
              leftSection={<IconArrowUpCircle size={10} />}
              styles={{ root: { cursor: "pointer" } }}
            >
              {t("version.updateAvailable")}
            </Badge>
          </Anchor>
        </Tooltip>
      )}
    </Group>
  );
}
