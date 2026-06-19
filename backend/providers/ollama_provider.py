"""Ollama local LLM provider."""

from __future__ import annotations

import base64
import logging

import ollama

logger = logging.getLogger(__name__)


class OllamaProvider:
    """LLMProvider implementation backed by a local Ollama instance.

    A single ``ollama.AsyncClient`` is created on first use and reused for
    all subsequent calls — this keeps the underlying connection pool alive
    across requests instead of rebuilding it on every call.
    """

    def __init__(self, base_url: str, model: str) -> None:
        self._base_url = base_url
        self._model = model
        self._client_instance: ollama.AsyncClient | None = None

    def _client(self) -> ollama.AsyncClient:
        """Return the shared AsyncClient, creating it on first call."""
        if self._client_instance is None:
            self._client_instance = ollama.AsyncClient(host=self._base_url)
        return self._client_instance

    async def chat(
        self,
        messages: list[dict],
        max_tokens: int,
        output_schema: dict | None = None,
        images: list[bytes] | None = None,
    ) -> str:
        """Send a multi-turn chat request to Ollama.

        When ``output_schema`` is provided, passes it as the ``format``
        option for native structured JSON output (Ollama ≥0.5).
        When ``images`` are provided, injects them as base64 strings into
        the last user message.
        """
        client = self._client()
        if images:
            messages = _inject_images_ollama(messages, images)

        kwargs: dict = dict(
            model=self._model,
            messages=messages,
            options={"num_predict": max_tokens},
        )
        if output_schema:
            kwargs["format"] = output_schema

        response = await client.chat(**kwargs)
        return response["message"]["content"]

    async def complete(
        self,
        prompt: str,
        max_tokens: int,
        output_schema: dict | None = None,
        images: list[bytes] | None = None,
    ) -> str:
        """Single-turn convenience wrapper around chat()."""
        return await self.chat(
            [{"role": "user", "content": prompt}],
            max_tokens,
            output_schema=output_schema,
            images=images,
        )

    async def embed(self, text: str, *, is_query: bool = False) -> list[float]:
        """Generate embeddings via Ollama (no query/document distinction)."""
        client = self._client()
        response = await client.embeddings(model=self._model, prompt=text)
        return response["embedding"]

    async def supports_vision(self) -> bool:
        """Return True if the configured model reports vision capability.

        Uses the local /api/show endpoint — no external network call needed.
        Falls back to False on any error (model not pulled, Ollama unreachable).
        """
        try:
            client = self._client()
            info = await client.show(self._model)
            capabilities = getattr(info, "capabilities", None) or info.get("capabilities", [])
            return "vision" in capabilities
        except Exception:
            logger.debug("supports_vision(): could not determine capabilities for %s", self._model)
            return False

    async def health_check(self) -> bool:
        """Return True if the Ollama instance is reachable."""
        try:
            client = self._client()
            await client.list()
            return True
        except Exception:
            return False


def _inject_images_ollama(messages: list[dict], images: list[bytes]) -> list[dict]:
    """Return a copy of messages with base64 image strings in the last user message."""
    if not messages:
        return messages
    messages = [m.copy() for m in messages]
    for i in reversed(range(len(messages))):
        if messages[i].get("role") == "user":
            existing_images: list[str] = list(messages[i].get("images", []))
            new_images = [base64.b64encode(img).decode() for img in images]
            messages[i] = {**messages[i], "images": new_images + existing_images}
            break
    return messages
