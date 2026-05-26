import {
  Select, Paper, Text, Divider, Stack, Group, ColorSwatch, Tooltip,
  SegmentedControl, SimpleGrid, NumberInput,
} from "@mantine/core";

const MANTINE_COLORS = [
  "teal", "blue", "violet", "grape", "pink", "red",
  "orange", "yellow", "lime", "green", "cyan", "indigo",
] as const;

const NAV_ITEMS = [
  { id: "manual", label: "Analysis" },
  { id: "queue", label: "Queue" },
  { id: "discovery", label: "Discovery" },
  { id: "audit", label: "Audit" },
  { id: "settings", label: "Settings" },
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
  themeLogo: string;
  setThemeLogo: (v: string) => void;
  themeNavIcons: Record<string, string>;
  setThemeNavIcons: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  logoNames: string[];
}

export function AppearanceTab({
  s,
  mantineColor, setMantineColor,
  colorScheme, setColorScheme,
  themeFont, setThemeFont,
  themeFontSize, setThemeFontSize,
  themeLogo, setThemeLogo,
  themeNavIcons, setThemeNavIcons,
  logoNames,
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
                { label: "Dark", value: "dark" },
                { label: "Auto", value: "auto" },
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
                      outline: mantineColor === color ? "3px solid var(--mantine-color-teal-5)" : "2px solid transparent",
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
                { value: "Roboto", label: "Roboto" },
                { value: "Open Sans", label: "Open Sans" },
                { value: "Inter", label: "Inter" },
                { value: "Fira Sans", label: "Fira Sans" },
                { value: "Source Sans 3", label: "Source Sans 3" },
                { value: "Nunito", label: "Nunito" },
                { value: "Ubuntu", label: "Ubuntu" },
                { value: "Noto Sans", label: "Noto Sans (full Unicode)" },
                { value: "JetBrains Mono", label: "JetBrains Mono" },
                { value: "Fira Code", label: "Fira Code" },
              ]}
            />
            <Select
              label="Size"
              value={themeFontSize}
              onChange={v => setThemeFontSize(v ?? "14px")}
              data={["12px", "13px", "14px", "15px", "16px"].map(v => ({ value: v, label: v }))}
            />
          </SimpleGrid>

          <Divider label="Branding" labelPosition="left" />

          {logoNames.length > 0 && (
            <div>
              <Text size="sm" fw={500} mb="xs">Logo</Text>
              <Group gap="sm">
                {logoNames.map(name => (
                  <div
                    key={name}
                    onClick={() => setThemeLogo(name)}
                    style={{
                      cursor: "pointer", padding: "0.35rem", borderRadius: "var(--mantine-radius-sm)",
                      border: themeLogo === name
                        ? "2px solid var(--mantine-color-teal-5)"
                        : "2px solid var(--mantine-color-default-border)",
                      background: themeLogo === name ? "var(--mantine-color-teal-0)" : "transparent",
                    }}
                  >
                    <img src={`/logos/${name}`} alt={name}
                      style={{ width: "48px", height: "48px", objectFit: "contain", display: "block" }} />
                  </div>
                ))}
              </Group>
            </div>
          )}

          <div>
            <Text size="sm" fw={500} mb={4}>Navigation Icons</Text>
            <Text size="xs" c="dimmed" mb="xs">Emoji or Unicode symbol for each section.</Text>
            <Group gap="sm">
              {NAV_ITEMS.map(item => (
                <div key={item.id} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: "0.2rem" }}>
                  <input
                    value={themeNavIcons[item.id] ?? ""}
                    onChange={e => setThemeNavIcons(prev => ({ ...prev, [item.id]: e.target.value }))}
                    style={{
                      width: "3rem", textAlign: "center", fontSize: "1.1rem", padding: "0.3rem",
                      background: "var(--mantine-color-default)", border: "1px solid var(--mantine-color-default-border)",
                      borderRadius: "var(--mantine-radius-sm)", color: "inherit",
                    }}
                  />
                  <Text size="xs" c="dimmed">{item.label}</Text>
                </div>
              ))}
            </Group>
          </div>
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
              { value: "en", label: "English" },
              { value: "de", label: "Deutsch" },
              { value: "fr", label: "Français" },
              { value: "es", label: "Español" },
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
