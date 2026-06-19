# Feature: paperless-live-integration, Property 9: Provider registry returns LLMProvider for valid config
# Feature: paperless-live-integration, Property 10: Provider registry raises on missing credentials
"""Property-based tests for the provider registry module.

Validates: Requirements 11.1, 11.6
"""

from __future__ import annotations

import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from backend.models import PaperlessIQConfig
from backend.protocols import LLMProvider
from backend.provider_registry import build_providers


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_model_strategy = st.sampled_from([
    "gpt-4o",
    "gpt-3.5-turbo",
    "claude-3-haiku-20240307",
    "claude-3-sonnet-20240229",
    "llama3",
    "mistral",
    "anthropic.claude-3-haiku-20240307-v1:0",
])

_secret_key_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
    min_size=16,
    max_size=64,
)

_api_key_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
    min_size=8,
    max_size=64,
)

_region_strategy = st.sampled_from([
    "us-east-1",
    "us-west-2",
    "eu-west-1",
    "eu-central-1",
    "ap-southeast-1",
])


def _anthropic_config(model: str, api_key: str) -> PaperlessIQConfig:
    return PaperlessIQConfig(
        llm_provider="anthropic",
        llm_model=model,
        llm_credentials=api_key.encode(),
    )


def _openai_config(model: str, api_key: str) -> PaperlessIQConfig:
    return PaperlessIQConfig(
        llm_provider="openai",
        llm_model=model,
        llm_credentials=api_key.encode(),
    )


def _ollama_config(model: str) -> PaperlessIQConfig:
    return PaperlessIQConfig(
        llm_provider="ollama",
        llm_model=model,
        llm_credentials=b"",
    )


def _bedrock_config(model: str, region: str, access_key: str, secret_key: str) -> PaperlessIQConfig:
    creds = json.dumps({
        "region": region,
        "access_key_id": access_key,
        "secret_access_key": secret_key,
    })
    return PaperlessIQConfig(
        llm_provider="bedrock",
        llm_model=model,
        llm_credentials=creds.encode(),
    )


# ---------------------------------------------------------------------------
# Property 9: Provider registry returns LLMProvider for valid config
# ---------------------------------------------------------------------------

@given(
    model=_model_strategy,
    api_key=_api_key_strategy,
    secret_key=_secret_key_strategy,
)
def test_property_9_anthropic_returns_llm_provider(
    model: str, api_key: str, secret_key: str
) -> None:
    """**Validates: Requirements 11.1**

    For any valid anthropic config with non-empty credentials,
    build_providers returns a dict containing an LLMProvider instance.
    """
    config = _anthropic_config(model, api_key)
    result = build_providers(config, secret_key)

    assert isinstance(result, dict)
    assert "anthropic" in result
    assert isinstance(result["anthropic"], LLMProvider)


@given(
    model=_model_strategy,
    api_key=_api_key_strategy,
    secret_key=_secret_key_strategy,
)
def test_property_9_openai_returns_llm_provider(
    model: str, api_key: str, secret_key: str
) -> None:
    """**Validates: Requirements 11.1**

    For any valid openai config with non-empty credentials,
    build_providers returns a dict containing an LLMProvider instance.
    """
    config = _openai_config(model, api_key)
    result = build_providers(config, secret_key)

    assert isinstance(result, dict)
    assert "openai" in result
    assert isinstance(result["openai"], LLMProvider)


@given(
    model=_model_strategy,
    secret_key=_secret_key_strategy,
)
def test_property_9_ollama_returns_llm_provider(
    model: str, secret_key: str
) -> None:
    """**Validates: Requirements 11.1**

    For any valid ollama config (no credentials required),
    build_providers returns a dict containing an LLMProvider instance.
    """
    config = _ollama_config(model)
    result = build_providers(config, secret_key)

    assert isinstance(result, dict)
    assert "ollama" in result
    assert isinstance(result["ollama"], LLMProvider)


@given(
    model=_model_strategy,
    region=_region_strategy,
    access_key=_api_key_strategy,
    secret_access_key=_api_key_strategy,
    secret_key=_secret_key_strategy,
)
def test_property_9_bedrock_returns_llm_provider(
    model: str, region: str, access_key: str, secret_access_key: str, secret_key: str
) -> None:
    """**Validates: Requirements 11.1**

    For any valid bedrock config with JSON credentials containing
    region, access_key_id, and secret_access_key,
    build_providers returns a dict containing an LLMProvider instance.
    """
    config = _bedrock_config(model, region, access_key, secret_access_key)
    result = build_providers(config, secret_key)

    assert isinstance(result, dict)
    assert "bedrock" in result
    assert isinstance(result["bedrock"], LLMProvider)


# ---------------------------------------------------------------------------
# Property 10: Provider registry raises on missing credentials
# ---------------------------------------------------------------------------

@given(
    model=_model_strategy,
    secret_key=_secret_key_strategy,
)
def test_property_10_anthropic_raises_on_empty_credentials(
    model: str, secret_key: str
) -> None:
    """**Validates: Requirements 11.6**

    For anthropic provider with empty llm_credentials,
    build_providers raises ValueError.
    """
    config = PaperlessIQConfig(
        llm_provider="anthropic",
        llm_model=model,
        llm_credentials=b"",
    )
    with pytest.raises(ValueError, match="[Cc]redentials"):
        build_providers(config, secret_key)


@given(
    model=_model_strategy,
    secret_key=_secret_key_strategy,
)
def test_property_10_openai_raises_on_empty_credentials(
    model: str, secret_key: str
) -> None:
    """**Validates: Requirements 11.6**

    For openai provider with empty llm_credentials,
    build_providers raises ValueError.
    """
    config = PaperlessIQConfig(
        llm_provider="openai",
        llm_model=model,
        llm_credentials=b"",
    )
    with pytest.raises(ValueError, match="[Cc]redentials"):
        build_providers(config, secret_key)


@given(
    model=_model_strategy,
    secret_key=_secret_key_strategy,
)
def test_property_10_bedrock_raises_on_empty_credentials(
    model: str, secret_key: str
) -> None:
    """**Validates: Requirements 11.6**

    For bedrock provider with empty llm_credentials,
    build_providers raises ValueError.
    """
    config = PaperlessIQConfig(
        llm_provider="bedrock",
        llm_model=model,
        llm_credentials=b"",
    )
    with pytest.raises(ValueError, match="[Cc]redentials"):
        build_providers(config, secret_key)
