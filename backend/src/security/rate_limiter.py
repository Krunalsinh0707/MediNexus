import time
import threading
from typing import Dict, List
from fastapi import Request, HTTPException, status

class InMemoryRateLimiter:
    """
    Thread-safe in-memory sliding-window rate limiter for sensitive endpoints.
    Protects against brute force, credential stuffing, and request flooding.
    """
    def __init__(self):
        self._records: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, max_requests: int, window_seconds: int) -> tuple[bool, int]:
        """
        Check if request is allowed.
        Returns:
            (allowed: bool, retry_after: int)
        """
        now = time.time()
        cutoff = now - window_seconds

        with self._lock:
            timestamps = self._records.get(key, [])
            # Filter timestamps within current sliding window
            timestamps = [t for t in timestamps if t > cutoff]

            if len(timestamps) >= max_requests:
                earliest = timestamps[0]
                retry_after = max(1, int(earliest + window_seconds - now))
                self._records[key] = timestamps
                return False, retry_after

            timestamps.append(now)
            self._records[key] = timestamps
            return True, 0

    def cleanup(self, max_age: int = 3600):
        """Purge stale records older than max_age."""
        cutoff = time.time() - max_age
        with self._lock:
            stale_keys = [k for k, v in self._records.items() if not v or max(v) < cutoff]
            for k in stale_keys:
                del self._records[k]

limiter = InMemoryRateLimiter()

def get_client_ip(request: Request) -> str:
    """Extract real client IP considering reverse proxy headers."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "127.0.0.1"

def rate_limit(max_requests: int, window_seconds: int, scope: str = "global", prefix: str | None = None):
    """
    FastAPI dependency factory; ``prefix`` remains an alias for ``scope``.
    """
    if prefix is not None:
        scope = prefix
    def dependency(request: Request):
        client_ip = get_client_ip(request)
        key = f"{scope}:{client_ip}"
        allowed, retry_after = limiter.check(key, max_requests, window_seconds)

        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many requests for {scope}. Please try again in {retry_after} second(s).",
                headers={"Retry-After": str(retry_after)}
            )
        return True

    return dependency
