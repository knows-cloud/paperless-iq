"""OpenAI (and compatible) LLM provider."""

from __future__ import annotations

import openai

from backend.providers.encryption import decrypt_credential


class OpenAIProvider:
    """LLMProvider implementation backed by OpenAI's API."""

    def __init__(
        self,
        api_key_enc: str,
        model: str,
        secret_key: str,
        base_url: str | None = None,
    ) -> None:
        self._api_key_enc = api_key_enc
        self._model = model
        self._secret_key = secret_key
        self._base_url = base_url

    def _client(self) -> openai.AsyncOpenAI:
        api_key = decrypt_credential(self._api_key_enc, self._secret_key)
        return openai.AsyncOpenAI(api_key=api_key, base_url=self._base_url)

    async def chat(self, messages: list[dict], max_tokens: int) -> str:
        """Send a multi-turn chat request to OpenAI.

        OpenAI natively supports the ``system`` role, so messages are passed
        through as-is.
        """
        client = self._client()
        response = await client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=messages,
        )
        return response.choices[0].message.content

    async def complete(self, prompt: str, max_tokens: int) -> str:
        """Send a single-turn chat completion request to OpenAI."""
        return await self.chat([{"role": "user", "content": prompt}], max_tokens)

    async def embed(self, text: str) -> list[float]:
        """Generate embeddings using text-embedding-3-small."""
        client = self._client()
        response = await client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )
        return response.data[0].embedding

    async def health_check(self) -> bool:
        """Return True if an OpenAI API key is configured.

        Avoids a live models.list() call — the API is always reachable if
        credentials are present, and polling it every few seconds is wasteful.
        """
        try:
            api_key = decrypt_credential(self._api_key_enc, self._secret_key)
            return bool(api_key and api_key.strip())
        except Exception:
            return False
