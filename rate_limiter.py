"""
rate_limiter.py
---------------
A zero-dependency, in-memory sliding-window rate limiter for FastAPI.
Uses only Python standard library (collections, time, threading).

Usage
-----
from rate_limiter import rate_limit_ip, rate_limit_user

# In an endpoint:
rate_limit_ip(request, max_requests=5, window_seconds=60)   # raises HTTP 429 if exceeded
rate_limit_user(username, max_requests=10, window_seconds=60)
"""

import time
import threading
from collections import deque, defaultdict
from fastapi import Request, HTTPException


# ---------------------------------------------------------------------------
# Internal store: key -> deque of timestamps (sliding window)
# ---------------------------------------------------------------------------
_store: dict[str, deque] = defaultdict(deque)
_lock = threading.Lock()


def _is_rate_limited(key: str, max_requests: int, window_seconds: int) -> bool:
    """
    Sliding-window check.  Returns True if the caller has exceeded the limit.
    Thread-safe via a global lock (suitable for single-process FastAPI/Uvicorn).
    """
    now = time.monotonic()
    cutoff = now - window_seconds

    with _lock:
        dq = _store[key]

        # Drop timestamps that are outside the current window
        while dq and dq[0] < cutoff:
            dq.popleft()

        if len(dq) >= max_requests:
            return True

        dq.append(now)
        return False


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def rate_limit_ip(
    request: Request,
    max_requests: int,
    window_seconds: int,
    endpoint: str = "",
) -> None:
    """
    Rate-limit by client IP address.

    Args:
        request:        The FastAPI Request object.
        max_requests:   Maximum number of requests allowed in the window.
        window_seconds: Length of the sliding window in seconds.
        endpoint:       Optional label to scope limits per-endpoint.

    Raises:
        HTTPException(429) when the limit is exceeded.
    """
    # X-Forwarded-For is set by reverse proxies; fall back to direct IP.
    forwarded = request.headers.get("X-Forwarded-For")
    ip = forwarded.split(",")[0].strip() if forwarded else request.client.host

    key = f"ip:{ip}:{endpoint}"

    if _is_rate_limited(key, max_requests, window_seconds):
        raise HTTPException(
            status_code=429,
            detail=(
                f"Too many requests. You are limited to {max_requests} requests "
                f"per {window_seconds} seconds. Please wait and try again."
            ),
        )


def rate_limit_user(
    username: str,
    max_requests: int,
    window_seconds: int,
    endpoint: str = "",
) -> None:
    """
    Rate-limit by authenticated username.

    Args:
        username:       The authenticated user's username.
        max_requests:   Maximum number of requests allowed in the window.
        window_seconds: Length of the sliding window in seconds.
        endpoint:       Optional label to scope limits per-endpoint.

    Raises:
        HTTPException(429) when the limit is exceeded.
    """
    key = f"user:{username}:{endpoint}"

    if _is_rate_limited(key, max_requests, window_seconds):
        raise HTTPException(
            status_code=429,
            detail=(
                f"Too many AI requests. You are limited to {max_requests} messages "
                f"per {window_seconds} seconds. Please wait before sending another message."
            ),
        )
