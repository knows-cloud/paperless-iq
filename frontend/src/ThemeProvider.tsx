import { createContext, useContext, useEffect, useMemo, useState } from "react";
import { MantineProvider, createTheme, useMantineColorScheme } from "@mantine/core";
import type { MantineColorScheme } from "@mantine/core";
import { api } from "./api";
import { setLang, type Lang } from "./i18n";

interface ThemeConfig {
  mantine_color: string;
  font: string;
  color_scheme: MantineColorScheme;
  logo: string;
  nav_icons: Record<string, string>;
}

const DEFAULT: ThemeConfig = {
  mantine_color: "teal",
  font: "",
  color_scheme: "dark",
  logo: "",
  nav_icons: {},
};

const ThemeConfigContext = createContext<ThemeConfig>(DEFAULT);
export function useTheme() { return useContext(ThemeConfigContext); }

// Reads server theme and applies color scheme + language. Runs inside MantineProvider.
function ThemeSync({ onLoad }: { onLoad: (c: ThemeConfig) => void }) {
  const { setColorScheme } = useMantineColorScheme();

  useEffect(() => {
    api.getTheme().then(t => {
      const cfg: ThemeConfig = {
        mantine_color: (t as Record<string, unknown>).mantine_color as string ?? "teal",
        font: t.font ?? "",
        color_scheme: ((t as Record<string, unknown>).color_scheme as MantineColorScheme) ?? "dark",
        logo: t.logo ?? "iq_1.png",
        nav_icons: t.nav_icons ?? DEFAULT.nav_icons,
      };
      setColorScheme(cfg.color_scheme);
      if (t.ui_language) setLang(t.ui_language as Lang);
      onLoad(cfg);
    }).catch(() => { /* keep defaults */ });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return null;
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [config, setConfig] = useState<ThemeConfig>(DEFAULT);

  const theme = useMemo(() => createTheme({
    primaryColor: config.mantine_color,
    fontFamily: config.font ? `'${config.font}', system-ui, sans-serif` : undefined,
  }), [config.mantine_color, config.font]);

  return (
    <MantineProvider theme={theme} defaultColorScheme="dark">
      <ThemeSync onLoad={setConfig} />
      <ThemeConfigContext.Provider value={config}>
        {children}
      </ThemeConfigContext.Provider>
    </MantineProvider>
  );
}
