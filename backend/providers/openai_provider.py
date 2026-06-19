"""OpenAI (and compatible) LLM provider."""

from __future__ import annotations

import base64

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
        embed_model: str = "text-embedding-3-small",
    ) -> None:
        self._api_key_enc = api_key_enc
        self._model = model
        self._secret_key = secret_key
        self._base_url = base_url
        self._embed_model = embed_model

    def _client(self) -> openai.AsyncOpenAI:
        api_key = decrypt_credential(self._api_key_enc, self._secret_key)
        return openai.AsyncOpenAI(api_key=api_key, base_url=self._base_url)

    async def chat(
        self,
        messages: list[dict],
        max_tokens: int,
        output_schema: dict | None = None,
        images: list[bytes] | None = None,
    ) -> str:
        """Send a multi-turn chat request to OpenAI.

        When ``output_schema`` is provided, uses response_format with JSON
        schema for native structured output.  When ``images`` are provided,
        injects them as base64 image_url blocks into the last user message.
        """
        if images:
            messages = _inject_images_openai(messages, images)

        client = self._client()
        kwargs: dict = dict(
            model=self._model,
            max_tokens=max_tokens,
            messages=messages,
        )
        if output_schema:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "document_classification",
                    "schema": output_schema,
                    "strict": True,
                },
            }

        response = await client.chat.completions.create(**kwargs)
        return response.choices[0].message.content

    async def complete(
        self,
        prompt: str,
        max_tokens: int,
        output_schema: dict | None = None,
        images: list[bytes] | None = None,
    ) -> str:
        """Send a single-turn chat completion request to OpenAI."""
        return await self.chat(
            [{"role": "user", "content": prompt}],
            max_tokens,
            output_schema=output_schema,
            images=images,
        )

    async def embed(self, text: str, *, is_query: bool = False) -> list[float]:
        """Generate embeddings using the configured embed model.

        OpenAI embedding models are symmetric, so ``is_query`` is ignored.
        """
        client = self._client()
        response = await client.embeddings.create(
            model=self._embed_model,
            input=text,
        )
        return response.data[0].embedding

    async def health_check(self) -> bool:
        """Return True if an OpenAI API key is configured."""
        try:
            api_key = decrypt_credential(self._api_key_enc, self._secret_key)
            return bool(api_key and api_key.strip())
        except Exception:
            return False


def _inject_images_openai(messages: list[dict], images: list[bytes]) -> list[dict]:
    """Return a copy of messages with image_url blocks prepended to the last user message."""
    if not messages:
        return messages
    messages = [m.copy() for m in messages]
    for i in reversed(range(len(messages))):
        if messages[i].get("role") == "user":
            content = messages[i]["content"]
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            image_blocks = [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64.b64encode(img).decode()}"
                    },
                }
                for img in images
            ]
            messages[i] = {**messages[i], "content": image_blocks + content}
            break
    return messages
