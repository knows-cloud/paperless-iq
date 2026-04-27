"""Settings service for Paperless IQ.

Manages PaperlessIQConfig persistence, validation, import/export.

Validates: Requirements 5.2, 5.3, 13.1, 13.2, 13.3, 13.4, 13.5
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from backend.models import PaperlessIQConfig

logger = logging.getLogger(__name__)

# Fields that contain credentials and must be redacted on export
CREDENTIAL_FIELDS = frozenset({"llm_credentials"})

# Placeholder used in exported config files
REDACTED_PLACEHOLDER = "__REDACTED__"


class SettingsService:
    """In-memory settings store with validation.

    In production this would be backed by the database. For now it holds
    a single PaperlessIQConfig instance in memory.
    """

    def __init__(self, config: PaperlessIQConfig | None = None) -> None:
        self._config = config or PaperlessIQConfig(
            llm_provider="ollama",
            llm_model="llama3",
        )

    @property
    def config(self) -> PaperlessIQConfig:
        return self._config

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

    def export_config(self) -> dict[str, Any]:
        """Export config as JSON-serializable dict with credentials redacted.

        Validates: Requirements 13.1, 13.2
        """
        data = self._config.model_dump(mode="json")
        for field in CREDENTIAL_FIELDS:
            if field in data:
                data[field] = REDACTED_PLACEHOLDER
        return data

    def import_config(self, data: dict[str, Any]) -> dict[str, Any]:
        """Import config from a dict, skipping unknown/invalid fields.

        Returns a summary with 'applied' and 'skipped' field lists.

        Validates: Requirements 13.3, 13.4, 13.5
        """
        known_fields = set(PaperlessIQConfig.model_fields.keys())
        applied: list[str] = []
        skipped: list[dict[str, str]] = []

        valid_values: dict[str, Any] = {}

        for key, value in data.items():
            # Skip credential fields (must be re-entered manually)
            if key in CREDENTIAL_FIELDS:
                if value == REDACTED_PLACEHOLDER:
                    skipped.append({"field": key, "reason": "Credential field — re-enter manually"})
                    continue
                # Allow actual credential values to be imported
                valid_values[key] = value
                applied.append(key)
                continue

            if key not in known_fields:
                skipped.append({"field": key, "reason": "Unrecognized field"})
                continue

            # Try to validate this single field
            try:
                test_data = self._config.model_dump()
                test_data[key] = value
                PaperlessIQConfig(**test_data)
                valid_values[key] = value
                applied.append(key)
            except (ValidationError, ValueError) as exc:
                skipped.append({"field": key, "reason": str(exc)})

        # Apply all valid fields at once
        if valid_values:
            current = self._config.model_dump()
            current.update(valid_values)
            try:
                self._config = PaperlessIQConfig(**current)
            except ValidationError:
                # Shouldn't happen since we validated individually, but be safe
                pass

        return {"applied": applied, "skipped": skipped}
