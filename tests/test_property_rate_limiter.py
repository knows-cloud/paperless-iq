# Feature: paperless-live-integration, Property 12: Rate limiter enforcement
# Feature: paperless-live-integration, Property 13: Rate limiter per-client isolation
"""Property-based tests for the token-bucket RateLimiter.

**Validates: Requirements 15.1, 15.3, 15.5**
"""

from __future__ import annotations

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from backend.rate_limiter import RateLimiter


@settings(max_examples=100)
@given(
    max_requests=st.integers(min_value=1, max_value=50),
    window_seconds=st.integers(min_value=1, max_value=120),
)
def test_rate_limiter_enforcement(max_requests: int, window_seconds: int) -> None:
    """Property 12: After max_requests calls the next call is denied with a positive retry-after.

    For any max_requests in [1, 50] and window_seconds in [1, 120], consuming
    exactly max_requests tokens must succeed, and the very next check must
    return (False, positive_int).

    **Validates: Requirements 15.1, 15.3**
    """
    rl = RateLimiter(max_requests=max_requests, window_seconds=window_seconds)
    client = "test-client"

    # All max_requests calls should be allowed
    for i in range(max_requests):
        allowed, retry = rl.check(client)
        assert allowed is True, f"Request {i + 1}/{max_requests} should be allowed"
        assert retry == 0

    # The next call must be denied
    allowed, retry = rl.check(client)
    assert allowed is False, "Request after exhausting limit should be denied"
    assert isinstance(retry, int)
    assert retry > 0, "retry_after must be a positive integer"


@settings(max_examples=100)
@given(
    max_requests=st.integers(min_value=1, max_value=50),
    window_seconds=st.integers(min_value=1, max_value=120),
    key_a=st.text(min_size=1, max_size=20),
    key_b=st.text(min_size=1, max_size=20),
)
def test_rate_limiter_per_client_isolation(
    max_requests: int,
    window_seconds: int,
    key_a: str,
    key_b: str,
) -> None:
    """Property 13: Two distinct clients are independently rate-limited.

    Exhausting client A's limit must not affect client B's ability to make
    requests.

    **Validates: Requirements 15.5**
    """
    assume(key_a != key_b)

    rl = RateLimiter(max_requests=max_requests, window_seconds=window_seconds)

    # Exhaust client A's limit
    for _ in range(max_requests):
        rl.check(key_a)

    # Client A should now be denied
    allowed_a, _ = rl.check(key_a)
    assert allowed_a is False, "Client A should be denied after exhausting limit"

    # Client B should still be allowed
    allowed_b, retry_b = rl.check(key_b)
    assert allowed_b is True, "Client B should be allowed when only A is exhausted"
    assert retry_b == 0
