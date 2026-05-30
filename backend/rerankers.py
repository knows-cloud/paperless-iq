"""Rerankers for the shared vector-search query path.

A reranker re-scores ``(query, passage)`` pairs after the vector store returns
its first-pass candidates — the largest single quality lever for retrieval.
Ships disabled (``config.rerank_enabled=False``). When enabled,
``config.rerank_method`` selects the implementation:

- ``"llm"``   — listwise prompt to the already-configured chat provider.
                Reuses the LLM credentials; no new deps.
- ``"local"`` — in-process cross-encoder via ``sentence-transformers``. This is
                an **optional** dependency (``paperless-iq[rerank-local]``) and is
                imported lazily on first use; the first run downloads the model
                weights (progress logged by ``huggingface_hub``).
- ``"api"``   — AWS Bedrock Rerank using the configured Bedrock credentials.

All implementations return scores normalised to ``[0, 1]`` in input order and
degrade gracefully: on any failure they return neutral scores (preserving the
vector-search order) rather than raising into the request path. The one
exception is the local method's missing-dependency error, which surfaces a
clear, actionable message.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from typing import Any

from backend.protocols import LLMProvider, Reranker

logger = logging.getLogger(__name__)


def _sigmoid(x: float) -> float:
    """Map a cross-encoder logit to (0, 1)."""
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 0.0 if x < 0 else 1.0


class LLMReranker:
    """Listwise reranking via the configured chat provider (reuses LLM creds)."""

    # Cap passage length sent to the LLM to bound token cost.
    _MAX_PASSAGE_CHARS = 1000

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    async def rerank(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        numbered = "\n".join(
            f"[{i}] {p[: self._MAX_PASSAGE_CHARS]}" for i, p in enumerate(passages)
        )
        prompt = (
            "Rate how well each passage answers the query, from 0 (irrelevant) to "
            "10 (directly answers it). Respond with JSON only: "
            '{"scores": [<one integer per passage, in the same order>]}.\n\n'
            f"Query: {query}\n\nPassages:\n{numbered}"
        )
        schema = {
            "type": "object",
            "properties": {"scores": {"type": "array", "items": {"type": "number"}}},
            "required": ["scores"],
        }
        try:
            raw = await self._provider.complete(prompt, max_tokens=512, output_schema=schema)
            data = json.loads(raw)
            scores = [float(s) for s in data.get("scores", [])]
        except Exception:
            logger.warning("LLM reranker failed; preserving vector order.", exc_info=True)
            return [0.5] * len(passages)
        # Align length defensively, then squash 0..10 into [0, 1].
        if len(scores) != len(passages):
            scores = (scores + [0.0] * len(passages))[: len(passages)]
        return [max(0.0, min(1.0, s / 10.0)) for s in scores]


class LocalCrossEncoderReranker:
    """In-process cross-encoder via sentence-transformers (optional dependency).

    The heavy import (``sentence_transformers`` → ``torch``) and the model load
    happen lazily on first ``rerank`` call, so merely selecting — but not
    enabling — this method costs nothing.
    """

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model: Any = None

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:  # pragma: no cover - exercised via build_reranker
            raise RuntimeError(
                "The 'local' reranker needs optional dependencies. Install them with "
                "`pip install 'paperless-iq[rerank-local]'` (adds sentence-transformers "
                "and torch), or choose the 'llm' / 'api' rerank method instead."
            ) from exc
        logger.info(
            "Loading local reranker '%s' — first run downloads the model weights "
            "(progress is logged by huggingface_hub).",
            self._model_name,
        )
        self._model = CrossEncoder(self._model_name)
        logger.info("Local reranker '%s' ready.", self._model_name)

    async def rerank(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        loop = asyncio.get_running_loop()

        def _predict() -> list[float]:
            self._ensure_model()
            pairs = [[query, p] for p in passages]
            return [float(s) for s in self._model.predict(pairs)]

        try:
            raw = await loop.run_in_executor(None, _predict)
        except RuntimeError:
            raise  # missing-dependency message must surface
        except Exception:
            logger.warning("Local reranker failed; preserving vector order.", exc_info=True)
            return [0.5] * len(passages)
        return [_sigmoid(s) for s in raw]


class BedrockReranker:
    """AWS Bedrock Rerank using the configured Bedrock provider's credentials."""

    def __init__(self, provider: Any, model: str) -> None:
        self._provider = provider  # BedrockProvider — supplies client + region
        self._model = model

    def _model_arn(self) -> str:
        if self._model.startswith("arn:"):
            return self._model
        region = self._provider.region
        return f"arn:aws:bedrock:{region}::foundation-model/{self._model}"

    async def rerank(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        loop = asyncio.get_running_loop()

        def _call() -> dict:
            client = self._provider.rerank_client()
            return client.rerank(
                queries=[{"type": "TEXT", "textQuery": {"text": query}}],
                sources=[
                    {
                        "type": "INLINE",
                        "inlineDocumentSource": {
                            "type": "TEXT",
                            "textDocument": {"text": p},
                        },
                    }
                    for p in passages
                ],
                rerankingConfiguration={
                    "type": "BEDROCK_RERANKING_MODEL",
                    "bedrockRerankingConfiguration": {
                        "numberOfResults": len(passages),
                        "modelConfiguration": {"modelArn": self._model_arn()},
                    },
                },
            )

        try:
            resp = await loop.run_in_executor(None, _call)
        except Exception:
            logger.warning("Bedrock reranker failed; preserving vector order.", exc_info=True)
            return [0.5] * len(passages)

        # Bedrock returns {index, relevanceScore} (0..1) per input document.
        scores = [0.0] * len(passages)
        for item in resp.get("results", []):
            idx = item.get("index")
            if isinstance(idx, int) and 0 <= idx < len(passages):
                scores[idx] = float(item.get("relevanceScore", 0.0))
        return scores


def build_reranker(config: Any, providers: dict | None) -> Reranker | None:
    """Construct the configured reranker, or None when reranking is disabled
    or cannot be satisfied. Never raises — a failure disables reranking."""
    if not getattr(config, "rerank_enabled", False):
        return None

    method = getattr(config, "rerank_method", "llm")
    try:
        if method == "llm":
            provider = providers.get(config.llm_provider) if providers else None
            if provider is None:
                logger.warning(
                    "Rerank method 'llm' selected but provider '%s' is unavailable; "
                    "reranking disabled.", config.llm_provider,
                )
                return None
            return LLMReranker(provider)

        if method == "local":
            # Construction is cheap (torch is imported lazily on first rerank).
            return LocalCrossEncoderReranker(config.rerank_model)

        if method == "api":
            provider = providers.get("bedrock") if providers else None
            if config.llm_provider == "bedrock" and provider is not None:
                return BedrockReranker(provider, config.rerank_model)
            logger.warning(
                "Rerank method 'api' currently requires Bedrock as the LLM provider; "
                "reranking disabled."
            )
            return None
    except Exception:
        logger.warning("Failed to build reranker (method=%s); reranking disabled.", method, exc_info=True)
        return None

    logger.warning("Unknown rerank_method '%s'; reranking disabled.", method)
    return None
