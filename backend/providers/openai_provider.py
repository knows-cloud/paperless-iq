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

    async def complete(self, prompt: str, max_tokens: int) -> str:
        """Send a chat completion request to OpenAI."""
        client = self._client()
        response = await client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content

    async def embed(self, text: str) -> list[float]:
        """Generate embeddings using text-embedding-3-small."""
        client = self._client()
        response = await client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )
        return response.data[0].embedding

    async def health_check(self) -> bool:
        """Return True if the OpenAI API is reachable."""
        try:
            client = self._client()
            await client.models.list()
            return True
        except Exception:
            return False
