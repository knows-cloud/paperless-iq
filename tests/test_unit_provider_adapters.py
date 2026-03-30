"""Unit tests for provider adapters.

Tests credential masking, health_check delegation, and SDK call construction
for all LLM provider implementations.

Validates: Requirements 3.1, 3.2, 3.4
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.providers.encryption import encrypt_credential, decrypt_credential
from backend.providers.anthropic_provider import AnthropicProvider
from backend.providers.bedrock import BedrockProvider
from backend.providers.ollama_provider import OllamaProvider
from backend.providers.openai_provider import OpenAIProvider

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_SECRET_KEY = "test-secret-key-1234567890abcdef"
PLAINTEXT_API_KEY = "sk-test-plaintext-api-key-12345"
PLAINTEXT_AWS_KEY = "AKIAIOSFODNN7EXAMPLE"
PLAINTEXT_AWS_SECRET = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"


@pytest.fixture
def encrypted_api_key() -> str:
    return encrypt_credential(PLAINTEXT_API_KEY, TEST_SECRET_KEY)


@pytest.fixture
def encrypted_aws_key() -> str:
    return encrypt_credential(PLAINTEXT_AWS_KEY, TEST_SECRET_KEY)


@pytest.fixture
def encrypted_aws_secret() -> str:
    return encrypt_credential(PLAINTEXT_AWS_SECRET, TEST_SECRET_KEY)


@pytest.fixture
def anthropic_provider(encrypted_api_key: str) -> AnthropicProvider:
    return AnthropicProvider(
        api_key_enc=encrypted_api_key,
        model="claude-3-haiku-20240307",
        secret_key=TEST_SECRET_KEY,
    )


@pytest.fixture
def openai_provider(encrypted_api_key: str) -> OpenAIProvider:
    return OpenAIProvider(
        api_key_enc=encrypted_api_key,
        model="gpt-4o",
        secret_key=TEST_SECRET_KEY,
    )


@pytest.fixture
def bedrock_provider(encrypted_aws_key: str, encrypted_aws_secret: str) -> BedrockProvider:
    return BedrockProvider(
        region="us-east-1",
        access_key_id_enc=encrypted_aws_key,
        secret_access_key_enc=encrypted_aws_secret,
        secret_key=TEST_SECRET_KEY,
        model="anthropic.claude-3-haiku-20240307-v1:0",
    )


@pytest.fixture
def ollama_provider() -> OllamaProvider:
    return OllamaProvider(base_url="http://localhost:11434", model="llama3")


# ---------------------------------------------------------------------------
# 1. Encryption round-trip
# ---------------------------------------------------------------------------

class TestEncryptionRoundTrip:
    def test_encrypt_decrypt_roundtrip(self):
        token = encrypt_credential(PLAINTEXT_API_KEY, TEST_SECRET_KEY)
        recovered = decrypt_credential(token, TEST_SECRET_KEY)
        assert recovered == PLAINTEXT_API_KEY

    def test_encrypted_token_differs_from_plaintext(self):
        token = encrypt_credential(PLAINTEXT_API_KEY, TEST_SECRET_KEY)
        assert token != PLAINTEXT_API_KEY

    def test_different_keys_produce_different_tokens(self):
        token1 = encrypt_credential(PLAINTEXT_API_KEY, TEST_SECRET_KEY)
        token2 = encrypt_credential(PLAINTEXT_API_KEY, "different-secret-key-xyz")
        assert token1 != token2

    def test_wrong_key_raises_on_decrypt(self):
        from cryptography.fernet import InvalidToken
        token = encrypt_credential(PLAINTEXT_API_KEY, TEST_SECRET_KEY)
        with pytest.raises(InvalidToken):
            decrypt_credential(token, "wrong-secret-key-xyz-abc-123456")


# ---------------------------------------------------------------------------
# 2. Credential masking — plaintext never exposed via public interface
# ---------------------------------------------------------------------------

class TestCredentialMasking:
    def test_anthropic_does_not_store_plaintext(self, anthropic_provider: AnthropicProvider):
        # The stored attribute must be the encrypted blob, not plaintext
        assert anthropic_provider._api_key_enc != PLAINTEXT_API_KEY
        assert PLAINTEXT_API_KEY not in vars(anthropic_provider).values()

    def test_openai_does_not_store_plaintext(self, openai_provider: OpenAIProvider):
        assert openai_provider._api_key_enc != PLAINTEXT_API_KEY
        assert PLAINTEXT_API_KEY not in vars(openai_provider).values()

    def test_bedrock_does_not_store_plaintext(self, bedrock_provider: BedrockProvider):
        stored_values = vars(bedrock_provider).values()
        assert PLAINTEXT_AWS_KEY not in stored_values
        assert PLAINTEXT_AWS_SECRET not in stored_values

    def test_ollama_has_no_credentials(self, ollama_provider: OllamaProvider):
        # Ollama uses no credentials — verify no sensitive fields exist
        assert not hasattr(ollama_provider, "_api_key_enc")
        assert not hasattr(ollama_provider, "_secret_key")


# ---------------------------------------------------------------------------
# 3. health_check delegation — Anthropic
# ---------------------------------------------------------------------------

class TestAnthropicHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_true_on_success(self, anthropic_provider: AnthropicProvider):
        mock_client = AsyncMock()
        mock_client.models.list = AsyncMock(return_value=[])
        with patch.object(anthropic_provider, "_client", return_value=mock_client):
            result = await anthropic_provider.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_exception(self, anthropic_provider: AnthropicProvider):
        mock_client = AsyncMock()
        mock_client.models.list = AsyncMock(side_effect=Exception("connection refused"))
        with patch.object(anthropic_provider, "_client", return_value=mock_client):
            result = await anthropic_provider.health_check()
        assert result is False


# ---------------------------------------------------------------------------
# 4. health_check delegation — OpenAI
# ---------------------------------------------------------------------------

class TestOpenAIHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_true_on_success(self, openai_provider: OpenAIProvider):
        mock_client = AsyncMock()
        mock_client.models.list = AsyncMock(return_value=[])
        with patch.object(openai_provider, "_client", return_value=mock_client):
            result = await openai_provider.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_exception(self, openai_provider: OpenAIProvider):
        mock_client = AsyncMock()
        mock_client.models.list = AsyncMock(side_effect=Exception("unauthorized"))
        with patch.object(openai_provider, "_client", return_value=mock_client):
            result = await openai_provider.health_check()
        assert result is False


# ---------------------------------------------------------------------------
# 5. health_check delegation — Bedrock
# ---------------------------------------------------------------------------

class TestBedrockHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_true_on_success(self, bedrock_provider: BedrockProvider):
        mock_client = MagicMock()
        mock_client.list_foundation_models.return_value = {"modelSummaries": []}
        with patch.object(bedrock_provider, "_bedrock_client", return_value=mock_client):
            result = await bedrock_provider.health_check()
        assert result is True
        mock_client.list_foundation_models.assert_called_once()

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_exception(self, bedrock_provider: BedrockProvider):
        mock_client = MagicMock()
        mock_client.list_foundation_models.side_effect = Exception("no credentials")
        with patch.object(bedrock_provider, "_bedrock_client", return_value=mock_client):
            result = await bedrock_provider.health_check()
        assert result is False


# ---------------------------------------------------------------------------
# 6. health_check delegation — Ollama
# ---------------------------------------------------------------------------

class TestOllamaHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_true_on_success(self, ollama_provider: OllamaProvider):
        mock_client = AsyncMock()
        mock_client.list = AsyncMock(return_value={"models": []})
        with patch.object(ollama_provider, "_client", return_value=mock_client):
            result = await ollama_provider.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_exception(self, ollama_provider: OllamaProvider):
        mock_client = AsyncMock()
        mock_client.list = AsyncMock(side_effect=Exception("connection refused"))
        with patch.object(ollama_provider, "_client", return_value=mock_client):
            result = await ollama_provider.health_check()
        assert result is False


# ---------------------------------------------------------------------------
# 7. SDK call construction — Anthropic complete()
# ---------------------------------------------------------------------------

class TestAnthropicSDKCalls:
    @pytest.mark.asyncio
    async def test_complete_calls_messages_create_with_correct_args(
        self, anthropic_provider: AnthropicProvider
    ):
        mock_message = MagicMock()
        mock_message.content = [MagicMock(text="Hello from Claude")]
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_message)

        with patch.object(anthropic_provider, "_client", return_value=mock_client):
            result = await anthropic_provider.complete("Say hello", max_tokens=100)

        mock_client.messages.create.assert_called_once_with(
            model="claude-3-haiku-20240307",
            max_tokens=100,
            messages=[{"role": "user", "content": "Say hello"}],
        )
        assert result == "Hello from Claude"

    @pytest.mark.asyncio
    async def test_embed_raises_not_implemented(self, anthropic_provider: AnthropicProvider):
        with pytest.raises(NotImplementedError):
            await anthropic_provider.embed("some text")


# ---------------------------------------------------------------------------
# 8. SDK call construction — OpenAI complete() and embed()
# ---------------------------------------------------------------------------

class TestOpenAISDKCalls:
    @pytest.mark.asyncio
    async def test_complete_calls_chat_completions_create(self, openai_provider: OpenAIProvider):
        mock_choice = MagicMock()
        mock_choice.message.content = "Hello from GPT"
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client = AsyncMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch.object(openai_provider, "_client", return_value=mock_client):
            result = await openai_provider.complete("Say hello", max_tokens=50)

        mock_client.chat.completions.create.assert_called_once_with(
            model="gpt-4o",
            max_tokens=50,
            messages=[{"role": "user", "content": "Say hello"}],
        )
        assert result == "Hello from GPT"

    @pytest.mark.asyncio
    async def test_embed_calls_embeddings_create(self, openai_provider: OpenAIProvider):
        mock_embedding = MagicMock()
        mock_embedding.embedding = [0.1, 0.2, 0.3]
        mock_response = MagicMock()
        mock_response.data = [mock_embedding]
        mock_client = AsyncMock()
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)

        with patch.object(openai_provider, "_client", return_value=mock_client):
            result = await openai_provider.embed("embed this")

        mock_client.embeddings.create.assert_called_once_with(
            model="text-embedding-3-small",
            input="embed this",
        )
        assert result == [0.1, 0.2, 0.3]


# ---------------------------------------------------------------------------
# 9. SDK call construction — Bedrock complete() and embed()
# ---------------------------------------------------------------------------

class TestBedrockSDKCalls:
    @pytest.mark.asyncio
    async def test_complete_calls_invoke_model_with_correct_body(
        self, bedrock_provider: BedrockProvider
    ):
        import json
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps(
            {"content": [{"text": "Hello from Bedrock"}]}
        ).encode()
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = {"body": mock_body}

        with patch.object(bedrock_provider, "_runtime_client", return_value=mock_client):
            result = await bedrock_provider.complete("Say hello", max_tokens=200)

        call_kwargs = mock_client.invoke_model.call_args[1]
        assert call_kwargs["modelId"] == "anthropic.claude-3-haiku-20240307-v1:0"
        body = json.loads(call_kwargs["body"])
        assert body["max_tokens"] == 200
        assert body["messages"] == [{"role": "user", "content": "Say hello"}]
        assert result == "Hello from Bedrock"

    @pytest.mark.asyncio
    async def test_embed_calls_invoke_model_with_titan(self, bedrock_provider: BedrockProvider):
        import json
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps({"embedding": [0.4, 0.5, 0.6]}).encode()
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = {"body": mock_body}

        with patch.object(bedrock_provider, "_runtime_client", return_value=mock_client):
            result = await bedrock_provider.embed("embed this")

        call_kwargs = mock_client.invoke_model.call_args[1]
        assert call_kwargs["modelId"] == "amazon.titan-embed-text-v1"
        body = json.loads(call_kwargs["body"])
        assert body["inputText"] == "embed this"
        assert result == [0.4, 0.5, 0.6]


# ---------------------------------------------------------------------------
# 10. SDK call construction — Ollama complete() and embed()
# ---------------------------------------------------------------------------

class TestOllamaSDKCalls:
    @pytest.mark.asyncio
    async def test_complete_calls_chat_with_correct_args(self, ollama_provider: OllamaProvider):
        mock_client = AsyncMock()
        mock_client.chat = AsyncMock(
            return_value={"message": {"content": "Hello from Ollama"}}
        )

        with patch.object(ollama_provider, "_client", return_value=mock_client):
            result = await ollama_provider.complete("Say hello", max_tokens=64)

        mock_client.chat.assert_called_once_with(
            model="llama3",
            messages=[{"role": "user", "content": "Say hello"}],
            options={"num_predict": 64},
        )
        assert result == "Hello from Ollama"

    @pytest.mark.asyncio
    async def test_embed_calls_embeddings_with_correct_args(self, ollama_provider: OllamaProvider):
        mock_client = AsyncMock()
        mock_client.embeddings = AsyncMock(return_value={"embedding": [0.7, 0.8, 0.9]})

        with patch.object(ollama_provider, "_client", return_value=mock_client):
            result = await ollama_provider.embed("embed this")

        mock_client.embeddings.assert_called_once_with(model="llama3", prompt="embed this")
        assert result == [0.7, 0.8, 0.9]
