"""Anthropic Claude LLM provider."""

from __future__ import annotations

import base64

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

    async def chat(
        self,
        messages: list[dict],
        max_tokens: int,
        output_schema: dict | None = None,
        images: list[bytes] | None = None,
    ) -> str:
        """Send a multi-turn chat request to Anthropic.

        When ``output_schema`` is provided, uses output_config.format for
        native structured JSON output.  When ``images`` are provided, injects
        them as base64 image blocks into the last user message.
        """
        system: str | None = None
        filtered: list[dict] = []
        for m in messages:
            if m.get("role") == "system":
                system = m["content"]
            else:
                filtered.append(m)

        # Inject image blocks into the last user message when images are provided.
        if images:
            filtered = _inject_images_anthropic(filtered, images)

        client = self._client()
        kwargs: dict = dict(model=self._model, max_tokens=max_tokens, messages=filtered)
        if system:
            kwargs["system"] = system
        if output_schema:
            kwargs["output_config"] = {
                "format": {"type": "json_schema", "schema": output_schema}
            }

        message = await client.messages.create(**kwargs)
        return message.content[0].text

    async def complete(
        self,
        prompt: str,
        max_tokens: int,
        output_schema: dict | None = None,
        images: list[bytes] | None = None,
    ) -> str:
        """Send a single-turn completion request to Anthropic."""
        return await self.chat(
            [{"role": "user", "content": prompt}],
            max_tokens,
            output_schema=output_schema,
            images=images,
        )

    async def embed(self, text: str) -> list[float]:
        """Anthropic does not support embeddings."""
        raise NotImplementedError("Anthropic does not support embeddings")

    async def health_check(self) -> bool:
        """Return True if an Anthropic API key is configured."""
        try:
            api_key = decrypt_credential(self._api_key_enc, self._secret_key)
            return bool(api_key and api_key.strip())
        except Exception:
            return False


def _inject_images_anthropic(messages: list[dict], images: list[bytes]) -> list[dict]:
    """Return a copy of messages with image blocks prepended to the last user message."""
    if not messages:
        return messages
    messages = [m.copy() for m in messages]
    # Find the last user message to attach images to.
    for i in reversed(range(len(messages))):
        if messages[i].get("role") == "user":
            content = messages[i]["content"]
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            image_blocks = [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": base64.b64encode(img).decode(),
                    },
                }
                for img in images
            ]
            messages[i] = {**messages[i], "content": image_blocks + content}
            break
    return messages
