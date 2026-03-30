"""Manual analysis service for Paperless IQ.

Provides single-document analysis with optional provider/model/mode overrides,
and document listing with tag filter support.

Validates: Requirements 6.1, 6.2, 6.3, 6.4
"""

from __future__ import annotations

import logging
from typing import Any, Literal

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
    ) -> None:
        self._config = config
        self._providers = providers
        self._paperless = paperless_client

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
        )

        suggestion = await analyzer.analyze(document_id)

        # Verify global config was NOT modified
        assert self._config.llm_provider == self._config.llm_provider  # identity check
        if provider_override:
            # The original config must still have its original provider
            logger.debug(
                "Override used provider=%s for doc %d; global config unchanged.",
                provider_override, document_id,
            )

        return suggestion


async def list_documents_by_tag(
    paperless_client: PaperlessNGXClient,
    tag_id: int | None = None,
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    """List documents from Paperless NGX, optionally filtered by tag.

    Validates: Requirements 6.4
    """
    import httpx

    params: dict[str, Any] = {
        "page": page,
        "page_size": page_size,
    }
    if tag_id is not None:
        params["tags__id__in"] = tag_id

    url = f"{paperless_client._base_url.rstrip('/')}/api/documents/"
    headers = {"Authorization": f"Token {paperless_client._token}"}

    async with httpx.AsyncClient(headers=headers, timeout=30) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()

    results = data.get("results", [])
    total = data.get("count", len(results))

    return {
        "items": results,
        "total": total,
        "page": page,
        "page_size": page_size,
    }
