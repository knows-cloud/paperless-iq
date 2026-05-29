#!/usr/bin/env node
/**
 * Checks that all locale translation files have an identical key set.
 * Run via: node scripts/check-i18n.mjs
 * Or wire into package.json: "check:i18n": "node scripts/check-i18n.mjs"
 */

import { readFileSync, readdirSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const LOCALES_DIR = join(__dirname, "../src/locales");
const REFERENCE_LANG = "en";

function getKeys(obj, prefix = "") {
  return Object.entries(obj).flatMap(([k, v]) => {
    const full = prefix ? `${prefix}.${k}` : k;
    return typeof v === "object" && v !== null ? getKeys(v, full) : [full];
  });
}

const langs = readdirSync(LOCALES_DIR);
const reference = JSON.parse(
  readFileSync(join(LOCALES_DIR, REFERENCE_LANG, "translation.json"), "utf8")
);
const refKeys = new Set(getKeys(reference));

let failed = false;

for (const lang of langs) {
  if (lang === REFERENCE_LANG) continue;
  const data = JSON.parse(
    readFileSync(join(LOCALES_DIR, lang, "translation.json"), "utf8")
  );
  const keys = new Set(getKeys(data));

  const missing = [...refKeys].filter(k => !keys.has(k));
  const extra = [...keys].filter(k => !refKeys.has(k));

  if (missing.length || extra.length) {
    failed = true;
    console.error(`\n❌ ${lang}/translation.json:`);
    if (missing.length) console.error(`   Missing keys:\n     ${missing.join("\n     ")}`);
    if (extra.length)   console.error(`   Extra keys:\n     ${extra.join("\n     ")}`);
  } else {
    console.log(`✅ ${lang} — ${keys.size} keys match`);
  }
}

if (failed) {
  process.exit(1);
} else {
  console.log(`\nAll locale files in sync (${refKeys.size} keys).`);
}
