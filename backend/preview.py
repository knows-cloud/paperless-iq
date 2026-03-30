"""Document preview URL resolution for Paperless IQ.

Resolves Paperless NGX thumbnail/preview URLs for documents in the
approval queue. Falls back to a placeholder when preview is unavailable.

Validates: Requirements 11.1, 11.2, 11.3
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

PAPERLESS_URL = os.getenv("PAPERLESS_URL", "http://localhost:8000")

PLACEHOLDER_URL = "/static/placeholder-preview.png"


def resolve_preview_url(document_id: int, preview_available: bool = True) -> dict[str, str]:
    """Resolve the preview URL for a document.

    Returns a dict with:
      - preview_url: thumbnail/preview URL or placeholder
      - document_url: direct link to the document in Paperless NGX

    Validates: Requirements 11.1, 11.2, 11.3
    """
    base = PAPERLESS_URL.rstrip("/")
    document_url = f"{base}/documents/{document_id}/details"

    if preview_available:
        preview_url = f"{base}/api/documents/{document_id}/thumb/"
    else:
        preview_url = PLACEHOLDER_URL

    return {
        "preview_url": preview_url,
        "document_url": document_url,
    }
