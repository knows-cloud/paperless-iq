"""Provider registry — role-aware factory for LLM provider instances.

Paperless IQ uses providers in three distinct *roles*:

- ``llm``    — chat / analysis completions
- ``embed``  — vector embeddings
- ``rerank`` — second-pass relevance scoring

Historically the registry built exactly one provider (the chat one) and keyed it
by provider *name*, so every other role had to reuse that instance — and with it
its base URL and its credentials. :class:`ProviderRegistry` replaces that with
per-role resolution: ask for the role you need, not for a provider name.

The class still subclasses ``dict`` and still contains the ``{name: provider}``
entry for the chat provider, so older name-keyed lookups keep working while call
sites migrate to the role accessors.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from backend.models import PaperlessIQConfig
from backend.protocols import LLMProvider
from backend.providers import (
    AnthropicProvider,
    BedrockProvider,
    OllamaProvider,
    OpenAIProvider,
)
from backend.providers.encryption import encrypt_credential

logger = logging.getLogger(__name__)


def _build_llm_provider(
    config: PaperlessIQConfig,
    secret_key: str,
) -> LLMProvider:
    """Instantiate the configured chat provider.

    Raises ValueError if credentials are required but missing.
    """
    provider_name = config.llm_provider
    model = config.llm_model
    raw_creds = config.llm_credentials

    if provider_name == "ollama":
        base_url = config.ollama_url or os.environ.get("OLLAMA_URL", "http://localhost:11434")
        logger.info("Building Ollama provider with base_url=%s, model=%s", base_url, model)
        return OllamaProvider(base_url=base_url, model=model)

    if provider_name in ("anthropic", "openai"):
        if not raw_creds:
            raise ValueError(
                f"Credentials are required for the '{provider_name}' provider "
                "but llm_credentials is empty."
            )
        api_key = raw_creds.decode() if isinstance(raw_creds, bytes) else raw_creds
        api_key_enc = encrypt_credential(api_key, secret_key)

        if provider_name == "anthropic":
            return AnthropicProvider(api_key_enc=api_key_enc, model=model, secret_key=secret_key)
        return OpenAIProvider(
            api_key_enc=api_key_enc,
            model=model,
            secret_key=secret_key,
            base_url=getattr(config, "openai_base_url", None) or None,
            embed_model=getattr(config, "embedding_model", None) or "text-embedding-3-small",
        )

    if provider_name == "bedrock":
        if not raw_creds:
            raise ValueError(
                "Credentials are required for the 'bedrock' provider "
                "but llm_credentials is empty."
            )
        creds = _parse_bedrock_credentials(raw_creds)

        access_key_enc = encrypt_credential(creds["access_key_id"], secret_key)
        secret_access_key_enc = encrypt_credential(creds["secret_access_key"], secret_key)
        # session_token is optional — only needed for temporary STS credentials
        session_token_enc: str | None = None
        if creds.get("session_token"):
            session_token_enc = encrypt_credential(creds["session_token"], secret_key)

        # embedding_model is only meaningful when embed_provider="bedrock".
        # We pass it here so the provider is ready regardless of whether
        # it will be used for LLM only, embeddings only, or both.
        embed_model = config.embedding_model or "amazon.titan-embed-text-v1"

        return BedrockProvider(
            region=creds["region"],
            access_key_id_enc=access_key_enc,
            secret_access_key_enc=secret_access_key_enc,
            secret_key=secret_key,
            model=model,
            session_token_enc=session_token_enc,
            embed_model=embed_model,
        )

    raise ValueError(f"Unsupported LLM provider: '{provider_name}'")


def _parse_bedrock_credentials(raw_creds: Any) -> dict[str, Any]:
    """Decode and validate a Bedrock credentials JSON blob."""
    creds_str = raw_creds.decode() if isinstance(raw_creds, bytes) else raw_creds
    try:
        creds = json.loads(creds_str)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(
            "Bedrock llm_credentials must be a JSON object with "
            "'region', 'access_key_id', and 'secret_access_key' keys."
        ) from exc

    for key in ("region", "access_key_id", "secret_access_key"):
        if key not in creds:
            raise ValueError(
                f"Bedrock llm_credentials JSON is missing required key '{key}'."
            )
    return creds


def resolve_embed_provider(config: Any, providers: Any) -> Any | None:
    """Return the right embedding provider based on ``config.embed_provider``.

    - ollama  → fresh OllamaProvider using config.ollama_url + config.embedding_model
    - bedrock → prefers the existing BedrockProvider instance when llm_provider=bedrock;
                falls back to building a standalone BedrockProvider from stored credentials
                so you can use Bedrock embeddings with any LLM (Ollama, Anthropic, etc.)
    - openai  → reuses the OpenAIProvider instance; requires llm_provider=openai
    """
    ep = getattr(config, "embed_provider", "ollama")

    if ep == "ollama":
        embed_model = config.embedding_model or "nomic-embed-text"
        ollama_url = config.ollama_url or os.environ.get("OLLAMA_URL", "http://localhost:11434")
        return OllamaProvider(base_url=ollama_url, model=embed_model)

    if ep == "bedrock":
        # Case 1: LLM is also Bedrock — reuse the existing provider instance
        provider = providers.get("bedrock") if providers else None
        if provider is not None:
            provider._embed_model = config.embedding_model or "amazon.titan-embed-text-v1"
            return provider

        # Case 2: LLM is something else (Ollama, Anthropic, …) — build a standalone
        # BedrockProvider from the credentials stored in llm_credentials.
        raw = getattr(config, "llm_credentials", None)
        if raw:
            try:
                from backend.keystore import get_machine_key

                creds_str = raw.decode("latin-1") if isinstance(raw, bytes) else str(raw)
                creds = json.loads(creds_str)
                secret_key = get_machine_key()
                session_token_enc = None
                if creds.get("session_token"):
                    session_token_enc = encrypt_credential(creds["session_token"], secret_key)
                return BedrockProvider(
                    region=creds["region"],
                    access_key_id_enc=encrypt_credential(creds["access_key_id"], secret_key),
                    secret_access_key_enc=encrypt_credential(
                        creds["secret_access_key"], secret_key
                    ),
                    secret_key=secret_key,
                    model="",  # unused — this instance is embed-only
                    session_token_enc=session_token_enc,
                    embed_model=config.embedding_model or "amazon.titan-embed-text-v1",
                )
            except Exception:
                logger.warning(
                    "embed_provider='bedrock' requested but could not build a standalone "
                    "Bedrock embed provider from stored credentials. "
                    "Check that Bedrock credentials are saved in Settings.",
                    exc_info=True,
                )
        raise ValueError(
            "embed_provider='bedrock' is configured but no Bedrock credentials are stored. "
            "Go to Settings → LLM Provider and save your AWS credentials."
        )

    if ep == "openai":
        provider = providers.get("openai") if providers else None
        if provider is None:
            raise ValueError(
                "embed_provider='openai' requires llm_provider='openai' as well "
                "(credentials are shared). Use 'ollama' as embed_provider to mix providers."
            )
        return provider

    return None


class ProviderRegistry(dict):
    """Per-role provider resolution for one config snapshot.

    Subclasses ``dict`` and carries the ``{llm_provider_name: instance}`` entry
    so name-keyed lookups written before roles existed keep working. New code
    should call :meth:`for_llm`, :meth:`for_embed` or :meth:`for_rerank`.

    A registry is bound to the config it was built from — ``app.state.providers``
    is rebuilt whenever settings are saved — so resolved roles are cached.
    """

    def __init__(self, config: PaperlessIQConfig, secret_key: str) -> None:
        llm = _build_llm_provider(config, secret_key)
        super().__init__({config.llm_provider: llm})
        self._config = config
        self._secret_key = secret_key
        self._llm = llm
        self._role_cache: dict[str, Any] = {}

    def for_llm(self) -> LLMProvider:
        """The chat provider. Always present — construction would have raised."""
        return self._llm

    def for_embed(self) -> Any | None:
        """The embedding provider, or None when the role is unconfigured.

        Raises ValueError when embeddings are configured but unsatisfiable.
        """
        if "embed" not in self._role_cache:
            self._role_cache["embed"] = resolve_embed_provider(self._config, self)
        return self._role_cache["embed"]

    def for_rerank(self) -> Any | None:
        """The provider backing provider-based reranking.

        Reranking inherits the chat provider today; the HTTP rerankers do not
        go through a provider at all.
        """
        return self._llm


def build_providers(
    config: PaperlessIQConfig,
    secret_key: str,
) -> ProviderRegistry:
    """Build the provider registry for a config snapshot.

    Returns a :class:`ProviderRegistry` — a dict mapping the chat provider's
    name to its instance, plus per-role accessors.
    Raises ValueError if credentials are required but missing.
    """
    return ProviderRegistry(config, secret_key)
