"""Unit tests for the token-bucket RateLimiter."""

from __future__ import annotations

from unittest.mock import patch

from backend.rate_limiter import RateLimiter


class TestRateLimiterBasics:
    """Core behaviour of the token-bucket rate limiter."""

    def test_first_request_allowed(self) -> None:
        rl = RateLimiter(max_requests=5, window_seconds=10)
        allowed, retry = rl.check("client-a")
        assert allowed is True
        assert retry == 0

    def test_exhaust_bucket(self) -> None:
        rl = RateLimiter(max_requests=3, window_seconds=60)
        for _ in range(3):
            allowed, _ = rl.check("client-a")
            assert allowed is True
        allowed, retry = rl.check("client-a")
        assert allowed is False
        assert retry > 0

    def test_retry_after_is_positive_int(self) -> None:
        rl = RateLimiter(max_requests=1, window_seconds=60)
        rl.check("c")  # consume the single token
        allowed, retry = rl.check("c")
        assert allowed is False
        assert isinstance(retry, int)
        assert retry > 0

    def test_per_client_isolation(self) -> None:
        rl = RateLimiter(max_requests=1, window_seconds=60)
        rl.check("client-a")  # exhaust client-a
        allowed_a, _ = rl.check("client-a")
        allowed_b, _ = rl.check("client-b")
        assert allowed_a is False
        assert allowed_b is True

    def test_tokens_refill_over_time(self) -> None:
        rl = RateLimiter(max_requests=1, window_seconds=1)
        rl.check("c")  # consume
        # Simulate 2 seconds passing
        with patch("backend.rate_limiter.time") as mock_time:
            mock_time.monotonic.return_value = rl._buckets["c"].last_refill + 2.0
            allowed, retry = rl.check("c")
        assert allowed is True
        assert retry == 0


class TestRateLimiterUpdateConfig:
    """Runtime reconfiguration via update_config()."""

    def test_update_config_changes_limits(self) -> None:
        rl = RateLimiter(max_requests=2, window_seconds=60)
        rl.check("c")
        rl.check("c")
        # Bucket exhausted at old config
        allowed, _ = rl.check("c")
        assert allowed is False

        # Increase limit — existing bucket adapts
        rl.update_config(max_requests=10, window_seconds=60)
        assert rl._buckets["c"].max_tokens == 10

    def test_update_config_clamps_tokens(self) -> None:
        rl = RateLimiter(max_requests=10, window_seconds=60)
        # Bucket starts with 10 tokens; shrink to 2
        rl.update_config(max_requests=2, window_seconds=60)
        assert rl._buckets.get("c") is None  # no bucket yet
        rl.check("c")
        assert rl._buckets["c"].max_tokens == 2

    def test_update_config_clamps_existing_tokens(self) -> None:
        rl = RateLimiter(max_requests=10, window_seconds=60)
        rl.check("c")  # creates bucket with ~9 tokens
        rl.update_config(max_requests=2, window_seconds=60)
        assert rl._buckets["c"].tokens <= 2.0
