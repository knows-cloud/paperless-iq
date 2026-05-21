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

    async def chat(self, messages: list[dict], max_tokens: int) -> str:
        """Send a multi-turn chat request to Anthropic.

        Anthropic requires the ``system`` role to be passed as a top-level
        ``system`` parameter rather than as a message entry, so we extract it
        here before forwarding the remaining messages.
        """
        system: str | None = None
        filtered = []
        for m in messages:
            if m.get("role") == "system":
                system = m["content"]
            else:
                filtered.append(m)
        client = self._client()
        kwargs: dict = dict(model=self._model, max_tokens=max_tokens, messages=filtered)
        if system:
            kwargs["system"] = system
        message = await client.messages.create(**kwargs)
        return message.content[0].text

    async def complete(self, prompt: str, max_tokens: int) -> str:
        """Send a single-turn completion request to Anthropic."""
        return await self.chat([{"role": "user", "content": prompt}], max_tokens)

    async def embed(self, text: str) -> list[float]:
        """Anthropic does not support embeddings."""
        raise NotImplementedError("Anthropic does not support embeddings")

    async def health_check(self) -> bool:
        """Return True if an Anthropic API key is configured.

        Avoids a live models.list() call — the API is always reachable if
        credentials are present, and polling it every few seconds is wasteful.
        """
        try:
            api_key = decrypt_credential(self._api_key_enc, self._secret_key)
            return bool(api_key and api_key.strip())
        except Exception:
            return False
