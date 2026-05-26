"""Property-based tests for settings import/export.

# Feature: paperless-iq, Property 30: Settings export credential redaction
# Feature: paperless-iq, Property 31: Settings export/import round-trip
# Feature: paperless-iq, Property 32: Import unknown field tolerance

Validates: Requirements 13.1, 13.2, 13.3, 13.4, 13.5
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backend.models import PaperlessIQConfig
from backend.settings_service import CREDENTIAL_FIELDS, REDACTED_PLACEHOLDER, SettingsService

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_provider_names = st.sampled_from(["bedrock", "anthropic", "ollama", "openai"])
_analysis_modes = st.sampled_from(["ocr", "full_document"])
_creation_policies = st.sampled_from(["existing_only", "allow_new"])

_valid_config = st.builds(
    PaperlessIQConfig,
    llm_provider=_provider_names,
    llm_model=st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
        min_size=3,
        max_size=20,
    ),
    llm_credentials=st.just(b"secret-api-key-12345"),
    default_analysis_mode=_analysis_modes,
    tag_creation_policy=_creation_policies,
    correspondent_creation_policy=_creation_policies,
    doctype_creation_policy=_creation_policies,
    auto_apply=st.booleans(),
    poll_interval_seconds=st.integers(min_value=1, max_value=300),
    batch_size=st.integers(min_value=1, max_value=100),
    audit_retention_days=st.integers(min_value=90, max_value=365),
    automation_enabled=st.booleans(),
)


# ---------------------------------------------------------------------------
# Property 30: Settings export credential redaction
# ---------------------------------------------------------------------------

@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(config=_valid_config)
def test_property_30_export_credential_redaction(
    config: PaperlessIQConfig,
) -> None:
    """
    # Feature: paperless-iq, Property 30: Settings export credential redaction

    Exported config must contain __REDACTED__ for all credential fields
    and no plaintext secrets.

    Validates: Requirements 13.2
    """
    svc = SettingsService(config)
    exported = svc.export_config()

    for field in CREDENTIAL_FIELDS:
        raw = getattr(config, field, None)
        is_set = bool(raw)  # empty string / empty bytes = not configured
        if is_set:
            assert exported.get(field) == REDACTED_PLACEHOLDER, (
                f"Non-empty credential field '{field}' not redacted in export"
            )
        else:
            # Unset credentials should export as empty, never as plaintext
            assert exported.get(field, "") in ("", REDACTED_PLACEHOLDER), (
                f"Unset credential field '{field}' exported unexpected value"
            )

    # Ensure no plaintext credential value appears anywhere in the export
    cred_value = config.llm_credentials
    if cred_value and isinstance(cred_value, bytes):
        cred_str = cred_value.decode("utf-8", errors="replace")
        if cred_str and cred_str != REDACTED_PLACEHOLDER:
            export_str = str(exported)
            assert cred_str not in export_str, (
                f"Plaintext credential found in export: {cred_str}"
            )


# ---------------------------------------------------------------------------
# Property 31: Settings export/import round-trip
# ---------------------------------------------------------------------------

@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(config=_valid_config)
def test_property_31_export_import_round_trip(
    config: PaperlessIQConfig,
) -> None:
    """
    # Feature: paperless-iq, Property 31: Settings export/import round-trip

    Export then import must restore all non-credential settings to original values.

    Validates: Requirements 13.1, 13.3
    """
    svc = SettingsService(config)
    exported = svc.export_config()

    # Create a fresh service and import
    svc2 = SettingsService()
    summary = svc2.import_config(exported)

    # All non-credential fields should be applied
    original = config.model_dump(mode="json")
    restored = svc2.config.model_dump(mode="json")

    for field in original:
        if field in CREDENTIAL_FIELDS:
            continue  # Credentials are redacted, skip
        assert restored[field] == original[field], (
            f"Field '{field}' not restored: expected {original[field]!r}, got {restored[field]!r}"
        )


# ---------------------------------------------------------------------------
# Property 32: Import unknown field tolerance
# ---------------------------------------------------------------------------

@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    config=_valid_config,
    unknown_fields=st.dictionaries(
        keys=st.text(
            alphabet=st.characters(whitelist_categories=("Lu", "Ll")),
            min_size=5,
            max_size=15,
        ).filter(lambda k: k not in PaperlessIQConfig.model_fields),
        values=st.text(min_size=1, max_size=20),
        min_size=1,
        max_size=5,
    ),
)
def test_property_32_import_unknown_field_tolerance(
    config: PaperlessIQConfig,
    unknown_fields: dict[str, str],
) -> None:
    """
    # Feature: paperless-iq, Property 32: Import unknown field tolerance

    Valid fields must be applied, unknown fields must be listed in skipped summary.

    Validates: Requirements 13.4, 13.5
    """
    svc = SettingsService()
    exported = config.model_dump(mode="json")

    # Mix in unknown fields
    import_data = {**exported, **unknown_fields}

    summary = svc.import_config(import_data)

    # All unknown fields must appear in skipped
    skipped_fields = {s["field"] for s in summary["skipped"]}
    for field in unknown_fields:
        assert field in skipped_fields, (
            f"Unknown field '{field}' not in skipped summary"
        )

    # Valid fields (excluding credentials) must be applied
    for field in exported:
        if field in CREDENTIAL_FIELDS:
            continue
        assert field in summary["applied"], (
            f"Valid field '{field}' not in applied list"
        )
