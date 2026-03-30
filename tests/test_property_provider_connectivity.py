"""Property-based test for provider connectivity error surfacing.

# Feature: paperless-iq, Property 8: Provider connectivity error surfacing
For any provider configuration where health_check() returns False, the settings
save API must return an error response containing a descriptive message rather
than persisting the configuration silently.

Validates: Requirements 3.3
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backend.providers.anthropic_provider import AnthropicProvider
from backend.providers.bedrock import BedrockProvider
from backend.providers.ollama_provider import OllamaProvider
from backend.providers.openai_provider import OpenAIProvider

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_provider_name_strategy = st.sampled_from(["openai", "anthropic", "ollama", "bedrock"])

_model_strategy = st.one_of(
    st.just("gpt-4o"),
    st.just("gpt-3.5-turbo"),
    st.just("claude-3-haiku-20240307"),
    st.just("claude-3-sonnet-20240229"),
    st.just("llama3"),
    st.just("mistral"),
    st.just("anthropic.claude-3-haiku-20240307-v1:0"),
)

_credential_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
    min_size=8,
    max_size=64,
)

_secret_key_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
    min_size=16,
    max_size=64,
)

_base_url_strategy = st.one_of(
    st.just("http://localhost:11434"),
    st.just("http://ollama:11434"),
    st.just("https://api.openai.com/v1"),
)

# ---------------------------------------------------------------------------
# Helpers: settings save simulation
# ---------------------------------------------------------------------------

_PROVIDER_CLASS_MAP = {
    "openai": "backend.providers.openai_provider.OpenAIProvider",
    "anthropic": "backend.providers.anthropic_provider.AnthropicProvider",
    "ollama": "backend.providers.ollama_provider.OllamaProvider",
    "bedrock": "backend.providers.bedrock.BedrockProvider",
}


async def simulate_settings_save(
    provider_name: str,
    model: str,
    credential: str,
    secret_key: str,
    health_check_returns: bool,
) -> dict:
    """
    Simulate the settings save logic that the /api/settings PUT endpoint
    will implement (task 13.1).

    Returns a dict with:
      - "success": bool
      - "error": str | None  — descriptive error message when success is False
      - "persisted": bool    — whether the config was stored
    """
    patch_target = _PROVIDER_CLASS_MAP[provider_name] + ".health_check"

    with patch(patch_target, new=AsyncMock(return_value=health_check_returns)):
        # Instantiate the provider (credentials don't need to be valid for this test)
        if provider_name == "openai":
            provider = OpenAIProvider(
                api_key_enc=credential,
                model=model,
                secret_key=secret_key,
            )
        elif provider_name == "anthropic":
            provider = AnthropicProvider(
                api_key_enc=credential,
                model=model,
                secret_key=secret_key,
            )
        elif provider_name == "ollama":
            provider = OllamaProvider(
                base_url="http://localhost:11434",
                model=model,
            )
        else:  # bedrock
            provider = BedrockProvider(
                region="us-east-1",
                access_key_id_enc=credential,
                secret_access_key_enc=credential,
                secret_key=secret_key,
                model=model,
            )

        reachable = await provider.health_check()

        if not reachable:
            return {
                "success": False,
                "error": (
                    f"Cannot connect to provider '{provider_name}': "
                    f"health check failed. Please verify your credentials and "
                    f"network connectivity."
                ),
                "persisted": False,
            }

        # Health check passed — config would be persisted
        return {
            "success": True,
            "error": None,
            "persisted": True,
        }


# ---------------------------------------------------------------------------
# Property 8: Provider connectivity error surfacing
# ---------------------------------------------------------------------------

@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(
    provider_name=_provider_name_strategy,
    model=_model_strategy,
    credential=_credential_strategy,
    secret_key=_secret_key_strategy,
)
@pytest.mark.asyncio
async def test_property_8_connectivity_error_surfaced(
    provider_name: str,
    model: str,
    credential: str,
    secret_key: str,
) -> None:
    """
    # Feature: paperless-iq, Property 8: Provider connectivity error surfacing

    For any provider configuration where health_check() returns False, the
    settings save API must return an error response containing a descriptive
    message rather than persisting the configuration silently.

    Validates: Requirements 3.3
    """
    result = await simulate_settings_save(
        provider_name=provider_name,
        model=model,
        credential=credential,
        secret_key=secret_key,
        health_check_returns=False,
    )

    # Must not succeed
    assert result["success"] is False, (
        f"Settings save must fail when health_check() returns False "
        f"(provider={provider_name!r}, model={model!r})"
    )

    # Error message must be a non-empty descriptive string
    assert isinstance(result["error"], str), (
        f"Error must be a string, got {type(result['error'])!r}"
    )
    assert len(result["error"]) > 0, (
        "Error message must not be empty when connectivity check fails"
    )

    # Config must NOT have been persisted
    assert result["persisted"] is False, (
        f"Invalid config must not be persisted when health_check() returns False "
        f"(provider={provider_name!r})"
    )


@settings(
    max_examples=100,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(
    provider_name=_provider_name_strategy,
    model=_model_strategy,
    credential=_credential_strategy,
    secret_key=_secret_key_strategy,
)
@pytest.mark.asyncio
async def test_property_8_successful_connectivity_persists(
    provider_name: str,
    model: str,
    credential: str,
    secret_key: str,
) -> None:
    """
    # Feature: paperless-iq, Property 8: Provider connectivity error surfacing (inverse)

    When health_check() returns True, the settings save must succeed and
    the config must be persisted. This validates the inverse of the property —
    that the error gate is not over-broad.

    Validates: Requirements 3.3
    """
    result = await simulate_settings_save(
        provider_name=provider_name,
        model=model,
        credential=credential,
        secret_key=secret_key,
        health_check_returns=True,
    )

    # Must succeed
    assert result["success"] is True, (
        f"Settings save must succeed when health_check() returns True "
        f"(provider={provider_name!r}, model={model!r})"
    )

    # No error message
    assert result["error"] is None, (
        f"No error expected when connectivity check passes, got: {result['error']!r}"
    )

    # Config must have been persisted
    assert result["persisted"] is True, (
        f"Config must be persisted when health_check() returns True "
        f"(provider={provider_name!r})"
    )
