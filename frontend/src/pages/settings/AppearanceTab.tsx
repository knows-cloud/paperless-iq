import {
  Select, Paper, Text, Divider, Stack, Group, ColorSwatch, Tooltip,
  SegmentedControl, SimpleGrid, Autocomplete, Anchor,
} from "@mantine/core";
import { useTranslation } from "react-i18next";
import { AVAILABLE_LANGS } from "../../i18n";
import { NAV_ICON_PALETTE, NAV_ICON_NAMES, toPascal } from "./nav-icon-palette";

const MANTINE_COLORS = [
  "teal", "blue", "violet", "grape", "pink", "red",
  "orange", "yellow", "lime", "green", "cyan", "indigo",
] as const;

const NAV_ITEMS = [
  { id: "manual",     key: "nav.analysis",   placeholder: "file-search"    },
  { id: "queue",      key: "nav.queue",      placeholder: "list-check"     },
  { id: "discovery",  key: "nav.discovery",  placeholder: "sparkles"       },
  { id: "processing", key: "nav.processing", placeholder: "activity"       },
  { id: "audit",      key: "nav.audit",      placeholder: "clipboard-list" },
  { id: "settings",   key: "nav.settings",   placeholder: "settings"       },
];

interface Props {
  mantineColor: string;
  setMantineColor: (v: string) => void;
  colorScheme: string;
  setColorScheme: (v: string) => void;
  themeFont: string;
  setThemeFont: (v: string) => void;
  themeFontSize: string;
  setThemeFontSize: (v: string) => void;
  themeNavIcons: Record<string, string>;
  setThemeNavIcons: React.Dispatch<React.SetStateAction<Record<string, string>>>;
}

function NavIconInput({
  item,
  value,
  onChange,
}: {
  item: typeof NAV_ITEMS[0];
  value: string;      // stored as kebab-case
  onChange: (v: string) => void;
}) {
  const { t } = useTranslation();
  const paletteName = toPascal(value || item.placeholder);
  const Icon = NAV_ICON_PALETTE[paletteName];
  const isUnknown = value !== "" && !NAV_ICON_PALETTE[toPascal(value)];

  return (
    <Autocomplete
      label={t(item.key)}
      placeholder={item.placeholder}
      value={value}
      onChange={onChange}
      data={NAV_ICON_NAMES}
      limit={8}
      size="sm"
      error={isUnknown ? t("appearance.navIconUnknown") : undefined}
      leftSection={Icon ? <Icon size={16} /> : null}
    />
  );
}

export function AppearanceTab({
  mantineColor, setMantineColor,
  colorScheme, setColorScheme,
  themeFont, setThemeFont,
  themeFontSize, setThemeFontSize,
  themeNavIcons, setThemeNavIcons,
}: Props) {
  const { t, i18n } = useTranslation();
  return (
    <Stack gap="md">
      <Paper withBorder p="md" radius="md">
        <Text fw={600} mb="md">{t("appearance.theme")}</Text>
        <Stack gap="md">
          <div>
            <Text size="sm" fw={500} mb="xs">{t("appearance.colorScheme")}</Text>
            <SegmentedControl
              value={colorScheme}
              onChange={setColorScheme}
              data={[
                { label: t("appearance.light"), value: "light" },
                { label: t("appearance.dark"),  value: "dark"  },
                { label: t("appearance.auto"),  value: "auto"  },
              ]}
            />
          </div>

          <div>
            <Text size="sm" fw={500} mb="xs">{t("appearance.primaryColor")}</Text>
            <Group gap="xs">
              {MANTINE_COLORS.map(color => (
                <Tooltip key={color} label={color} withArrow>
                  <ColorSwatch
                    color={`var(--mantine-color-${color}-6)`}
                    onClick={() => setMantineColor(color)}
                    style={{
                      cursor: "pointer",
                      outline: mantineColor === color
                        ? "3px solid var(--mantine-color-teal-5)"
                        : "2px solid transparent",
                      outlineOffset: "2px",
                    }}
                  />
                </Tooltip>
              ))}
            </Group>
            <Text size="xs" c="dimmed" mt="xs">{t("appearance.selected", { color: mantineColor })}</Text>
          </div>

          <Divider label={t("appearance.typography")} labelPosition="left" />

          <SimpleGrid cols={2}>
            <Select
              label={t("appearance.font")}
              value={themeFont}
              onChange={v => setThemeFont(v ?? "Roboto")}
              data={[
                { value: "Roboto",        label: "Roboto"               },
                { value: "Open Sans",     label: "Open Sans"            },
                { value: "Inter",         label: "Inter"                },
                { value: "Fira Sans",     label: "Fira Sans"            },
                { value: "Source Sans 3", label: "Source Sans 3"        },
                { value: "Nunito",        label: "Nunito"               },
                { value: "Ubuntu",        label: "Ubuntu"               },
                { value: "Noto Sans",     label: "Noto Sans (full Unicode)" },
                { value: "JetBrains Mono",label: "JetBrains Mono"      },
                { value: "Fira Code",     label: "Fira Code"           },
              ]}
            />
            <Select
              label={t("appearance.size")}
              value={themeFontSize}
              onChange={v => setThemeFontSize(v ?? "14px")}
              data={["12px", "13px", "14px", "15px", "16px"].map(v => ({ value: v, label: v }))}
            />
          </SimpleGrid>

          <Divider label={t("appearance.navIcons")} labelPosition="left" />
          <Group justify="space-between" mt={-8}>
            <Text size="xs" c="dimmed">{t("appearance.navIconsHint")}</Text>
            <Anchor
              href="https://tabler.io/icons"
              target="_blank"
              rel="noopener noreferrer"
              size="xs"
            >
              {t("appearance.browseIcons")}
            </Anchor>
          </Group>

          <SimpleGrid cols={3}>
            {NAV_ITEMS.map(item => (
              <NavIconInput
                key={item.id}
                item={item}
                value={themeNavIcons[item.id] ?? ""}
                onChange={v => setThemeNavIcons(prev => ({ ...prev, [item.id]: v }))}
              />
            ))}
          </SimpleGrid>
        </Stack>
      </Paper>

      <Paper withBorder p="md" radius="md">
        <Text fw={600} mb="md">{t("appearance.language")}</Text>
        <Select
          label={t("appearance.interfaceLanguage")}
          value={i18n.language}
          description={t("appearance.languageImmediate")}
          data={AVAILABLE_LANGS.map(l => ({ value: l.code, label: l.label }))}
          onChange={v => { if (v) i18n.changeLanguage(v); }}
        />
      </Paper>
    </Stack>
  );
}
