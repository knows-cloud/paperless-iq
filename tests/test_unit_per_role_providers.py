"""Per-role provider routing: inheritance, isolation, HTTP rerank, re-index.

Covers the four guarantees the per-role refactor rests on:

1. **Inheritance** — an empty role field resolves to the LLM section (D-27),
   which is what keeps installs that predate these fields working unchanged.
2. **Isolation** — a role that carries its own endpoint gets its *own* provider
   instance. Regressing this would silently restore the shared-credential
   coupling the refactor exists to remove.
3. **HTTP rerank scoring** — sorted responses map back to input order, scores
   clamp to [0, 1], and any failure degrades to neutral rather than raising.
4. **Re-index trigger** — repointing embeddings invalidates the index; rotating
   a credential against the same endpoint does not.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar, Self

import pytest

from backend.models import PaperlessIQConfig
from backend.provider_registry import (
    ProviderRegistry,
    effective_embed_endpoint,
    resolve_embed_provider,
)
from backend.rerankers import HTTPReranker, TEIReranker, build_reranker

SECRET = "unit-test-secret-key"


def _config(**overrides: Any) -> PaperlessIQConfig:
    base: dict[str, Any] = {"llm_provider": "ollama", "llm_model": "llama3"}
    base.update(overrides)
    return PaperlessIQConfig(**base)


# ---------------------------------------------------------------------------
# 1. Inheritance — empty means inherit (D-27)
# ---------------------------------------------------------------------------


def test_embed_inherits_ollama_url_when_base_url_empty() -> None:
    cfg = _config(ollama_url="http://box:11434", embed_provider="ollama")
    provider = resolve_embed_provider(cfg, {}, SECRET)
    assert "box:11434" in provider._base_url


def test_embed_own_base_url_overrides_ollama_url() -> None:
    cfg = _config(
        ollama_url="http://box:11434",
        embed_provider="ollama",
        embed_base_url="http://gpu-rig:9000",
    )
    provider = resolve_embed_provider(cfg, {}, SECRET)
    assert "gpu-rig:9000" in provider._base_url


def test_embed_openai_inherits_chat_key() -> None:
    """The old code raised here unless llm_provider was also openai."""
    cfg = _config(
        llm_provider="openai",
        llm_model="gpt-4o",
        llm_credentials=b"sk-chat-key",
        embed_provider="openai",
        embed_base_url="http://vllm:8000/v1",
    )
    provider = resolve_embed_provider(cfg, {}, SECRET)
    assert provider is not None


def test_embed_openai_with_own_key_no_longer_requires_openai_chat() -> None:
    """The central restriction issue #183 reported is gone."""
    cfg = _config(
        llm_provider="ollama",
        embed_provider="openai",
        embed_credentials=b"sk-embed-only",
        embed_base_url="http://embeddings.internal/v1",
    )
    provider = resolve_embed_provider(cfg, {}, SECRET)
    assert provider is not None


def test_embed_openai_without_any_key_raises_actionable_error() -> None:
    cfg = _config(llm_provider="ollama", embed_provider="openai")
    with pytest.raises(ValueError, match="API key"):
        resolve_embed_provider(cfg, {}, SECRET)


# ---------------------------------------------------------------------------
# 2. Role isolation
# ---------------------------------------------------------------------------


def test_embed_role_with_own_endpoint_is_a_distinct_instance() -> None:
    """Two roles on the same provider type must not share one object."""
    cfg = _config(
        llm_provider="openai",
        llm_model="gpt-4o",
        llm_credentials=b"sk-chat-key",
        openai_base_url="https://api.openai.com/v1",
        embed_provider="openai",
        embed_base_url="http://vllm:8000/v1",
        embed_credentials=b"sk-embed-key",
    )
    registry = ProviderRegistry(cfg, SECRET)
    assert registry.for_embed() is not registry.for_llm()


def test_embed_role_without_overrides_still_reuses_chat_instance() -> None:
    """Inheritance must not multiply instances — that was the old behaviour."""
    cfg = _config(
        llm_provider="openai",
        llm_model="gpt-4o",
        llm_credentials=b"sk-chat-key",
        embed_provider="openai",
    )
    registry = ProviderRegistry(cfg, SECRET)
    assert registry.for_embed() is registry.for_llm()


def test_registry_is_still_a_name_keyed_dict() -> None:
    """Name-keyed lookups written before roles existed keep working."""
    cfg = _config(llm_provider="ollama", llm_model="llama3")
    registry = ProviderRegistry(cfg, SECRET)
    assert isinstance(registry, dict)
    assert registry.get("ollama") is registry.for_llm()


# ---------------------------------------------------------------------------
# 3. HTTP rerank scoring
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload
        self.is_success = True

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


class _FakeClient:
    """Stands in for httpx.AsyncClient; records the body it was handed."""

    sent: ClassVar[dict[str, Any]] = {}

    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def __call__(self, *args: Any, **kwargs: Any) -> Self:
        return self

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def post(self, url: str, json: Any, headers: Any) -> _FakeResponse:
        type(self).sent = {"url": url, "json": json, "headers": headers}
        return _FakeResponse(self._payload)


def _run_rerank(reranker: Any, payload: Any, passages: list[str]) -> list[float]:
    import httpx

    client = _FakeClient(payload)
    original = httpx.AsyncClient
    httpx.AsyncClient = client  # type: ignore[assignment]
    try:
        return asyncio.run(reranker.rerank("q", passages))
    finally:
        httpx.AsyncClient = original  # type: ignore[assignment]


def test_http_reranker_maps_sorted_results_back_to_input_order() -> None:
    """The API answers best-first; the protocol requires input order."""
    payload = {
        "results": [
            {"index": 2, "relevance_score": 0.9},
            {"index": 0, "relevance_score": 0.4},
            {"index": 1, "relevance_score": 0.1},
        ]
    }
    scores = _run_rerank(
        HTTPReranker("http://vllm:8000", "bge-reranker"), payload, ["a", "b", "c"]
    )
    assert scores == [0.4, 0.1, 0.9]


def test_http_reranker_clamps_raw_logits_into_range() -> None:
    payload = {"results": [{"index": 0, "relevance_score": 7.3},
                           {"index": 1, "relevance_score": -2.0}]}
    scores = _run_rerank(HTTPReranker("http://vllm:8000", "m"), payload, ["a", "b"])
    assert scores == [1.0, 0.0]


def test_http_reranker_requests_every_passage() -> None:
    """A truncated response would sink the missing passages at score 0."""
    payload = {"results": [{"index": 0, "relevance_score": 0.5}]}
    _run_rerank(HTTPReranker("http://vllm:8000", "m"), payload, ["a", "b", "c"])
    assert _FakeClient.sent["json"]["top_n"] == 3


def test_tei_reranker_reads_bare_array() -> None:
    """TEI is not Cohere-compatible: bare array, 'texts', 'score'."""
    payload = [{"index": 1, "score": 0.8}, {"index": 0, "score": 0.2}]
    scores = _run_rerank(TEIReranker("http://tei:80", "m"), payload, ["a", "b"])
    assert scores == [0.2, 0.8]
    assert "texts" in _FakeClient.sent["json"]
    assert _FakeClient.sent["json"]["raw_scores"] is False


def test_http_reranker_failure_degrades_to_neutral() -> None:
    """A bad endpoint must fall back to vector order, never raise."""
    reranker = HTTPReranker("http://unreachable.invalid", "m")
    scores = asyncio.run(reranker.rerank("q", ["a", "b"]))
    assert scores == [0.5, 0.5]


def test_build_reranker_cohere_api_inherits_openai_base_url() -> None:
    cfg = _config(
        llm_provider="openai",
        llm_model="gpt-4o",
        llm_credentials=b"sk-key",
        openai_base_url="http://vllm:8000/v1",
        rerank_enabled=True,
        rerank_method="cohere_api",
    )
    reranker = build_reranker(cfg, {})
    assert isinstance(reranker, HTTPReranker)
    assert reranker._base_url == "http://vllm:8000/v1"


def test_build_reranker_http_without_endpoint_disables_rather_than_raises() -> None:
    cfg = _config(rerank_enabled=True, rerank_method="tei")
    assert build_reranker(cfg, {}) is None


# ---------------------------------------------------------------------------
# 4. Re-index trigger
# ---------------------------------------------------------------------------


def test_repointing_embed_endpoint_changes_effective_endpoint() -> None:
    """Same model name, different server = different vector space."""
    before = _config(embed_provider="ollama", ollama_url="http://a:11434")
    after = _config(
        embed_provider="ollama",
        ollama_url="http://a:11434",
        embed_base_url="http://b:11434",
    )
    assert effective_embed_endpoint(before) != effective_embed_endpoint(after)


def test_rotating_embed_credentials_does_not_change_endpoint() -> None:
    """Key rotation yields identical vectors — no re-index prompt."""
    before = _config(
        embed_provider="openai",
        embed_base_url="http://x/v1",
        embed_credentials=b"sk-old",
    )
    after = _config(
        embed_provider="openai",
        embed_base_url="http://x/v1",
        embed_credentials=b"sk-new",
    )
    assert effective_embed_endpoint(before) == effective_embed_endpoint(after)
