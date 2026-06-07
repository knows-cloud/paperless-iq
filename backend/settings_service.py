"""Settings service for Paperless IQ.

Persists PaperlessIQConfig to the database as JSON.  On first startup the
config is seeded from environment variables (prefixed ``PIQ_``).  After the
first UI save the DB values take precedence.

Validates: Requirements 5.2, 5.3, 13.1, 13.2, 13.3, 13.4, 13.5
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from pydantic import ValidationError

from backend.keystore import get_machine_key
from backend.models import PaperlessIQConfig
from backend.providers.encryption import (
    decrypt_credential,
    decrypt_credential_v2,
    encrypt_credential_v2,
)

# Prefixes for credential blobs stored in the database.
# enc1: legacy fixed-salt (read only)
# enc2: random per-credential salt (current)
_CRED_ENC_PREFIX_V1 = "enc1:"
_CRED_ENC_PREFIX_V2 = "enc2:"


def _encrypt_creds(plaintext: str) -> str:
    """Encrypt a credential string for DB storage using the machine key (enc2 scheme)."""
    secret_key = get_machine_key()
    return _CRED_ENC_PREFIX_V2 + encrypt_credential_v2(plaintext, secret_key)


def _decrypt_creds(stored: str) -> str:
    """Decrypt a credential blob loaded from the DB.

    Accepts enc2 (current), enc1 (legacy fixed-salt), and plaintext (very old).
    Returns an empty string on decryption failure (wrong key, corrupt data).
    """
    secret_key = get_machine_key()
    try:
        if stored.startswith(_CRED_ENC_PREFIX_V2):
            return decrypt_credential_v2(stored[len(_CRED_ENC_PREFIX_V2):], secret_key)
        if stored.startswith(_CRED_ENC_PREFIX_V1):
            return decrypt_credential(stored[len(_CRED_ENC_PREFIX_V1):], secret_key)
        return stored  # plaintext / very old legacy
    except Exception:
        logger.error("Failed to decrypt stored credentials — wrong machine key?", exc_info=True)
        return ""

logger = logging.getLogger(__name__)

# Fields that contain credentials and must be redacted on export / API response
CREDENTIAL_FIELDS = frozenset(
    {"llm_credentials", "webhook_secret", "qdrant_api_key"}
)

# Credential fields typed as bytes (EncryptedBlob) — env-var values for these
# must be encoded to bytes before being placed on the model. webhook_secret is
# a plain str field and is excluded.
_BYTES_CREDENTIAL_FIELDS = frozenset(
    {"llm_credentials", "qdrant_api_key"}
)

# Placeholder used in exported config files and masked API responses
REDACTED_PLACEHOLDER = "__REDACTED__"

# ---------------------------------------------------------------------------
# Environment variable → config field mapping
# ---------------------------------------------------------------------------
# Only "simple" scalar fields are mapped.  Prompt templates and complex dicts
# (field_descriptions, per_field_prompt_templates, per_doctype_prompt_templates)
# are intentionally excluded — they'd be unwieldy as env vars.
# ---------------------------------------------------------------------------

_ENV_MAP: dict[str, tuple[str, type]] = {
    # key: (env var name, target python type)
    "llm_provider":                ("PIQ_LLM_PROVIDER", str),
    "llm_model":                   ("PIQ_LLM_MODEL", str),
    "llm_credentials":             ("PIQ_LLM_CREDENTIALS", str),
    "ollama_url":                   ("PIQ_OLLAMA_URL", str),
    "openai_base_url":              ("PIQ_OPENAI_BASE_URL", str),
    "llm_timeout_seconds":          ("PIQ_LLM_TIMEOUT_SECONDS", int),
    "vector_store_backend":        ("PIQ_VECTOR_STORE_BACKEND", str),
    "bedrock_kb_id":               ("PIQ_BEDROCK_KB_ID", str),
    "context_window_chars":        ("PIQ_CONTEXT_WINDOW_CHARS", int),
    "smart_entity_selection":      ("PIQ_SMART_ENTITY_SELECTION", bool),
    "similar_docs_count":          ("PIQ_SIMILAR_DOCS_COUNT", int),
    "frequency_fallback_count":    ("PIQ_FREQUENCY_FALLBACK_COUNT", int),
    "embed_provider":              ("PIQ_EMBED_PROVIDER", str),
    "embedding_model":             ("PIQ_EMBEDDING_MODEL", str),
    "embed_concurrency":           ("PIQ_EMBED_CONCURRENCY", int),
    "tag_creation_policy":         ("PIQ_TAG_CREATION_POLICY", str),
    "correspondent_creation_policy": ("PIQ_CORRESPONDENT_CREATION_POLICY", str),
    "doctype_creation_policy":     ("PIQ_DOCTYPE_CREATION_POLICY", str),
    "inbox_tag_id":                ("PIQ_INBOX_TAG_ID", int),
    "auto_apply":                  ("PIQ_AUTO_APPLY", bool),
    "poll_interval_seconds":       ("PIQ_POLL_INTERVAL_SECONDS", int),
    "batch_size":                  ("PIQ_BATCH_SIZE", int),
    "schedule_cron":               ("PIQ_SCHEDULE_CRON", str),
    "automation_enabled":          ("PIQ_AUTOMATION_ENABLED", bool),
    "audit_retention_days":        ("PIQ_AUDIT_RETENTION_DAYS", int),
    "target_language":             ("PIQ_TARGET_LANGUAGE", str),
    "paperless_public_url":        ("PIQ_PAPERLESS_PUBLIC_URL", str),
    # Qdrant backend (api key is a credential — encoded to bytes below)
    "qdrant_mode":                 ("PIQ_QDRANT_MODE", str),
    "qdrant_url":                  ("PIQ_QDRANT_URL", str),
    "qdrant_api_key":              ("PIQ_QDRANT_API_KEY", str),
    "qdrant_collection":           ("PIQ_QDRANT_COLLECTION", str),
    "qdrant_memory_collection":    ("PIQ_QDRANT_MEMORY_COLLECTION", str),
    # Search tuning: common
    "search_overfetch_multiplier": ("PIQ_SEARCH_OVERFETCH_MULTIPLIER", int),
    "search_min_score":            ("PIQ_SEARCH_MIN_SCORE", float),
    "chunk_size":                  ("PIQ_CHUNK_SIZE", int),
    "chunk_overlap":               ("PIQ_CHUNK_OVERLAP", int),
    "chunk_strategy":              ("PIQ_CHUNK_STRATEGY", str),
    "rerank_enabled":              ("PIQ_RERANK_ENABLED", bool),
    "rerank_method":               ("PIQ_RERANK_METHOD", str),
    "rerank_top_k":                ("PIQ_RERANK_TOP_K", int),
    "rerank_model":                ("PIQ_RERANK_MODEL", str),
    # Search tuning: Chroma-specific
    "chroma_hnsw_search_ef":       ("PIQ_CHROMA_HNSW_SEARCH_EF", int),
    "chroma_hnsw_m":               ("PIQ_CHROMA_HNSW_M", int),
    "chroma_hnsw_construction_ef": ("PIQ_CHROMA_HNSW_CONSTRUCTION_EF", int),
    # Search tuning: Qdrant-specific
    "qdrant_hnsw_ef":              ("PIQ_QDRANT_HNSW_EF", int),
    "qdrant_hnsw_m":               ("PIQ_QDRANT_HNSW_M", int),
    "qdrant_quantization":         ("PIQ_QDRANT_QUANTIZATION", str),
    "qdrant_hybrid_search":        ("PIQ_QDRANT_HYBRID_SEARCH", bool),
}


def _coerce(value: str, target_type: type) -> Any:
    """Convert a raw env-var string to the target Python type."""
    if target_type is bool:
        return value.lower() in ("1", "true", "yes", "on")
    if target_type is int:
        return int(value)
    if target_type is float:
        return float(value)
    return value


def _build_env_overrides() -> dict[str, Any]:
    """Read PIQ_* environment variables and return a dict of config overrides."""
    overrides: dict[str, Any] = {}
    for field, (env_name, target_type) in _ENV_MAP.items():
        raw = os.environ.get(env_name)
        if raw is None or raw == "":
            continue
        try:
            overrides[field] = _coerce(raw, target_type)
        except (ValueError, TypeError):
            logger.warning("Ignoring invalid env var %s=%r", env_name, raw)
    # Special: bytes-typed credential blobs must be stored as bytes on the model
    for field in _BYTES_CREDENTIAL_FIELDS:
        if field in overrides and isinstance(overrides[field], str):
            overrides[field] = overrides[field].encode()
    return overrides


def _default_config() -> PaperlessIQConfig:
    """Build the default config, applying any PIQ_* env-var overrides."""
    base = {"llm_provider": "ollama", "llm_model": "llama3"}
    base.update(_build_env_overrides())
    return PaperlessIQConfig(**base)


class SettingsService:
    """Settings store backed by the database.

    On construction the service is in-memory only.  Call :meth:`load_from_db`
    (async) during application startup to hydrate from the DB.  If no row
    exists yet the config is seeded from env vars and persisted.
    """

    def __init__(self, config: PaperlessIQConfig | None = None) -> None:
        self._config = config or _default_config()

    @property
    def config(self) -> PaperlessIQConfig:
        return self._config

    # ------------------------------------------------------------------
    # Database persistence
    # ------------------------------------------------------------------

    async def load_from_db(self) -> None:
        """Load config from the settings table.  If empty, seed from env vars and persist."""
        from backend.database import AsyncSessionLocal
        from backend.orm_models import SettingsORM

        async with AsyncSessionLocal() as session:
            row = await session.get(SettingsORM, 1)
            if row is not None:
                try:
                    data = json.loads(row.config_json)
                    # Decrypt credential fields if stored encrypted
                    for field in CREDENTIAL_FIELDS:
                        if data.get(field):
                            data[field] = _decrypt_creds(data[field])
                    self._config = PaperlessIQConfig(**data)
                    logger.info("Settings loaded from database.")
                    return
                except Exception:
                    logger.warning("Failed to parse saved settings; re-seeding from env vars.", exc_info=True)

            # No saved settings — seed from env vars
            self._config = _default_config()
            await self._persist(session)
            logger.info("Settings seeded from environment variables and saved to database.")

    async def _persist(self, session: Any | None = None) -> None:
        """Write current config to the database (credentials encrypted at rest)."""
        from backend.database import AsyncSessionLocal
        from backend.orm_models import SettingsORM

        own_session = session is None
        if own_session:
            session = AsyncSessionLocal()

        try:
            data = self._config.model_dump(mode="json")
            # Encrypt credential fields before writing to disk
            for field in CREDENTIAL_FIELDS:
                raw = getattr(self._config, field)
                if raw:
                    plaintext = raw.decode("latin-1") if isinstance(raw, bytes) else str(raw)
                    data[field] = _encrypt_creds(plaintext)
                else:
                    data[field] = ""

            row = await session.get(SettingsORM, 1)
            if row is None:
                row = SettingsORM(id=1, config_json=json.dumps(data))
                session.add(row)
            else:
                row.config_json = json.dumps(data)
            await session.commit()
        finally:
            if own_session:
                await session.close()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_masked(self) -> dict[str, Any]:
        """Return config as dict with credentials masked.

        For Bedrock: also exposes non-sensitive credential sub-fields
        (region, access_key_id) so the UI can pre-populate them, and
        adds ``bedrock_has_secret`` / ``bedrock_has_session_token`` flags
        so the UI can show a "stored" indicator without revealing the values.
        """
        data = self._config.model_dump(mode="json")

        # Extract non-sensitive Bedrock sub-fields BEFORE redacting the blob
        if self._config.llm_provider == "bedrock":
            raw = self._config.llm_credentials
            creds_str = raw.decode("latin-1") if isinstance(raw, bytes) else str(raw)
            if creds_str and creds_str.strip().startswith("{"):
                try:
                    creds = json.loads(creds_str)
                    data["bedrock_region"] = creds.get("region", "")
                    data["bedrock_access_key_id"] = creds.get("access_key_id", "")
                    data["bedrock_has_secret"] = bool(creds.get("secret_access_key"))
                    data["bedrock_has_session_token"] = bool(creds.get("session_token"))
                except (json.JSONDecodeError, Exception):
                    pass

        # "<field>_stored" flag lets the UI show a "stored" badge + keep-existing
        # placeholder without exposing the value (mirrors bedrock_has_secret).
        data["qdrant_api_key_stored"] = bool(self._config.qdrant_api_key)

        for field in CREDENTIAL_FIELDS:
            if data.get(field):  # only redact when non-empty
                data[field] = REDACTED_PLACEHOLDER
        return data

    def update(self, values: dict[str, Any]) -> PaperlessIQConfig:
        """Validate and apply partial settings update.

        Raises ValueError with descriptive message on validation failure.

        Special handling for Bedrock credentials:
        - ``__KEEP__`` as the ``secret_access_key`` or ``session_token`` value
          means "leave the existing value unchanged".  This lets the UI send
          an updated region / access_key_id without requiring the user to
          re-enter the secret key.
        """
        current = self._config.model_dump()

        # Don't overwrite credentials with the redacted placeholder
        for field in CREDENTIAL_FIELDS:
            if field in values and values[field] == REDACTED_PLACEHOLDER:
                del values[field]

        # Bedrock partial-update: merge __KEEP__ sentinel with existing creds
        if "llm_credentials" in values:
            try:
                raw = values["llm_credentials"]
                creds_str = raw.decode("latin-1") if isinstance(raw, bytes) else str(raw)
                new_creds = json.loads(creds_str)
                needs_merge = (
                    new_creds.get("secret_access_key") == "__KEEP__"
                    or new_creds.get("session_token") == "__KEEP__"
                )
                if needs_merge:
                    existing_raw = current.get("llm_credentials", b"")
                    existing_str = (
                        existing_raw.decode("latin-1")
                        if isinstance(existing_raw, bytes)
                        else str(existing_raw)
                    )
                    try:
                        existing_creds = json.loads(existing_str)
                    except (json.JSONDecodeError, Exception):
                        existing_creds = {}
                    if new_creds.get("secret_access_key") == "__KEEP__":
                        new_creds["secret_access_key"] = existing_creds.get("secret_access_key", "")
                    if new_creds.get("session_token") == "__KEEP__":
                        st = existing_creds.get("session_token", "")
                        if st:
                            new_creds["session_token"] = st
                        else:
                            new_creds.pop("session_token", None)
                    values["llm_credentials"] = json.dumps(new_creds)
            except (json.JSONDecodeError, AttributeError):
                pass  # leave values["llm_credentials"] as-is

        current.update(values)

        try:
            new_config = PaperlessIQConfig(**current)
        except ValidationError as exc:
            errors = "; ".join(
                f"{'.'.join(str(l) for l in e['loc'])}: {e['msg']}"
                for e in exc.errors()
            )
            raise ValueError(f"Invalid settings: {errors}") from exc

        # Revert global_prompt_template to default if cleared (Req 6.5)
        if not new_config.global_prompt_template.strip():
            default_prompt = PaperlessIQConfig.model_fields["global_prompt_template"].default
            new_config = new_config.model_copy(update={"global_prompt_template": default_prompt})

        self._config = new_config
        return self._config

    async def update_and_persist(self, values: dict[str, Any]) -> PaperlessIQConfig:
        """Validate, apply, and persist settings to the database."""
        self.update(values)
        await self._persist()
        return self._config

    def export_config(self) -> dict[str, Any]:
        """Export config as JSON-serializable dict with credentials redacted."""
        data = self._config.model_dump(mode="json")
        for field in CREDENTIAL_FIELDS:
            if data.get(field):  # only redact when non-empty
                data[field] = REDACTED_PLACEHOLDER
        return data

    def import_config(self, data: dict[str, Any]) -> dict[str, Any]:
        """Import config from a dict, skipping unknown/invalid fields.

        Returns a summary with 'applied' and 'skipped' field lists.
        """
        known_fields = set(PaperlessIQConfig.model_fields.keys())
        applied: list[str] = []
        skipped: list[dict[str, str]] = []

        valid_values: dict[str, Any] = {}

        for key, value in data.items():
            if key in CREDENTIAL_FIELDS:
                if value == REDACTED_PLACEHOLDER:
                    skipped.append({"field": key, "reason": "Credential field — re-enter manually"})
                    continue
                valid_values[key] = value
                applied.append(key)
                continue

            if key not in known_fields:
                skipped.append({"field": key, "reason": "Unrecognized field"})
                continue

            try:
                test_data = self._config.model_dump()
                test_data[key] = value
                PaperlessIQConfig(**test_data)
                valid_values[key] = value
                applied.append(key)
            except ValidationError as exc:
                reasons = [e["msg"] for e in exc.errors()[:3]]
                skipped.append({"field": key, "reason": "; ".join(reasons)})
            except ValueError:
                skipped.append({"field": key, "reason": "Invalid value for this field"})

        if valid_values:
            current = self._config.model_dump()
            current.update(valid_values)
            try:
                self._config = PaperlessIQConfig(**current)
            except ValidationError:
                pass

        return {"applied": applied, "skipped": skipped}
