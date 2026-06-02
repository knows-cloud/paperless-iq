#!/usr/bin/env node
/**
 * i18n consistency checks. Run via: node scripts/check-i18n.mjs
 * Wired into package.json as "check:i18n".
 *
 * Two independent checks, both must pass:
 *   1. Locale parity — every locale file has the same key set as the reference (en).
 *   2. Reference resolution — every i18n key referenced in source code actually
 *      exists in the reference locale. This catches keys that render as their raw
 *      string in the UI (react-i18next falls back to the key when it's missing).
 *
 * Check 2 covers both ways the codebase reaches `t()`:
 *   - static  `t("some.key")`              — key is a literal at the call site
 *   - dynamic `t(item.labelKey)`           — key is carried as data, defined as a
 *                                            `labelKey:`/`key:` field (e.g. in
 *                                            settings/constants.ts, App.tsx nav).
 * A naive scan of `t("...")` only sees the static form, which is exactly how a
 * broken dynamic key (e.g. a Select option's labelKey) can ship unnoticed.
 */

import { readFileSync, readdirSync, statSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const LOCALES_DIR = join(__dirname, "../src/locales");
const SRC_DIR = join(__dirname, "../src");
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

// ── Check 1: locale parity ──────────────────────────────────────────────────
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

// ── Check 2: every key referenced in source resolves in the reference locale ──
function walk(dir) {
  return readdirSync(dir).flatMap(name => {
    const p = join(dir, name);
    if (name === "node_modules" || name === "locales" || name === "dist") return [];
    return statSync(p).isDirectory() ? walk(p) : [p];
  });
}

// Each matcher pulls a literal i18n key out of a line. `key:` is only treated as
// an i18n key when the value is namespaced (contains a dot) — plain identifiers
// like METADATA_FIELDS' `key: "title"` are not translation keys.
const MATCHERS = [
  { re: /\bt\(\s*(["'])([^"'`\n]+?)\1/g,            kind: 't("…")',   dotOnly: false },
  { re: /\blabelKey:\s*(["'])([^"'`\n]+?)\1/g,      kind: "labelKey", dotOnly: false },
  { re: /\bi18nKey\s*[:=]\s*(["'])([^"'`\n]+?)\1/g, kind: "i18nKey",  dotOnly: false },
  { re: /\bkey:\s*(["'])([^"'`\n]+?)\1/g,           kind: "key",      dotOnly: true  },
];

const unresolved = [];
const sourceFiles = walk(SRC_DIR).filter(f => /\.(ts|tsx)$/.test(f));

for (const file of sourceFiles) {
  const lines = readFileSync(file, "utf8").split("\n");
  lines.forEach((line, i) => {
    for (const { re, kind, dotOnly } of MATCHERS) {
      for (const m of line.matchAll(re)) {
        const key = m[2];
        if (key.includes("${")) continue;            // interpolated — can't resolve statically
        if (dotOnly && !key.includes(".")) continue; // not a namespaced i18n key
        if (!refKeys.has(key)) {
          unresolved.push({ file: file.replace(SRC_DIR + "/", ""), line: i + 1, key, kind });
        }
      }
    }
  });
}

if (unresolved.length) {
  failed = true;
  console.error(`\n❌ ${unresolved.length} i18n key(s) referenced in code but missing from ${REFERENCE_LANG}/translation.json:`);
  for (const u of unresolved) {
    console.error(`     ${u.file}:${u.line}  [${u.kind}]  ${u.key}`);
  }
} else {
  console.log(`✅ source references — all i18n keys resolve (${sourceFiles.length} files scanned)`);
}

if (failed) {
  process.exit(1);
} else {
  console.log(`\nAll i18n checks passed (${refKeys.size} keys).`);
}
