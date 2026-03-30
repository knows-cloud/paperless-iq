"""Property-based tests for document preview in approval queue.

# Feature: paperless-iq, Property 29: Document preview in queue

Validates: Requirements 11.1, 11.2, 11.3
"""

from __future__ import annotations

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from backend.preview import PLACEHOLDER_URL, resolve_preview_url

# ---------------------------------------------------------------------------
# Property 29: Document preview in queue
# ---------------------------------------------------------------------------

@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
@given(
    document_id=st.integers(min_value=1, max_value=100_000),
    preview_available=st.booleans(),
)
def test_property_29_document_preview_in_queue(
    document_id: int,
    preview_available: bool,
) -> None:
    """
    # Feature: paperless-iq, Property 29: Document preview in queue

    Each response must contain a valid preview URL or fallback placeholder
    with a direct document link.

    Validates: Requirements 11.1, 11.2, 11.3
    """
    result = resolve_preview_url(document_id, preview_available)

    # Must always have both keys
    assert "preview_url" in result
    assert "document_url" in result

    # Document URL must always point to the document
    assert f"/documents/{document_id}/details" in result["document_url"]

    if preview_available:
        # Preview URL must point to the Paperless NGX thumbnail endpoint
        assert f"/api/documents/{document_id}/thumb/" in result["preview_url"]
        assert result["preview_url"] != PLACEHOLDER_URL
    else:
        # Fallback: placeholder URL
        assert result["preview_url"] == PLACEHOLDER_URL
        # Must still have a direct document link
        assert result["document_url"], "Document URL must be present as fallback"
