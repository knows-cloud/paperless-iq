"""Unit tests for pdf_utils.py — page count and rendering."""

from __future__ import annotations

import io

import pypdfium2 as pdfium
import pytest

from backend.pdf_utils import get_page_count, render_pages


def _make_pdf(num_pages: int = 1) -> bytes:
    """Create a minimal in-memory PDF with the given page count."""
    doc = pdfium.PdfDocument.new()
    for _ in range(num_pages):
        doc.new_page(width=72, height=72)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_get_page_count_single_page() -> None:
    assert get_page_count(_make_pdf(1)) == 1


def test_get_page_count_multi_page() -> None:
    assert get_page_count(_make_pdf(3)) == 3


def test_render_pages_returns_jpeg_bytes() -> None:
    pdf = _make_pdf(2)
    images = render_pages(pdf, max_pages=1)
    assert len(images) == 1
    # JPEG magic bytes: FF D8 FF
    assert images[0][:3] == b"\xff\xd8\xff"


def test_render_pages_respects_max_pages() -> None:
    pdf = _make_pdf(5)
    images = render_pages(pdf, max_pages=2)
    assert len(images) == 2


def test_render_pages_none_returns_all() -> None:
    pdf = _make_pdf(3)
    images = render_pages(pdf, max_pages=None)
    assert len(images) == 3


def test_render_pages_max_pages_exceeds_actual() -> None:
    pdf = _make_pdf(2)
    images = render_pages(pdf, max_pages=100)
    assert len(images) == 2
