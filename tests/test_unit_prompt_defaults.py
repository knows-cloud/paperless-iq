"""Unit tests for pre-populated system prompt default and revert behavior.

Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5
"""

from __future__ import annotations

from backend.models import PaperlessIQConfig
from backend.settings_service import SettingsService


# The default prompt from PaperlessIQConfig
DEFAULT_PROMPT = PaperlessIQConfig.model_fields["global_prompt_template"].default


class TestDefaultPromptContent:
    """Verify the default global_prompt_template describes inputs and output format (Req 6.1, 6.2)."""

    def test_default_describes_ocr_text_input(self) -> None:
        assert "OCR text" in DEFAULT_PROMPT or "ocr" in DEFAULT_PROMPT.lower()

    def test_default_describes_full_content_input(self) -> None:
        assert "full content" in DEFAULT_PROMPT

    def test_default_describes_existing_tags(self) -> None:
        assert "tags" in DEFAULT_PROMPT.lower()

    def test_default_describes_existing_correspondents(self) -> None:
        assert "correspondents" in DEFAULT_PROMPT.lower()

    def test_default_describes_existing_document_types(self) -> None:
        assert "document types" in DEFAULT_PROMPT.lower()

    def test_default_describes_custom_fields(self) -> None:
        assert "custom_fields" in DEFAULT_PROMPT or "custom fields" in DEFAULT_PROMPT.lower()

    def test_default_describes_json_output(self) -> None:
        assert "JSON" in DEFAULT_PROMPT

    def test_default_describes_title_key(self) -> None:
        assert '"title"' in DEFAULT_PROMPT

    def test_default_describes_tags_key(self) -> None:
        assert '"tags"' in DEFAULT_PROMPT

    def test_default_describes_correspondent_key(self) -> None:
        assert '"correspondent"' in DEFAULT_PROMPT

    def test_default_describes_document_type_key(self) -> None:
        assert '"document_type"' in DEFAULT_PROMPT

    def test_default_describes_storage_path_key(self) -> None:
        assert '"storage_path"' in DEFAULT_PROMPT

    def test_default_describes_custom_fields_key(self) -> None:
        assert '"custom_fields"' in DEFAULT_PROMPT


class TestPromptRevertOnClear:
    """Verify SettingsService reverts to default when prompt is cleared (Req 6.5)."""

    def test_empty_string_reverts_to_default(self) -> None:
        svc = SettingsService()
        svc.update({"global_prompt_template": ""})
        assert svc.config.global_prompt_template == DEFAULT_PROMPT

    def test_whitespace_only_reverts_to_default(self) -> None:
        svc = SettingsService()
        svc.update({"global_prompt_template": "   \n\t  "})
        assert svc.config.global_prompt_template == DEFAULT_PROMPT

    def test_custom_prompt_is_preserved(self) -> None:
        svc = SettingsService()
        custom = "You are a custom classifier."
        svc.update({"global_prompt_template": custom})
        assert svc.config.global_prompt_template == custom

    def test_clear_after_custom_reverts_to_default(self) -> None:
        svc = SettingsService()
        svc.update({"global_prompt_template": "Custom prompt here"})
        assert svc.config.global_prompt_template == "Custom prompt here"
        svc.update({"global_prompt_template": ""})
        assert svc.config.global_prompt_template == DEFAULT_PROMPT

    def test_default_prompt_on_fresh_config(self) -> None:
        config = PaperlessIQConfig(llm_provider="ollama", llm_model="llama3")
        assert config.global_prompt_template == DEFAULT_PROMPT
