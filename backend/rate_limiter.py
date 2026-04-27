from __future__ import annotations

import math
import time
from dataclasses import dataclass, field


@dataclass
class TokenBucket:
    """Per-client token bucket for rate limiting."""

    tokens: float
    last_refill: float
    max_tokens: int
    refill_rate: float  # tokens per second


class RateLimiter:
    """Token-bucket rate limiter keyed by client IP.

    Each client gets *max_requests* tokens, refilled at
    *max_requests / window_seconds* tokens per second.
    """

    def __init__(self, max_requests: int = 60, window_seconds: int = 60) -> None:
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._refill_rate = max_requests / window_seconds
        self._buckets: dict[str, TokenBucket] = {}

    # -- public API ----------------------------------------------------------

    def check(self, client_key: str) -> tuple[bool, int]:
        """Check whether *client_key* is allowed to make a request.

        Returns ``(allowed, retry_after_seconds)``.
        *retry_after_seconds* is 0 when allowed, otherwise the ceiling of
        seconds until the next token becomes available.
        """
        now = time.monotonic()
        bucket = self._buckets.get(client_key)

        if bucket is None:
            bucket = TokenBucket(
                tokens=float(self._max_requests),
                last_refill=now,
                max_tokens=self._max_requests,
                refill_rate=self._refill_rate,
            )
            self._buckets[client_key] = bucket

        # Refill tokens based on elapsed time
        elapsed = now - bucket.last_refill
        if elapsed > 0:
            bucket.tokens = min(
                bucket.max_tokens,
                bucket.tokens + elapsed * self._refill_rate,
            )
            bucket.last_refill = now

        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return (True, 0)

        # Not enough tokens — compute wait time until 1 token is available
        deficit = 1.0 - bucket.tokens
        wait_seconds = deficit / self._refill_rate
        return (False, math.ceil(wait_seconds))

    def update_config(self, max_requests: int, window_seconds: int) -> None:
        """Reconfigure limits at runtime.

        Existing buckets will adapt on their next :meth:`check` call because
        we update the shared ``max_tokens`` and ``refill_rate`` values stored
        on each bucket lazily.
        """
        self._max_requests = max_requests
        self._window_seconds = window_seconds
        self._refill_rate = max_requests / window_seconds

        # Update existing buckets so the next check uses the new limits
        for bucket in self._buckets.values():
            bucket.max_tokens = max_requests
            bucket.refill_rate = self._refill_rate
            # Clamp current tokens to new max
            if bucket.tokens > max_requests:
                bucket.tokens = float(max_requests)
