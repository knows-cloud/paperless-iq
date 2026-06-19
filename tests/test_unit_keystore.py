"""Unit tests for backend/keystore.py — key generation, persistence, caching."""

from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import patch

import pytest


def _reset_cache() -> None:
    """Clear the module-level key cache so tests start fresh."""
    import backend.keystore as ks
    ks._CACHE = None


def test_get_machine_key_uses_secret_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_cache()
    monkeypatch.setenv("SECRET_KEY", "my-test-secret-value-abc123")
    from backend.keystore import get_machine_key
    key = get_machine_key()
    assert key == "my-test-secret-value-abc123"


def test_get_machine_key_ignores_placeholder(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """SECRET_KEY set to the known placeholder should be ignored."""
    _reset_cache()
    monkeypatch.setenv("SECRET_KEY", "change-me-in-production")
    # Point _KEY_FILE at a writable tmp location so it doesn't try /data
    key_file = tmp_path / ".secret_key"
    with patch("backend.keystore._KEY_FILE", key_file):
        from backend.keystore import get_machine_key
        key = get_machine_key()
    # Must not be the placeholder
    assert key != "change-me-in-production"
    assert len(key) > 0


def test_get_machine_key_stable_across_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two calls with the same env var return the same key (cache hit)."""
    _reset_cache()
    monkeypatch.setenv("SECRET_KEY", "stable-key-xyz")
    from backend.keystore import get_machine_key
    assert get_machine_key() == get_machine_key()


def test_get_machine_key_persists_to_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When no env var is set, a key is generated and written to the key file."""
    _reset_cache()
    monkeypatch.delenv("SECRET_KEY", raising=False)
    key_file = tmp_path / ".secret_key"

    with patch("backend.keystore._KEY_FILE", key_file):
        _reset_cache()
        from backend.keystore import get_machine_key
        key = get_machine_key()

    assert key_file.exists()
    assert key_file.read_text().strip() == key


def test_get_machine_key_loads_from_existing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If the key file already exists its contents are reused."""
    _reset_cache()
    monkeypatch.delenv("SECRET_KEY", raising=False)
    key_file = tmp_path / ".secret_key"
    key_file.write_text("pre-existing-key-content")

    with patch("backend.keystore._KEY_FILE", key_file):
        _reset_cache()
        from backend.keystore import get_machine_key
        key = get_machine_key()

    assert key == "pre-existing-key-content"
