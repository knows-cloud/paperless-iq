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

from backend.models import PaperlessIQConfig

logger = logging.getLogger(__name__)

# Fields that contain credentials and must be redacted on export / API response
CREDENTIAL_FIELDS = frozenset({"llm_credentials"})

# Placeholder used in exported config files and masked API responses
REDACTED_PLACEHOLDER = "__REDACTED__"

# ---------------------------------------------------------------------------
# Environment variable → config field mapping
# ---------------------------------------------------------------------------
# Only "simple" scalar fields are mapped.  Prompt templates and complex dicts
# (field_descriptions, per_field_prompt_templates, per_doctype_prompt_templates,
# per_doctype_analysis_mode) are intentionally excluded — they'd be unwieldy
# as env vars.
# ---------------------------------------------------------------------------

_ENV_MAP: dict[str, tuple[str, type]] = {
    # key: (env var name, target python type)
    "llm_provider":                ("PIQ_LLM_PROVIDER", str),
    "llm_model":                   ("PIQ_LLM_MODEL", str),
    "llm_credentials":             ("PIQ_LLM_CREDENTIALS", str),
    "ollama_url":                   ("PIQ_OLLAMA_URL", str),
    "vector_store_backend":        ("PIQ_VECTOR_STORE_BACKEND", str),
    "bedrock_kb_id":               ("PIQ_BEDROCK_KB_ID", str),
    "default_analysis_mode":       ("PIQ_DEFAULT_ANALYSIS_MODE", str),
    "context_window_chars":        ("PIQ_CONTEXT_WINDOW_CHARS", int),
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
}


def _coerce(value: str, target_type: type) -> Any:
    """Convert a raw env-var string to the target Python type."""
    if target_type is bool:
        return value.lower() in ("1", "true", "yes", "on")
    if target_type is int:
        return int(value)
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
    # Special: llm_credentials must be stored as bytes on the model
    if "llm_credentials" in overrides and isinstance(overrides["llm_credentials"], str):
        overrides["llm_credentials"] = overrides["llm_credentials"].encode()
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
                    # Apply env-var overrides on top for fields that are set
                    # but only for fields NOT already saved in DB
                    # (DB values win; env vars are just initial seed)
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
        """Write current config to the database."""
        from backend.database import AsyncSessionLocal
        from backend.orm_models import SettingsORM

        own_session = session is None
        if own_session:
            session = AsyncSessionLocal()

        try:
            data = self._config.model_dump(mode="json")
            # Store credentials as base64 string for JSON compatibility
            if isinstance(self._config.llm_credentials, bytes):
                data["llm_credentials"] = self._config.llm_credentials.decode("latin-1")

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
        """Return config as dict with credentials masked."""
        data = self._config.model_dump(mode="json")
        for field in CREDENTIAL_FIELDS:
            if field in data:
                data[field] = REDACTED_PLACEHOLDER
        return data

    def update(self, values: dict[str, Any]) -> PaperlessIQConfig:
        """Validate and apply partial settings update.

        Raises ValueError with descriptive message on validation failure.
        """
        current = self._config.model_dump()

        # Don't overwrite credentials with the redacted placeholder
        for field in CREDENTIAL_FIELDS:
            if field in values and values[field] == REDACTED_PLACEHOLDER:
                del values[field]

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
            if field in data:
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
            except (ValidationError, ValueError) as exc:
                skipped.append({"field": key, "reason": str(exc)})

        if valid_values:
            current = self._config.model_dump()
            current.update(valid_values)
            try:
                self._config = PaperlessIQConfig(**current)
            except ValidationError:
                pass

        return {"applied": applied, "skipped": skipped}
