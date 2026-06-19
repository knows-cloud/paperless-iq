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

# Transient Bedrock errors worth a short in-process retry before bubbling up to
# the indexer's circuit-breaker. These are capacity/throttle blips, not config
# errors, so absorbing them here keeps the breaker closed during normal bursts.
_TRANSIENT_EMBED_ERRORS = frozenset({
    "ThrottlingException",
    "ServiceUnavailableException",
    "ModelTimeoutException",
    "InternalServerException",
})


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

    @property
    def region(self) -> str:
        """The configured AWS region (used to build Rerank model ARNs)."""
        return self._region

    def rerank_client(self) -> Any:
        """Return a bedrock-agent-runtime client for the Rerank API, built from
        the same credentials as the runtime client."""
        return boto3.client("bedrock-agent-runtime", **self._boto_kwargs())

    async def chat(
        self,
        messages: list[dict],
        max_tokens: int,
        output_schema: dict | None = None,
        images: list[bytes] | None = None,
    ) -> str:
        """Invoke any Bedrock model via the Converse API.

        The Converse API accepts a single unified request shape for all model
        families (Claude, Nova, Llama, Mistral, …) — Bedrock handles per-model
        translation internally, so no branching is needed here.

        When ``output_schema`` is provided, uses outputConfig.textFormat for
        native structured JSON output.  When ``images`` are provided, injects
        them as Converse image content blocks into the last user message.
        """
        system: list[dict] = []
        converse_messages: list[dict] = []
        for m in messages:
            if m.get("role") == "system":
                system = [{"text": m["content"]}]
            else:
                content = m["content"]
                # Converse API requires content as an array of content blocks.
                if isinstance(content, str):
                    content = [{"text": content}]
                converse_messages.append({"role": m["role"], "content": content})

        if images:
            converse_messages = _inject_images_bedrock(converse_messages, images)

        total_chars = sum(
            sum(len(b.get("text", "")) for b in m["content"] if isinstance(b, dict))
            for m in converse_messages
        )
        if system:
            total_chars += len(system[0]["text"])
        logger.info(
            "Bedrock chat(): model=%s  ~%d chars (~%d tokens est.)  max_output=%d",
            self._model, total_chars, total_chars // 4, max_tokens,
        )

        converse_kwargs: dict = {
            "modelId": self._model,
            "messages": converse_messages,
            "inferenceConfig": {"maxTokens": max_tokens},
        }
        if system:
            converse_kwargs["system"] = system
        if output_schema:
            # Bedrock requires the schema serialised as a JSON string inside jsonSchema.schema.
            converse_kwargs["outputConfig"] = {
                "textFormat": {
                    "type": "json_schema",
                    "structure": {
                        "jsonSchema": {
                            "schema": json.dumps(output_schema),
                            "name": "document_classification",
                            "description": "Structured metadata classification result",
                        }
                    },
                }
            }

        loop = asyncio.get_running_loop()

        outputconfig_removed = False
        token_refreshed = False
        for _attempt in range(3):
            client = self._runtime_client()

            def _invoke() -> dict:
                return client.converse(**converse_kwargs)

            try:
                result = await loop.run_in_executor(None, _invoke)
                break
            except botocore.exceptions.ClientError as exc:
                code = exc.response["Error"]["Code"]
                msg = exc.response["Error"].get("Message", "")
                if (
                    code == "ValidationException"
                    and "outputConfig" in msg
                    and "outputConfig" in converse_kwargs
                    and not outputconfig_removed
                ):
                    logger.warning(
                        "Bedrock chat(): model=%s rejected outputConfig — "
                        "falling back to unstructured output. Full error: %s",
                        self._model, msg,
                    )
                    del converse_kwargs["outputConfig"]
                    outputconfig_removed = True
                    continue
                if code == "ExpiredTokenException" and not token_refreshed:
                    logger.info("Bedrock chat(): session token expired — refreshing client.")
                    self._invalidate_runtime_client()
                    token_refreshed = True
                    continue
                raise

        output_text = result["output"]["message"]["content"][0]["text"]
        usage = result.get("usage", {})
        logger.info(
            "Bedrock chat(): input_tokens=%s  output_tokens=%s",
            usage.get("inputTokens", "?"), usage.get("outputTokens", "?"),
        )
        return output_text

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

    def embed_batch_limit(self) -> int:
        """Max texts the current embed model accepts in a single API call.

        Only Cohere accepts a list of texts (``texts[]``, up to 96 per call).
        Titan takes a single ``inputText`` string, so it reports 1 and the store
        keeps using the one-text-per-call path for it.
        """
        return 96 if "cohere." in self._embed_model else 1

    async def _invoke_embed_model(self, body: str) -> dict:
        """Invoke the embed model with token-refresh + transient-error retry.

        Refreshes the client once on ExpiredTokenException, and retries transient
        capacity/throttle errors with exponential backoff (1→2→4→8 s). Anything
        else — or a transient error that outlasts the retries — propagates so the
        indexer's circuit-breaker can take over.
        """
        model = self._embed_model
        loop = asyncio.get_running_loop()
        token_refreshed = False
        delay = 1.0

        for attempt in range(5):
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
                return await loop.run_in_executor(None, _invoke)
            except botocore.exceptions.ClientError as exc:
                code = exc.response["Error"]["Code"]
                if code == "ExpiredTokenException" and not token_refreshed:
                    logger.info("Bedrock embed(): session token expired — refreshing client.")
                    self._invalidate_runtime_client()
                    token_refreshed = True
                    continue
                if code in _TRANSIENT_EMBED_ERRORS and attempt < 4:
                    logger.warning(
                        "Bedrock embed(): transient %s — retry %d/4 in %.0fs.",
                        code, attempt + 1, delay,
                    )
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 8.0)
                    continue
                raise
        # Unreachable: the loop either returns or raises, but keep the type checker happy.
        raise RuntimeError("Bedrock embed(): retry loop exhausted without result.")

    def _embed_body(self, texts: list[str], *, is_query: bool = False) -> str:
        """Build the invoke_model body for the configured embed model.

        Supported model families and their request/response formats:
          - amazon.titan-embed-text-v1   : inputText → embedding[]  (1536-dim)
          - amazon.titan-embed-text-v2:0 : inputText → embedding[]  (1024-dim default)
          - cohere.embed-english-v3      : texts[]   → embeddings[][]        (1024-dim)
          - cohere.embed-multilingual-v3 : texts[]   → embeddings[][]        (1024-dim)
          - cohere.embed-v4:0            : texts[]   → embeddings[][] or     (1536-dim)
                                           embeddings{type:[][]} by response_type

        The family is matched as a substring, not a prefix: cross-Region
        inference-profile IDs prepend a region group (e.g. "eu.cohere.embed-v4:0",
        "us.amazon.titan-..."), and v4 in particular is only invokable through an
        inference profile. A prefix check would misroute those to the wrong body.

        ``is_query`` selects Cohere's ``input_type`` (search_query vs
        search_document); Titan has no equivalent and ignores it.

        Titan accepts only a single string, so a multi-text batch is rejected here
        rather than silently embedding just the first text.
        """
        model = self._embed_model

        if "cohere." in model:
            # Cohere expects a list of texts; input_type "search_query" optimises a
            # search query, "search_document" optimises a doc being indexed.
            # This body is valid for both Embed v3 and v4 — embedding_types is left
            # unset so v4 returns float vectors; the parser below handles both the
            # flat ("embeddings_floats") and keyed ("embeddings_by_type") shapes.
            input_type = "search_query" if is_query else "search_document"
            return json.dumps({"texts": texts, "input_type": input_type})

        if len(texts) != 1:
            raise ValueError(
                f"Bedrock embed model '{model}' accepts one text per call, got {len(texts)}."
            )
        text = texts[0]

        if "titan-embed-text-v2" in model:
            # Titan v2 supports normalisation and configurable dimensions (256/512/1024)
            return json.dumps({"inputText": text, "dimensions": 1024, "normalize": True})
        if "titan-embed" in model:
            # Titan v1 and older Titan embed variants
            return json.dumps({"inputText": text})

        # Refuse unknown models rather than silently sending the Titan body —
        # that would produce wrong embeddings (or a cryptic provider error) with
        # no signal. Raising surfaces it in the "Embedding paused" banner so the
        # user can pick a supported model instead.
        raise ValueError(
            f"Unsupported Bedrock embedding model '{model}'. Supported families: "
            "amazon.titan-embed-text-v1, amazon.titan-embed-text-v2:0, "
            "cohere.embed-english-v3, cohere.embed-multilingual-v3, cohere.embed-v4:0 "
            "(or their cross-Region inference-profile IDs). "
            "Set a supported model in Settings → AI Provider."
        )

    @staticmethod
    def _parse_cohere_embeddings(result: dict) -> list[list[float]]:
        embeddings = result["embeddings"]
        if isinstance(embeddings, dict):
            # v4 "embeddings_by_type": {"float": [[...]], "int8": [[...]]}.
            # Prefer float; fall back to whatever type was returned.
            return embeddings.get("float") or next(iter(embeddings.values()))
        # v3 / v4 "embeddings_floats": [[...]]
        return embeddings

    async def embed(self, text: str, *, is_query: bool = False) -> list[float]:
        """Generate an embedding vector for a single text.

        ``is_query`` selects Cohere's ``input_type`` (search_query vs
        search_document); Titan ignores it.
        """
        result = await self._invoke_embed_model(self._embed_body([text], is_query=is_query))
        if "cohere." in self._embed_model:
            return self._parse_cohere_embeddings(result)[0]
        return result["embedding"]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed several texts in one API call (Cohere only; see embed_batch_limit).

        Returns one vector per input text, in order. Callers should keep batches
        within ``embed_batch_limit()`` — Cohere rejects oversized batches.
        """
        if not texts:
            return []
        result = await self._invoke_embed_model(self._embed_body(texts))
        if "cohere." in self._embed_model:
            return self._parse_cohere_embeddings(result)
        # Non-batching models only ever reach here with a single text.
        return [result["embedding"]]

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


def _inject_images_bedrock(
    converse_messages: list[dict], images: list[bytes]
) -> list[dict]:
    """Return a copy of converse_messages with Bedrock image blocks prepended
    to the last user message's content array."""
    if not converse_messages:
        return converse_messages
    converse_messages = [m.copy() for m in converse_messages]
    for i in reversed(range(len(converse_messages))):
        if converse_messages[i].get("role") == "user":
            content = list(converse_messages[i]["content"])
            image_blocks = [
                {
                    "image": {
                        "format": "jpeg",
                        "source": {
                            "bytes": img,
                        },
                    }
                }
                for img in images
            ]
            converse_messages[i] = {
                **converse_messages[i],
                "content": image_blocks + content,
            }
            break
    return converse_messages
