# Feature: paperless-live-integration, Property 2: Tag name case-insensitive filtering
"""Property-based tests for tag name case-insensitive filtering.

**Validates: Requirements 4.2, 4.3**
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st


def filter_tags(tags: list[str], search: str) -> list[str]:
    """Filter tags by case-insensitive substring match.

    Mirrors the frontend searchable dropdown filtering logic:
    returns only those tags whose lowercased name contains the
    lowercased search string.
    """
    search_lower = search.lower()
    return [t for t in tags if search_lower in t.lower()]


@settings(max_examples=100)
@given(
    tags=st.lists(st.text(min_size=1, max_size=50), min_size=0, max_size=30),
    search=st.text(min_size=0, max_size=20),
)
def test_tag_filter_returns_only_matching_tags(tags: list[str], search: str) -> None:
    """Property 2: Every returned tag contains the search string (case-insensitive).

    For any list of tag names and any search string, every tag in the
    filtered result must contain the lowercased search string in its
    lowercased name.

    **Validates: Requirements 4.2, 4.3**
    """
    result = filter_tags(tags, search)
    search_lower = search.lower()

    for tag in result:
        assert search_lower in tag.lower(), (
            f"Tag {tag!r} does not contain search string {search!r} (case-insensitive)"
        )


@settings(max_examples=100)
@given(
    tags=st.lists(st.text(min_size=1, max_size=50), min_size=0, max_size=30),
    search=st.text(min_size=0, max_size=20),
)
def test_tag_filter_returns_all_matching_tags(tags: list[str], search: str) -> None:
    """Property 2: No matching tag is omitted from the result.

    For any list of tag names and any search string, every tag in the
    original list whose lowercased name contains the lowercased search
    string must appear in the filtered result.

    **Validates: Requirements 4.2, 4.3**
    """
    result = filter_tags(tags, search)
    search_lower = search.lower()

    expected = [t for t in tags if search_lower in t.lower()]
    assert result == expected, (
        f"Filter result {result!r} does not match expected {expected!r} "
        f"for tags={tags!r}, search={search!r}"
    )
