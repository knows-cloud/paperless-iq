"""Provider registry — factory for LLM provider instances."""

from __future__ import annotations

import json
import os

from backend.models import PaperlessIQConfig
from backend.protocols import LLMProvider
from backend.providers import (
    AnthropicProvider,
    BedrockProvider,
    OllamaProvider,
    OpenAIProvider,
)
from backend.providers.encryption import encrypt_credential


def build_providers(
    config: PaperlessIQConfig,
    secret_key: str,
) -> dict[str, LLMProvider]:
    """Instantiate the configured LLM provider.

    Returns a dict mapping provider name to LLMProvider instance.
    Raises ValueError if credentials are required but missing.
    """
    provider_name = config.llm_provider
    model = config.llm_model
    raw_creds = config.llm_credentials

    if provider_name == "ollama":
        base_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
        provider = OllamaProvider(base_url=base_url, model=model)

    elif provider_name in ("anthropic", "openai"):
        if not raw_creds:
            raise ValueError(
                f"Credentials are required for the '{provider_name}' provider "
                "but llm_credentials is empty."
            )
        api_key = raw_creds.decode() if isinstance(raw_creds, bytes) else raw_creds
        api_key_enc = encrypt_credential(api_key, secret_key)

        if provider_name == "anthropic":
            provider = AnthropicProvider(
                api_key_enc=api_key_enc, model=model, secret_key=secret_key
            )
        else:
            provider = OpenAIProvider(
                api_key_enc=api_key_enc, model=model, secret_key=secret_key
            )

    elif provider_name == "bedrock":
        if not raw_creds:
            raise ValueError(
                "Credentials are required for the 'bedrock' provider "
                "but llm_credentials is empty."
            )
        creds_str = raw_creds.decode() if isinstance(raw_creds, bytes) else raw_creds
        try:
            creds = json.loads(creds_str)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(
                "Bedrock llm_credentials must be a JSON object with "
                "'region', 'access_key_id', and 'secret_access_key' keys."
            ) from exc

        for key in ("region", "access_key_id", "secret_access_key"):
            if key not in creds:
                raise ValueError(
                    f"Bedrock llm_credentials JSON is missing required key '{key}'."
                )

        access_key_enc = encrypt_credential(creds["access_key_id"], secret_key)
        secret_access_key_enc = encrypt_credential(creds["secret_access_key"], secret_key)

        provider = BedrockProvider(
            region=creds["region"],
            access_key_id_enc=access_key_enc,
            secret_access_key_enc=secret_access_key_enc,
            secret_key=secret_key,
            model=model,
        )

    else:
        raise ValueError(f"Unsupported LLM provider: '{provider_name}'")

    return {provider_name: provider}
