"""Opt-in live smoke tests for the four LLM provider adapters.

These tests call real external APIs and cost money.  They are excluded from
the default suite and from CI by the ``-m 'not live'`` addopts in pyproject.toml.

How to run (pick whichever provider you have credentials for):
    uv run pytest -m live tests/test_live_providers.py -v

Expected cost: < $0.01 total (max_tokens=16 for completions, one embed call each).

Each test is individually skipped if the required credential env var is absent,
so you can run the whole file and only the providers you have keys for will execute.
"""

from __future__ import annotations

import os
import pytest


# ---------------------------------------------------------------------------
# Ollama (local — free, no env var needed, but must be running)
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("OLLAMA_HOST", ""),
    reason="OLLAMA_HOST not set — Ollama not configured",
)
async def test_live_ollama_complete() -> None:
    """Ollama complete() returns a non-empty string."""
    from backend.providers.ollama import OllamaProvider

    provider = OllamaProvider(model=os.environ.get("OLLAMA_MODEL", "llama3"))
    result = await provider.complete("Say: ok", max_tokens=8)
    assert isinstance(result, str) and len(result) > 0


@pytest.mark.live
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("OLLAMA_HOST", ""),
    reason="OLLAMA_HOST not set — Ollama not configured",
)
async def test_live_ollama_embed() -> None:
    """Ollama embed() returns a non-empty float list."""
    from backend.providers.ollama import OllamaProvider

    provider = OllamaProvider(model=os.environ.get("OLLAMA_MODEL", "llama3"))
    embedding = await provider.embed("test document")
    assert isinstance(embedding, list) and len(embedding) > 0
    assert all(isinstance(v, float) for v in embedding)


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)
async def test_live_anthropic_complete() -> None:
    from backend.providers.anthropic import AnthropicProvider

    provider = AnthropicProvider(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        model="claude-haiku-4-5-20251001",
    )
    result = await provider.complete("Say: ok", max_tokens=16)
    assert isinstance(result, str) and len(result) > 0


@pytest.mark.live
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)
async def test_live_anthropic_embed() -> None:
    from backend.providers.anthropic import AnthropicProvider

    provider = AnthropicProvider(
        api_key=os.environ["ANTHROPIC_API_KEY"],
        model="claude-haiku-4-5-20251001",
    )
    embedding = await provider.embed("test document")
    assert isinstance(embedding, list) and len(embedding) > 0


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set",
)
async def test_live_openai_complete() -> None:
    from backend.providers.openai import OpenAIProvider

    provider = OpenAIProvider(
        api_key=os.environ["OPENAI_API_KEY"],
        model="gpt-4o-mini",
    )
    result = await provider.complete("Say: ok", max_tokens=16)
    assert isinstance(result, str) and len(result) > 0


@pytest.mark.live
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set",
)
async def test_live_openai_embed() -> None:
    from backend.providers.openai import OpenAIProvider

    provider = OpenAIProvider(
        api_key=os.environ["OPENAI_API_KEY"],
        model="gpt-4o-mini",
    )
    embedding = await provider.embed("test document")
    assert isinstance(embedding, list) and len(embedding) > 0


# ---------------------------------------------------------------------------
# Bedrock
# ---------------------------------------------------------------------------

@pytest.mark.live
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("AWS_ACCESS_KEY_ID"),
    reason="AWS_ACCESS_KEY_ID not set",
)
async def test_live_bedrock_complete() -> None:
    from backend.providers.bedrock import BedrockProvider

    provider = BedrockProvider(
        region=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
        model=os.environ.get("BEDROCK_MODEL", "anthropic.claude-haiku-20240307-v1:0"),
    )
    result = await provider.complete("Say: ok", max_tokens=16)
    assert isinstance(result, str) and len(result) > 0


@pytest.mark.live
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("AWS_ACCESS_KEY_ID"),
    reason="AWS_ACCESS_KEY_ID not set",
)
async def test_live_bedrock_embed() -> None:
    from backend.providers.bedrock import BedrockProvider

    provider = BedrockProvider(
        region=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
        model=os.environ.get("BEDROCK_MODEL", "anthropic.claude-haiku-20240307-v1:0"),
    )
    embedding = await provider.embed("test document")
    assert isinstance(embedding, list) and len(embedding) > 0
