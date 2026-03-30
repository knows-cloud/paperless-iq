"""Anthropic Claude LLM provider."""

from __future__ import annotations

import anthropic

from backend.providers.encryption import decrypt_credential


class AnthropicProvider:
    """LLMProvider implementation backed by Anthropic's API."""

    def __init__(self, api_key_enc: str, model: str, secret_key: str) -> None:
        self._api_key_enc = api_key_enc
        self._model = model
        self._secret_key = secret_key

    def _client(self) -> anthropic.AsyncAnthropic:
        api_key = decrypt_credential(self._api_key_enc, self._secret_key)
        return anthropic.AsyncAnthropic(api_key=api_key)

    async def complete(self, prompt: str, max_tokens: int) -> str:
        """Send a completion request to Anthropic and return the response text."""
        client = self._client()
        message = await client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    async def embed(self, text: str) -> list[float]:
        """Anthropic does not support embeddings."""
        raise NotImplementedError("Anthropic does not support embeddings")

    async def health_check(self) -> bool:
        """Return True if the Anthropic API is reachable."""
        try:
            client = self._client()
            await client.models.list()
            return True
        except Exception:
            return False
