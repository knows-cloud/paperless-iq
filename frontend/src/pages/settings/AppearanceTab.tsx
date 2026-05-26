import {
  Select, Paper, Text, Divider, Stack, Group, ColorSwatch, Tooltip,
  SegmentedControl, SimpleGrid, NumberInput, Autocomplete, Anchor,
} from "@mantine/core";
import { NAV_ICON_PALETTE, NAV_ICON_NAMES, toPascal } from "./nav-icon-palette";

const MANTINE_COLORS = [
  "teal", "blue", "violet", "grape", "pink", "red",
  "orange", "yellow", "lime", "green", "cyan", "indigo",
] as const;

const NAV_ITEMS = [
  { id: "manual",     label: "Analysis",   placeholder: "file-search"    },
  { id: "queue",      label: "Queue",      placeholder: "list-check"     },
  { id: "discovery",  label: "Discovery",  placeholder: "sparkles"       },
  { id: "processing", label: "Processing", placeholder: "activity"       },
  { id: "audit",      label: "Audit",      placeholder: "clipboard-list" },
  { id: "settings",   label: "Settings",   placeholder: "settings"       },
];

interface Props {
  s: Record<string, unknown>;
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
  const paletteName = toPascal(value || item.placeholder);
  const Icon = NAV_ICON_PALETTE[paletteName];
  const isUnknown = value !== "" && !NAV_ICON_PALETTE[toPascal(value)];

  return (
    <Autocomplete
      label={item.label}
      placeholder={item.placeholder}
      value={value}
      onChange={onChange}
      data={NAV_ICON_NAMES}
      limit={8}
      size="sm"
      error={isUnknown ? "Unknown icon" : undefined}
      leftSection={Icon ? <Icon size={16} /> : null}
    />
  );
}

export function AppearanceTab({
  s,
  mantineColor, setMantineColor,
  colorScheme, setColorScheme,
  themeFont, setThemeFont,
  themeFontSize, setThemeFontSize,
  themeNavIcons, setThemeNavIcons,
}: Props) {
  return (
    <Stack gap="md">
      <Paper withBorder p="md" radius="md">
        <Text fw={600} mb="md">Theme</Text>
        <Stack gap="md">
          <div>
            <Text size="sm" fw={500} mb="xs">Color Scheme</Text>
            <SegmentedControl
              value={colorScheme}
              onChange={setColorScheme}
              data={[
                { label: "Light", value: "light" },
                { label: "Dark",  value: "dark"  },
                { label: "Auto",  value: "auto"  },
              ]}
            />
          </div>

          <div>
            <Text size="sm" fw={500} mb="xs">Primary Color</Text>
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
            <Text size="xs" c="dimmed" mt="xs">Selected: {mantineColor}</Text>
          </div>

          <Divider label="Typography" labelPosition="left" />

          <SimpleGrid cols={2}>
            <Select
              label="Font"
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
              label="Size"
              value={themeFontSize}
              onChange={v => setThemeFontSize(v ?? "14px")}
              data={["12px", "13px", "14px", "15px", "16px"].map(v => ({ value: v, label: v }))}
            />
          </SimpleGrid>

          <Divider label="Navigation Icons" labelPosition="left" />
          <Group justify="space-between" mt={-8}>
            <Text size="xs" c="dimmed">
              Type a Tabler icon name (e.g. <strong>file-text</strong>, <strong>bell</strong>).
              Leave blank to keep the default.
            </Text>
            <Anchor
              href="https://tabler.io/icons"
              target="_blank"
              rel="noopener noreferrer"
              size="xs"
            >
              Browse icons ↗
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
        <Text fw={600} mb="md">Language &amp; System</Text>
        <Stack gap="md">
          <Select
            label="Interface Language"
            name="ui_language"
            defaultValue={String(s.ui_language ?? "en")}
            description="Language for the Paperless IQ user interface. Refresh the page after saving."
            data={[
              { value: "en", label: "English"  },
              { value: "de", label: "Deutsch"  },
              { value: "fr", label: "Français" },
              { value: "es", label: "Español"  },
              { value: "it", label: "Italiano" },
            ]}
          />
          <NumberInput
            label="Audit Log Retention (days, min 90)"
            name="audit_retention_days"
            min={90}
            defaultValue={Number(s.audit_retention_days ?? 365)}
            description="Audit log entries older than this are automatically deleted."
          />
        </Stack>
      </Paper>
    </Stack>
  );
}
