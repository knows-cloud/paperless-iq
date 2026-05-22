"""Ollama local LLM provider."""

from __future__ import annotations

import ollama


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

    async def chat(self, messages: list[dict], max_tokens: int) -> str:
        """Send a multi-turn chat request to Ollama.

        Ollama's chat API accepts a ``system`` role natively, so messages are
        passed through as-is.
        """
        client = self._client()
        response = await client.chat(
            model=self._model,
            messages=messages,
            options={"num_predict": max_tokens},
        )
        return response["message"]["content"]

    async def complete(self, prompt: str, max_tokens: int) -> str:
        """Single-turn convenience wrapper around chat()."""
        return await self.chat([{"role": "user", "content": prompt}], max_tokens)

    async def embed(self, text: str) -> list[float]:
        """Generate embeddings via Ollama."""
        client = self._client()
        response = await client.embeddings(model=self._model, prompt=text)
        return response["embedding"]

    async def health_check(self) -> bool:
        """Return True if the Ollama instance is reachable."""
        try:
            client = self._client()
            await client.list()
            return True
        except Exception:
            return False
