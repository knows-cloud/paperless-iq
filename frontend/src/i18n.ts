import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import LanguageDetector from "i18next-browser-languagedetector";

import en from "./locales/en/translation.json";
import de from "./locales/de/translation.json";
import fr from "./locales/fr/translation.json";
import es from "./locales/es/translation.json";
import it from "./locales/it/translation.json";
import ja from "./locales/ja/translation.json";

export type Lang = "en" | "de" | "fr" | "es" | "it" | "ja";

export const AVAILABLE_LANGS: Array<{ code: Lang; label: string }> = [
  { code: "en", label: "English" },
  { code: "de", label: "Deutsch" },
  { code: "fr", label: "Français" },
  { code: "es", label: "Español" },
  { code: "it", label: "Italiano" },
  { code: "ja", label: "Japanese" },
];

i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      de: { translation: de },
      fr: { translation: fr },
      es: { translation: es },
      it: { translation: it },
      ja: { translation: ja },
    },
    fallbackLng: "en",
    supportedLngs: ["en", "de", "fr", "es", "it", "ja"],
    interpolation: {
      prefix: "{",
      suffix: "}",
      escapeValue: false,
    },
    detection: {
      order: ["localStorage", "navigator"],
      caches: ["localStorage"],
      lookupLocalStorage: "piq_lang",
    },
    returnNull: false,
  });
