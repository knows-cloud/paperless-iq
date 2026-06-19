"""Translation service for Paperless IQ.

Translates UI strings and prompt templates via the configured LLM,
persists translations to disk, and loads from cache on startup.

Validates: Requirements 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 10.8, 10.9, 10.10
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from backend.protocols import LLMProvider

logger = logging.getLogger(__name__)

# Default UI strings (English)
DEFAULT_STRINGS: dict[str, str] = {
    "app.title": "Paperless IQ",
    "nav.settings": "Settings",
    "nav.queue": "Approval Queue",
    "nav.audit": "Audit Log",
    "nav.search": "Search",
    "nav.manual": "Manual Analysis",
    "btn.approve": "Approve",
    "btn.reject": "Reject",
    "btn.save": "Save",
    "btn.cancel": "Cancel",
    "btn.export": "Export",
    "btn.import": "Import",
    "btn.retranslate": "Re-translate",
    "label.provider": "LLM Provider",
    "label.model": "Model",
    "label.language": "Language",
    "msg.no_results": "No results found.",
    "msg.save_success": "Settings saved successfully.",
    "msg.save_error": "Failed to save settings.",
}


class TranslationService:
    """Manages UI string and prompt template translations.

    Translations are cached in memory and persisted to disk as JSON files.
    On startup, if a cache file exists for the configured language, it is
    loaded without calling the LLM.

    Validates: Requirements 10.2-10.10
    """

    def __init__(
        self,
        llm_provider: LLMProvider | None = None,
        cache_dir: str = "/data/translations",
    ) -> None:
        self._llm = llm_provider
        self._cache_dir = Path(cache_dir)
        self._strings: dict[str, str] = dict(DEFAULT_STRINGS)
        self._language: str | None = None
        self._prompt_translations: dict[str, str] = {}

    def load_cache(self, language: str) -> bool:
        """Load translations from disk cache if available.

        Returns True if cache was loaded, False otherwise.

        Validates: Requirements 10.4
        """
        cache_file = self._cache_dir / f"{language}.json"
        if not cache_file.exists():
            return False

        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            self._strings = data.get("strings", dict(DEFAULT_STRINGS))
            self._prompt_translations = data.get("prompts", {})
            self._language = language
            logger.info("Loaded translation cache for '%s'.", language)
            return True
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load translation cache for '%s': %s", language, exc)
            return False

    def _save_cache(self, language: str) -> None:
        """Persist current translations to disk."""
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = self._cache_dir / f"{language}.json"
        data = {
            "strings": self._strings,
            "prompts": self._prompt_translations,
        }
        cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Saved translation cache for '%s'.", language)

    async def translate_all(self, target_language: str) -> None:
        """Translate all UI strings and default prompts via the LLM.

        Validates: Requirements 10.3, 10.5, 10.6, 10.8
        """
        if self._llm is None:
            raise RuntimeError("No LLM provider configured for translation.")

        translated_strings: dict[str, str] = {}

        for key, english_text in DEFAULT_STRINGS.items():
            prompt = (
                f"Translate the following UI text to {target_language}. "
                f"Return ONLY the translated text, nothing else.\n\n"
                f"Text: {english_text}"
            )
            try:
                result = await self._llm.complete(prompt, max_tokens=200)
                translated_strings[key] = result.strip()
            except Exception as exc:
                logger.error("Translation failed for key '%s': %s", key, exc)
                translated_strings[key] = english_text  # fallback to English

        self._strings = translated_strings
        self._language = target_language
        self._save_cache(target_language)

    async def translate_prompt(self, prompt_template: str, target_language: str) -> str:
        """Translate a single prompt template via the LLM.

        Validates: Requirements 10.9
        """
        if self._llm is None:
            raise RuntimeError("No LLM provider configured for translation.")

        translate_prompt = (
            f"Translate the following prompt template to {target_language}. "
            f"Preserve any {{placeholders}} exactly as they are. "
            f"Return ONLY the translated text.\n\n"
            f"Template: {prompt_template}"
        )
        result = await self._llm.complete(translate_prompt, max_tokens=500)
        translated = result.strip()
        self._prompt_translations[prompt_template] = translated
        self._save_cache(target_language)
        return translated

    async def retranslate(self, target_language: str) -> None:
        """Force a fresh translation of all strings.

        Validates: Requirements 10.7
        """
        await self.translate_all(target_language)

    def get_string(self, key: str) -> str:
        """Get a translated UI string by key.

        Falls back to English default if key not found.

        Validates: Requirements 10.5
        """
        return self._strings.get(key, DEFAULT_STRINGS.get(key, key))

    def get_prompt(self, original_prompt: str) -> str:
        """Get the translated version of a prompt template.

        Returns the original if no translation exists.

        Validates: Requirements 10.6
        """
        return self._prompt_translations.get(original_prompt, original_prompt)

    @property
    def language(self) -> str | None:
        return self._language

    @property
    def strings(self) -> dict[str, str]:
        return dict(self._strings)
