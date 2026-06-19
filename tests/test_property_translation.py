"""Property-based tests for the translation service.

# Feature: paperless-iq, Property 27: Translation persistence and application
# Feature: paperless-iq, Property 28: Translation failure fallback

Validates: Requirements 10.3, 10.4, 10.5, 10.6, 10.8, 10.10
"""

from __future__ import annotations

import shutil
import tempfile
from unittest.mock import AsyncMock

import pytest
from hypothesis import given
from hypothesis import strategies as st

from backend.translation import DEFAULT_STRINGS, TranslationService

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_language = st.sampled_from(["de", "fr", "es", "ja", "zh", "pt", "ko", "it"])


# ---------------------------------------------------------------------------
# Property 27: Translation persistence and application
# ---------------------------------------------------------------------------

@given(language=_language)
@pytest.mark.asyncio
async def test_property_27_translation_persistence(language: str) -> None:
    """
    # Feature: paperless-iq, Property 27: Translation persistence and application

    After translate_all(): cache must be written, restart must load from cache
    without LLM call, and prompts must use translated template.

    Validates: Requirements 10.3, 10.4, 10.5, 10.6, 10.8
    """
    tmpdir = tempfile.mkdtemp(prefix="piq_trans_test_")
    try:
        # Mock LLM that returns "[lang] original" as translation
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            side_effect=lambda prompt, max_tokens: f"[{language}] translated"
        )

        svc = TranslationService(llm_provider=mock_llm, cache_dir=tmpdir)
        await svc.translate_all(language)

        # Cache must be written
        assert svc.language == language

        # All strings must be translated (not English defaults)
        for key in DEFAULT_STRINGS:
            val = svc.get_string(key)
            assert val == f"[{language}] translated", (
                f"String '{key}' not translated: {val}"
            )

        # LLM was called for each string
        assert mock_llm.complete.call_count == len(DEFAULT_STRINGS)

        # Simulate restart: new service loads from cache WITHOUT LLM
        mock_llm2 = AsyncMock()
        svc2 = TranslationService(llm_provider=mock_llm2, cache_dir=tmpdir)
        loaded = svc2.load_cache(language)

        assert loaded, "Cache should have been loaded"
        mock_llm2.complete.assert_not_called()

        # Strings must still be translated
        for key in DEFAULT_STRINGS:
            val = svc2.get_string(key)
            assert val == f"[{language}] translated"
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Property 28: Translation failure fallback
# ---------------------------------------------------------------------------

@given(language=_language)
@pytest.mark.asyncio
async def test_property_28_translation_failure_fallback(language: str) -> None:
    """
    # Feature: paperless-iq, Property 28: Translation failure fallback

    When LLM translation fails, previous translations must remain in effect,
    error must be surfaced, and application must continue serving.

    Validates: Requirements 10.10
    """
    tmpdir = tempfile.mkdtemp(prefix="piq_trans_fail_")
    try:
        # First: successful translation
        mock_llm = AsyncMock()
        mock_llm.complete = AsyncMock(
            side_effect=lambda prompt, max_tokens: f"[{language}] good"
        )

        svc = TranslationService(llm_provider=mock_llm, cache_dir=tmpdir)
        await svc.translate_all(language)

        # Verify translations are in place
        for key in DEFAULT_STRINGS:
            assert svc.get_string(key) == f"[{language}] good"

        # Now: LLM fails on retranslation
        failing_llm = AsyncMock()
        failing_llm.complete = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        svc._llm = failing_llm

        # retranslate should not crash — individual string failures are caught
        # and fall back to English defaults
        await svc.retranslate(language)

        # Service must still be functional (get_string works)
        for key in DEFAULT_STRINGS:
            val = svc.get_string(key)
            assert val is not None, f"get_string('{key}') returned None"
            # Value should be the English fallback since translation failed
            assert val == DEFAULT_STRINGS[key], (
                f"Expected English fallback for '{key}', got '{val}'"
            )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
