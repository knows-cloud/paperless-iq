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


def _as_text(raw: Any) -> str:
    """Decode a credential blob to text. Empty blobs become ""."""
    if not raw:
        return ""
    if isinstance(raw, bytes):
        return raw.decode("latin-1")
    return str(raw)


def role_credentials(config: Any, role: str) -> str:
    """Credentials for ``role``, falling back to the LLM section when empty.

    Empty means inherit (D-27): an install that predates per-role settings has
    every role field empty and therefore resolves exactly as it did before.
    """
    own = _as_text(getattr(config, f"{role}_credentials", None))
    if own:
        return own
    return _as_text(getattr(config, "llm_credentials", None))


def effective_embed_endpoint(config: Any) -> str:
    """The URL embeddings will actually be requested from.

    Used to decide whether a settings change invalidates the index. Comparing
    ``embed_provider`` and ``embedding_model`` alone is not enough once the
    embedding role can carry its own endpoint: the same model name served by a
    different server is a *different vector space*, and mixing the two in one
    collection degrades retrieval silently.

    Credentials are deliberately excluded — rotating a key against the same
    endpoint yields identical vectors and must not prompt a re-index.
    """
    ep = getattr(config, "embed_provider", "ollama")
    own = (getattr(config, "embed_base_url", "") or "").strip()
    if own:
        return own
    if ep == "ollama":
        return config.ollama_url or os.environ.get("OLLAMA_URL", "http://localhost:11434")
    if ep == "openai":
        return getattr(config, "openai_base_url", "") or ""
    # Bedrock resolves by region, and a Titan/Cohere model is the same vector
    # space in every region, so there is no endpoint to compare.
    return ""


def resolve_embed_provider(
    config: Any, providers: Any, secret_key: str | None = None
) -> Any | None:
    """Return the embedding provider for ``config.embed_provider``.

    Each backend honours the per-role ``embed_base_url`` / ``embed_credentials``
    when set, and inherits the LLM section's endpoint and credentials when they
    are empty (D-27).

    - ollama  → fresh OllamaProvider on embed_base_url or ollama_url
    - bedrock → reuses the chat BedrockProvider only when the embed role adds
                nothing of its own; otherwise builds a standalone instance
    - openai  → reuses the chat OpenAIProvider only when the embed role adds
                nothing of its own; otherwise builds a standalone instance
    """
    ep = getattr(config, "embed_provider", "ollama")
    own_url = (getattr(config, "embed_base_url", "") or "").strip()
    own_creds = _as_text(getattr(config, "embed_credentials", None))

    if ep == "ollama":
        embed_model = config.embedding_model or "nomic-embed-text"
        base_url = (
            own_url
            or config.ollama_url
            or os.environ.get("OLLAMA_URL", "http://localhost:11434")
        )
        return OllamaProvider(base_url=base_url, model=embed_model)

    if secret_key is None:
        from backend.keystore import get_machine_key

        secret_key = get_machine_key()

    if ep == "bedrock":
        embed_model = config.embedding_model or "amazon.titan-embed-text-v1"

        # Reuse the chat instance only when the embed role adds nothing of its
        # own — otherwise the two roles would share credentials again.
        if not own_creds:
            provider = providers.get("bedrock") if providers else None
            if provider is not None:
                provider._embed_model = embed_model
                return provider

        raw = own_creds or _as_text(getattr(config, "llm_credentials", None))
        if raw:
            try:
                creds = json.loads(raw)
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
                    embed_model=embed_model,
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
            "Go to Settings → LLM Provider and save your AWS credentials, or give the "
            "embedding role its own credentials."
        )

    if ep == "openai":
        embed_model = config.embedding_model or "text-embedding-3-small"

        # Reuse the chat instance only when the embed role neither overrides the
        # endpoint nor brings its own key.
        if not own_url and not own_creds:
            provider = providers.get("openai") if providers else None
            if provider is not None:
                return provider

        api_key = own_creds
        if not api_key and getattr(config, "llm_provider", "") == "openai":
            # Inherit the chat key — but only when the chat provider is actually
            # OpenAI, since another provider's credentials are meaningless here.
            api_key = _as_text(getattr(config, "llm_credentials", None))
        if not api_key:
            raise ValueError(
                "embed_provider='openai' needs an API key. Set one under the embedding "
                "settings, or use 'openai' as the LLM provider so the key can be shared."
            )

        base_url = own_url or (getattr(config, "openai_base_url", "") or "")
        return OpenAIProvider(
            api_key_enc=encrypt_credential(api_key, secret_key),
            model="",  # unused — this instance is embed-only
            secret_key=secret_key,
            base_url=base_url or None,
            embed_model=embed_model,
        )

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
            self._role_cache["embed"] = resolve_embed_provider(
                self._config, self, self._secret_key
            )
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
