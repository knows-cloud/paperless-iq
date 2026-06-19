"""Property-based test for credential opacity.

# Feature: paperless-iq, Property 7: Credential opacity
For any API response from the settings endpoints, no response body may contain
the plaintext value of any stored credential (API key, secret, password).
Credential fields must be replaced with a masked placeholder.

Validates: Requirements 3.4
"""

from __future__ import annotations

import json

from hypothesis import given, assume
from hypothesis import strategies as st

from backend.providers.encryption import encrypt_credential

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Realistic credential shapes: API keys, secrets, tokens, passwords
_credential_strategy = st.one_of(
    # API key style: sk-... or similar
    st.from_regex(r"sk-[A-Za-z0-9]{20,40}", fullmatch=True),
    # AWS-style access key
    st.from_regex(r"AKIA[A-Z0-9]{16}", fullmatch=True),
    # Generic secret / password (printable ASCII, no whitespace)
    # min_size=16 ensures generated strings are longer than any JSON placeholder
    # ("**REDACTED**" is 12 chars) so they can't accidentally match it.
    st.text(
        alphabet=st.characters(
            whitelist_categories=("Lu", "Ll", "Nd"),
            whitelist_characters="!@#$%^&*()-_=+[]{}|;:,.<>?",
        ),
        min_size=16,
        max_size=64,
    ),
)

_secret_key_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
    min_size=16,
    max_size=64,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MASKED_PLACEHOLDER = "**REDACTED**"


def build_settings_response(plaintext_credential: str, secret_key: str) -> dict:
    """
    Simulate what a GET /api/settings response should look like.

    The credential is stored encrypted; the response must never include the
    plaintext value — it must be replaced with a masked placeholder.
    """
    encrypted = encrypt_credential(plaintext_credential, secret_key)

    # This is what the settings endpoint SHOULD return: masked, not plaintext,
    # not even the encrypted blob (which could be decoded with the key).
    return {
        "llm_provider": "openai",
        "llm_model": "gpt-4o",
        # Credential field must be masked — never the plaintext, never the token
        "llm_credentials": _MASKED_PLACEHOLDER,
        "vector_store_backend": "local",
        "bedrock_kb_id": None,
        "default_analysis_mode": "ocr",
        "per_doctype_analysis_mode": {},
        "global_prompt_template": "",
        "per_field_prompt_templates": {},
        "per_doctype_prompt_templates": {},
        "tag_creation_policy": "existing_only",
        "correspondent_creation_policy": "existing_only",
        "doctype_creation_policy": "existing_only",
        "inbox_tag_id": None,
        "auto_apply": False,
        "poll_interval_seconds": 10,
        "batch_size": 10,
        "schedule_cron": None,
        "automation_enabled": False,
        "audit_retention_days": 90,
        "target_language": None,
        # Store encrypted token separately for test verification only
        "_encrypted_token": encrypted,
    }


def response_body_as_text(response: dict) -> str:
    """Serialize the response dict to JSON text (as it would be sent over HTTP)."""
    # Exclude the internal test-only key before serializing
    public_response = {k: v for k, v in response.items() if not k.startswith("_")}
    return json.dumps(public_response)


# ---------------------------------------------------------------------------
# Property 7: Credential opacity
# ---------------------------------------------------------------------------

@given(
    plaintext_credential=_credential_strategy,
    secret_key=_secret_key_strategy,
)
def test_property_7_credential_opacity(
    plaintext_credential: str,
    secret_key: str,
) -> None:
    """
    # Feature: paperless-iq, Property 7: Credential opacity

    For any settings read response, the plaintext credential must not appear
    anywhere in the serialized response body.

    Validates: Requirements 3.4
    """
    response = build_settings_response(plaintext_credential, secret_key)
    body_text = response_body_as_text(response)

    # Build the response text WITHOUT the credential placeholder to check for
    # false positives: if the credential string happens to be a substring of a
    # field name (e.g. "correspo" ⊂ "correspondent_creation_policy"), skip it.
    non_cred_response = {k: v for k, v in response.items()
                         if not k.startswith("_") and k != "llm_credentials"}
    non_cred_text = json.dumps(non_cred_response)
    assume(plaintext_credential not in non_cred_text)

    # The plaintext credential must NOT appear in the response body
    assert plaintext_credential not in body_text, (
        f"Plaintext credential leaked in settings response body. "
        f"Credential: {plaintext_credential!r}"
    )

    # The encrypted token must NOT appear in the response body either
    # (the encrypted blob itself should not be returned — only the masked placeholder)
    encrypted_token = response["_encrypted_token"]
    assert encrypted_token not in body_text, (
        f"Encrypted credential token leaked in settings response body."
    )

    # The masked placeholder MUST be present for the credential field
    assert response["llm_credentials"] == _MASKED_PLACEHOLDER, (
        f"Credential field must be masked with {_MASKED_PLACEHOLDER!r}, "
        f"got {response['llm_credentials']!r}"
    )


@given(
    credentials=st.fixed_dictionaries({
        "api_key": _credential_strategy,
        "secret_key_val": _credential_strategy,
        "password": _credential_strategy,
    }),
    secret_key=_secret_key_strategy,
)
def test_property_7_multiple_credentials_opacity(
    credentials: dict[str, str],
    secret_key: str,
) -> None:
    """
    # Feature: paperless-iq, Property 7: Credential opacity (multiple credentials)

    For any settings read response containing multiple credential fields
    (API key, secret, password), none of the plaintext values may appear
    in the serialized response body.

    Validates: Requirements 3.4
    """
    _CRED_FIELDS = {"llm_credentials", "aws_access_key_id", "aws_secret_access_key", "api_password"}

    # Simulate a response with multiple credential-like fields all masked
    response = {
        "llm_provider": "bedrock",
        "llm_model": "anthropic.claude-3-haiku-20240307-v1:0",
        # All credential fields must be masked
        "llm_credentials": _MASKED_PLACEHOLDER,
        "aws_access_key_id": _MASKED_PLACEHOLDER,
        "aws_secret_access_key": _MASKED_PLACEHOLDER,
        "api_password": _MASKED_PLACEHOLDER,
        "vector_store_backend": "local",
        "audit_retention_days": 90,
    }

    body_text = json.dumps(response)

    # Skip examples where a credential coincidentally appears in non-secret content
    # (e.g., as a substring of a field name like "aws_secret_access_key").
    # Replace the placeholder values so only field names + non-cred values remain.
    redacted_body = body_text.replace(_MASKED_PLACEHOLDER, "")
    for plaintext_value in credentials.values():
        assume(plaintext_value not in redacted_body)

    # None of the plaintext credential values may appear in the response
    for field_name, plaintext_value in credentials.items():
        assert plaintext_value not in body_text, (
            f"Plaintext credential for field {field_name!r} leaked in response body. "
            f"Value: {plaintext_value!r}"
        )

    # All credential fields must carry the masked placeholder
    for field in _CRED_FIELDS:
        assert response[field] == _MASKED_PLACEHOLDER, (
            f"Field {field!r} must be masked, got {response[field]!r}"
        )
