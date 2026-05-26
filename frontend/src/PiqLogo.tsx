import { useMantineTheme } from "@mantine/core";

interface Props {
  size?: number;
}

export function PiqLogo({ size = 30 }: Props) {
  const theme = useMantineTheme();
  const primary = theme.colors[theme.primaryColor][5];
  const ff = theme.fontFamily ?? "system-ui, sans-serif";

  return (
    <span
      aria-label="Paperless IQ"
      style={{
        fontFamily: ff,
        fontSize: size,
        lineHeight: 1,
        letterSpacing: "-0.04em",
        userSelect: "none",
        display: "inline-block",
      }}
    >
      <span style={{ fontWeight: 200, color: primary }}>p</span>
      <span style={{ fontWeight: 900, color: "var(--mantine-color-text)" }}>IQ</span>
    </span>
  );
}
