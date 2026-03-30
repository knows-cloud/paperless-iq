"""AWS Bedrock LLM provider."""

from __future__ import annotations

import json

import boto3

from backend.providers.encryption import decrypt_credential


class BedrockProvider:
    """LLMProvider implementation backed by AWS Bedrock."""

    def __init__(
        self,
        region: str,
        access_key_id_enc: str,
        secret_access_key_enc: str,
        secret_key: str,
        model: str = "anthropic.claude-3-haiku-20240307-v1:0",
    ) -> None:
        self._region = region
        self._access_key_id_enc = access_key_id_enc
        self._secret_access_key_enc = secret_access_key_enc
        self._secret_key = secret_key
        self._model = model

    def _runtime_client(self):
        access_key = decrypt_credential(self._access_key_id_enc, self._secret_key)
        secret_key = decrypt_credential(self._secret_access_key_enc, self._secret_key)
        return boto3.client(
            "bedrock-runtime",
            region_name=self._region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    def _bedrock_client(self):
        access_key = decrypt_credential(self._access_key_id_enc, self._secret_key)
        secret_key = decrypt_credential(self._secret_access_key_enc, self._secret_key)
        return boto3.client(
            "bedrock",
            region_name=self._region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )

    async def complete(self, prompt: str, max_tokens: int) -> str:
        """Invoke Bedrock model and return completion text."""
        client = self._runtime_client()
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        })
        response = client.invoke_model(modelId=self._model, body=body)
        result = json.loads(response["body"].read())
        return result["content"][0]["text"]

    async def embed(self, text: str) -> list[float]:
        """Generate embeddings using Amazon Titan."""
        client = self._runtime_client()
        body = json.dumps({"inputText": text})
        response = client.invoke_model(
            modelId="amazon.titan-embed-text-v1",
            body=body,
            contentType="application/json",
            accept="application/json",
        )
        result = json.loads(response["body"].read())
        return result["embedding"]

    async def health_check(self) -> bool:
        """Return True if Bedrock is reachable."""
        try:
            client = self._bedrock_client()
            client.list_foundation_models()
            return True
        except Exception:
            return False
