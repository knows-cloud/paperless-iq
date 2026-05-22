"""Manual analysis service for Paperless IQ.

Provides single-document analysis with optional provider/model/mode overrides,
and document listing with tag filter support.

Validates: Requirements 6.1, 6.2, 6.3, 6.4
"""

from __future__ import annotations

import logging
from typing import Literal

from backend.analyzer import DocumentAnalyzer, PaperlessNGXClient
from backend.models import MetadataSuggestion, PaperlessIQConfig
from backend.protocols import LLMProvider

logger = logging.getLogger(__name__)


class ManualAnalysisService:
    """Handles manual (on-demand) document analysis with optional overrides.

    Overrides apply to a single run only and do not modify the global config.

    Validates: Requirements 6.1, 6.2, 6.3
    """

    def __init__(
        self,
        config: PaperlessIQConfig,
        providers: dict[str, LLMProvider],
        paperless_client: PaperlessNGXClient,
        vector_store: Any | None = None,
    ) -> None:
        self._config = config
        self._providers = providers
        self._paperless = paperless_client
        self._vector_store = vector_store

    async def analyze(
        self,
        document_id: int,
        provider_override: str | None = None,
        model_override: str | None = None,
        mode_override: Literal["ocr", "full_document"] | None = None,
    ) -> MetadataSuggestion:
        """Run analysis for a single document with optional overrides.

        Overrides are used for this run only. The global config is not modified.

        Validates: Requirements 6.1, 6.2
        """
        # Build a temporary config with overrides applied
        overrides: dict[str, Any] = {}
        if provider_override is not None:
            overrides["llm_provider"] = provider_override
        if model_override is not None:
            overrides["llm_model"] = model_override
        if mode_override is not None:
            overrides["default_analysis_mode"] = mode_override

        run_config = self._config.model_copy(update=overrides) if overrides else self._config

        # Resolve the provider for this run
        provider_name = run_config.llm_provider
        provider = self._providers.get(provider_name)
        if provider is None:
            raise ValueError(f"Provider '{provider_name}' is not configured.")

        analyzer = DocumentAnalyzer(
            provider=provider,
            paperless_client=self._paperless,
            config=run_config,
            provider_name=provider_name,
            context_window_chars=run_config.context_window_chars,
            vector_store=self._vector_store,
        )

        suggestion = await analyzer.analyze(document_id)

        return suggestion


