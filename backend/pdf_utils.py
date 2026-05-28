"""PDF rendering utilities using pypdfium2."""

from __future__ import annotations

import io

import pypdfium2 as pdfium

_JPEG_QUALITY = 85
_DEFAULT_DPI = 120


def get_page_count(pdf_bytes: bytes) -> int:
    """Return the number of pages without rendering anything."""
    doc = pdfium.PdfDocument(pdf_bytes)
    try:
        return len(doc)
    finally:
        doc.close()


def render_pages(
    pdf_bytes: bytes,
    max_pages: int | None = None,
    dpi: int = _DEFAULT_DPI,
) -> list[bytes]:
    """Render each page to JPEG bytes at the given DPI.

    Returns at most max_pages images (all pages when max_pages is None).
    """
    doc = pdfium.PdfDocument(pdf_bytes)
    try:
        n = len(doc)
        limit = n if max_pages is None else min(max_pages, n)
        scale = dpi / 72.0  # pdfium uses 72 DPI as its base unit
        images: list[bytes] = []
        for i in range(limit):
            page = doc[i]
            bitmap = page.render(scale=scale, rotation=0)
            pil_image = bitmap.to_pil()
            buf = io.BytesIO()
            pil_image.save(buf, format="JPEG", quality=_JPEG_QUALITY, optimize=True)
            images.append(buf.getvalue())
            page.close()
        return images
    finally:
        doc.close()
