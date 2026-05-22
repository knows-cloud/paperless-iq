"""AWS Bedrock LLM provider."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import boto3
import botocore.exceptions
from botocore.config import Config

from backend.providers.encryption import decrypt_credential

logger = logging.getLogger(__name__)

# Bedrock client timeouts: 10 s to connect, 120 s to read a completion response.
# Titan embeddings are fast (<5 s), so 120 s is a generous ceiling for Claude completions.
_BEDROCK_CONFIG = Config(
    connect_timeout=10,
    read_timeout=120,
    retries={"max_attempts": 0},  # no automatic retries — let caller decide
)


class BedrockProvider:
    """LLMProvider implementation backed by AWS Bedrock."""

    def __init__(
        self,
        region: str,
        access_key_id_enc: str,
        secret_access_key_enc: str,
        secret_key: str,
        model: str = "anthropic.claude-3-haiku-20240307-v1:0",
        session_token_enc: str | None = None,
        embed_model: str = "amazon.titan-embed-text-v1",
    ) -> None:
        self._region = region
        self._access_key_id_enc = access_key_id_enc
        self._secret_access_key_enc = secret_access_key_enc
        self._secret_key = secret_key
        self._model = model
        self._session_token_enc = session_token_enc
        self._embed_model = embed_model
        self._cached_runtime: Any = None  # lazily created; invalidated on token expiry

    def _boto_kwargs(self) -> dict:
        """Build the common keyword arguments for every boto3 client."""
        kwargs: dict = {
            "region_name": self._region,
            "aws_access_key_id": decrypt_credential(self._access_key_id_enc, self._secret_key),
            "aws_secret_access_key": decrypt_credential(self._secret_access_key_enc, self._secret_key),
            "config": _BEDROCK_CONFIG,
        }
        if self._session_token_enc:
            kwargs["aws_session_token"] = decrypt_credential(self._session_token_enc, self._secret_key)
        return kwargs

    def _runtime_client(self) -> Any:
        """Return the cached bedrock-runtime client, creating it on first call."""
        if self._cached_runtime is None:
            self._cached_runtime = boto3.client("bedrock-runtime", **self._boto_kwargs())
        return self._cached_runtime

    def _invalidate_runtime_client(self) -> None:
        """Drop the cached client so the next call builds a fresh one."""
        self._cached_runtime = None

    def _bedrock_client(self) -> Any:
        return boto3.client("bedrock", **self._boto_kwargs())

    async def chat(self, messages: list[dict], max_tokens: int) -> str:
        """Invoke Bedrock model with a multi-turn messages array.

        Bedrock's Claude API accepts a top-level ``system`` field rather than
        a system-role message, so we extract it from the messages list first.
        """
        system: str | None = None
        filtered = []
        for m in messages:
            if m.get("role") == "system":
                system = m["content"]
            else:
                filtered.append(m)

        # Log estimated token cost so you can correlate with your AWS bill.
        total_chars = sum(len(m.get("content", "")) for m in filtered)
        if system:
            total_chars += len(system)
        logger.info(
            "Bedrock chat(): model=%s  ~%d chars (~%d tokens est.)  max_output=%d",
            self._model, total_chars, total_chars // 4, max_tokens,
        )

        body_dict: dict = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "messages": filtered,
        }
        if system:
            body_dict["system"] = system
        body = json.dumps(body_dict)

        loop = asyncio.get_running_loop()

        for attempt in range(2):
            client = self._runtime_client()

            def _invoke() -> dict:
                response = client.invoke_model(modelId=self._model, body=body)
                return json.loads(response["body"].read())

            try:
                result = await loop.run_in_executor(None, _invoke)
                break
            except botocore.exceptions.ClientError as exc:
                if exc.response["Error"]["Code"] == "ExpiredTokenException" and attempt == 0:
                    logger.info("Bedrock chat(): session token expired — refreshing client.")
                    self._invalidate_runtime_client()
                    continue
                raise

        output_text = result["content"][0]["text"]
        usage = result.get("usage", {})
        logger.info(
            "Bedrock chat(): input_tokens=%s  output_tokens=%s",
            usage.get("input_tokens", "?"), usage.get("output_tokens", "?"),
        )
        return output_text

    async def complete(self, prompt: str, max_tokens: int) -> str:
        """Single-turn convenience wrapper around chat()."""
        return await self.chat([{"role": "user", "content": prompt}], max_tokens)

    async def embed(self, text: str) -> list[float]:
        """Generate embeddings using the configured Bedrock embedding model.

        Supported model families and their request/response formats:
          - amazon.titan-embed-text-v1   : inputText → embedding[]  (1536-dim)
          - amazon.titan-embed-text-v2:0 : inputText → embedding[]  (1024-dim default)
          - cohere.embed-english-v3      : texts[]   → embeddings[][] (1024-dim)
          - cohere.embed-multilingual-v3 : texts[]   → embeddings[][] (1024-dim)
        """
        model = self._embed_model

        is_cohere = model.startswith("cohere.")
        is_titan_v2 = model == "amazon.titan-embed-text-v2:0"

        if is_cohere:
            # Cohere expects a list of texts; input_type "search_document" optimises
            # for retrieval (use "search_query" when embedding a query instead).
            body = json.dumps({"texts": [text], "input_type": "search_document"})
        elif is_titan_v2:
            # Titan v2 supports normalisation and configurable dimensions (256/512/1024)
            body = json.dumps({"inputText": text, "dimensions": 1024, "normalize": True})
        else:
            # Titan v1 (and any unknown Titan variant)
            body = json.dumps({"inputText": text})

        loop = asyncio.get_running_loop()

        for attempt in range(2):
            client = self._runtime_client()

            def _invoke() -> dict:
                response = client.invoke_model(
                    modelId=model,
                    body=body,
                    contentType="application/json",
                    accept="application/json",
                )
                return json.loads(response["body"].read())

            try:
                result = await loop.run_in_executor(None, _invoke)
                break
            except botocore.exceptions.ClientError as exc:
                if exc.response["Error"]["Code"] == "ExpiredTokenException" and attempt == 0:
                    logger.info("Bedrock embed(): session token expired — refreshing client.")
                    self._invalidate_runtime_client()
                    continue
                raise

        if is_cohere:
            return result["embeddings"][0]
        return result["embedding"]

    async def health_check(self) -> bool:
        """Return True if Bedrock credentials are configured.

        Deliberately avoids any network call — ListFoundationModels is billed
        and would be called every few seconds by the status-polling loop.
        Credential presence is sufficient to show the provider as 'online'.
        """
        try:
            kwargs = self._boto_kwargs()
            return bool(
                kwargs.get("aws_access_key_id")
                and kwargs.get("aws_secret_access_key")
                and self._region
            )
        except Exception:
            return False
