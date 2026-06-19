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
        # health_check decrypts the key and checks it's non-empty — no network call
        result = await anthropic_provider.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_exception(self):
        # Provide an undecryptable token — health_check catches the exception and returns False
        bad_provider = AnthropicProvider(
            api_key_enc="not-a-valid-fernet-token",
            model="claude-3-haiku-20240307",
            secret_key=TEST_SECRET_KEY,
        )
        result = await bad_provider.health_check()
        assert result is False


# ---------------------------------------------------------------------------
# 4. health_check delegation — OpenAI
# ---------------------------------------------------------------------------

class TestOpenAIHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_true_on_success(self, openai_provider: OpenAIProvider):
        # health_check decrypts the key and checks it's non-empty — no network call
        result = await openai_provider.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_exception(self):
        bad_provider = OpenAIProvider(
            api_key_enc="not-a-valid-fernet-token",
            model="gpt-4o",
            secret_key=TEST_SECRET_KEY,
        )
        result = await bad_provider.health_check()
        assert result is False


# ---------------------------------------------------------------------------
# 5. health_check delegation — Bedrock
# ---------------------------------------------------------------------------

class TestBedrockHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_true_on_success(self, bedrock_provider: BedrockProvider):
        # health_check decrypts both keys, checks they're non-empty — no network call
        result = await bedrock_provider.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_exception(self):
        bad_provider = BedrockProvider(
            region="us-east-1",
            access_key_id_enc="not-a-valid-fernet-token",
            secret_access_key_enc="not-a-valid-fernet-token",
            secret_key=TEST_SECRET_KEY,
            model="anthropic.claude-3-haiku-20240307-v1:0",
        )
        result = await bad_provider.health_check()
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

    @pytest.mark.asyncio
    async def test_embed_uses_custom_embed_model(self, encrypted_api_key: str):
        provider = OpenAIProvider(
            api_key_enc=encrypted_api_key,
            model="gpt-4o",
            secret_key=TEST_SECRET_KEY,
            embed_model="text-embedding-ada-002",
        )
        mock_embedding = MagicMock()
        mock_embedding.embedding = [0.5, 0.6]
        mock_response = MagicMock()
        mock_response.data = [mock_embedding]
        mock_client = AsyncMock()
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)

        with patch.object(provider, "_client", return_value=mock_client):
            await provider.embed("embed this")

        mock_client.embeddings.create.assert_called_once_with(
            model="text-embedding-ada-002",
            input="embed this",
        )

    def test_base_url_forwarded_to_client(self, encrypted_api_key: str):
        provider = OpenAIProvider(
            api_key_enc=encrypted_api_key,
            model="gpt-4o",
            secret_key=TEST_SECRET_KEY,
            base_url="http://localhost:3000/v1",
        )
        with patch("backend.providers.openai_provider.openai.AsyncOpenAI") as mock_cls:
            mock_cls.return_value = MagicMock()
            provider._client()
        _, kwargs = mock_cls.call_args
        assert kwargs.get("base_url") == "http://localhost:3000/v1"


# ---------------------------------------------------------------------------
# 9. SDK call construction — Bedrock complete() and embed()
# ---------------------------------------------------------------------------

class TestBedrockSDKCalls:
    @pytest.mark.asyncio
    async def test_complete_calls_converse_with_correct_args(
        self, bedrock_provider: BedrockProvider
    ):
        # complete() → chat() uses the Bedrock Converse API, not invoke_model
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": "Hello from Bedrock"}]}},
            "usage": {},
        }

        with patch.object(bedrock_provider, "_runtime_client", return_value=mock_client):
            result = await bedrock_provider.complete("Say hello", max_tokens=200)

        call_kwargs = mock_client.converse.call_args[1]
        assert call_kwargs["modelId"] == "anthropic.claude-3-haiku-20240307-v1:0"
        assert call_kwargs["inferenceConfig"] == {"maxTokens": 200}
        assert call_kwargs["messages"] == [
            {"role": "user", "content": [{"text": "Say hello"}]}
        ]
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

    @pytest.mark.asyncio
    async def test_embed_cohere_inference_profile_uses_texts_body(
        self, encrypted_aws_key: str, encrypted_aws_secret: str
    ):
        # A region-prefixed inference-profile ID must still be recognised as Cohere,
        # so the request carries Cohere's {"texts": [...]} body rather than Titan's
        # {"inputText": ...} (which Bedrock rejects as "Malformed request").
        import json
        provider = BedrockProvider(
            region="eu-west-1",
            access_key_id_enc=encrypted_aws_key,
            secret_access_key_enc=encrypted_aws_secret,
            secret_key=TEST_SECRET_KEY,
            model="anthropic.claude-3-haiku-20240307-v1:0",
            embed_model="eu.cohere.embed-multilingual-v3:0",
        )
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps({"embeddings": [[0.1, 0.2]]}).encode()
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = {"body": mock_body}

        with patch.object(provider, "_runtime_client", return_value=mock_client):
            result = await provider.embed("embed this")

        body = json.loads(mock_client.invoke_model.call_args[1]["body"])
        assert body["texts"] == ["embed this"]
        assert "inputText" not in body
        # Default (document indexing) uses search_document.
        assert body["input_type"] == "search_document"
        assert result == [0.1, 0.2]

    @pytest.mark.asyncio
    async def test_embed_cohere_query_uses_search_query_input_type(
        self, encrypted_aws_key: str, encrypted_aws_secret: str
    ):
        # is_query=True must select Cohere's "search_query" input_type for
        # asymmetric retrieval quality.
        import json
        provider = BedrockProvider(
            region="eu-west-1",
            access_key_id_enc=encrypted_aws_key,
            secret_access_key_enc=encrypted_aws_secret,
            secret_key=TEST_SECRET_KEY,
            model="anthropic.claude-3-haiku-20240307-v1:0",
            embed_model="eu.cohere.embed-multilingual-v3:0",
        )
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps({"embeddings": [[0.1, 0.2]]}).encode()
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = {"body": mock_body}

        with patch.object(provider, "_runtime_client", return_value=mock_client):
            await provider.embed("find my invoice", is_query=True)

        body = json.loads(mock_client.invoke_model.call_args[1]["body"])
        assert body["input_type"] == "search_query"

    @pytest.mark.asyncio
    async def test_embed_cohere_embeddings_by_type_dict_response(
        self, encrypted_aws_key: str, encrypted_aws_secret: str
    ):
        # Some Cohere models return {"embeddings": {"float": [[...]]}} instead of
        # {"embeddings": [[...]]}; both must yield the float vector (not KeyError: 0).
        import json
        provider = BedrockProvider(
            region="eu-west-1",
            access_key_id_enc=encrypted_aws_key,
            secret_access_key_enc=encrypted_aws_secret,
            secret_key=TEST_SECRET_KEY,
            model="anthropic.claude-3-haiku-20240307-v1:0",
            embed_model="eu.cohere.embed-multilingual-v3:0",
        )
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps(
            {"embeddings": {"float": [[0.7, 0.8, 0.9]]}}
        ).encode()
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = {"body": mock_body}

        with patch.object(provider, "_runtime_client", return_value=mock_client):
            result = await provider.embed("embed this")

        assert result == [0.7, 0.8, 0.9]

    @pytest.mark.asyncio
    async def test_embed_titan_v2_inference_profile_sets_dimensions(
        self, encrypted_aws_key: str, encrypted_aws_secret: str
    ):
        # Prefixed Titan v2 profile ID must still hit the v2 branch (dimensions/normalize).
        import json
        provider = BedrockProvider(
            region="us-east-1",
            access_key_id_enc=encrypted_aws_key,
            secret_access_key_enc=encrypted_aws_secret,
            secret_key=TEST_SECRET_KEY,
            model="anthropic.claude-3-haiku-20240307-v1:0",
            embed_model="us.amazon.titan-embed-text-v2:0",
        )
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps({"embedding": [0.3, 0.4]}).encode()
        mock_client = MagicMock()
        mock_client.invoke_model.return_value = {"body": mock_body}

        with patch.object(provider, "_runtime_client", return_value=mock_client):
            result = await provider.embed("embed this")

        body = json.loads(mock_client.invoke_model.call_args[1]["body"])
        assert body["inputText"] == "embed this"
        assert body["dimensions"] == 1024
        assert result == [0.3, 0.4]


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
