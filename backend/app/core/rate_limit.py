"""Small bounded process-local abuse guard.

Redis remains the preferred deployment coordination layer; this fallback is bounded
and TTL-based so local/demo mode does not silently become unbounded state.
"""
from __future__ import annotations

import hashlib
import os
import threading
import time
from fastapi import HTTPException

_lock = threading.Lock()
_buckets: dict[str, list[float]] = {}
_MAX_BUCKETS = 10000


def enforce(scope: str, subject: str, limit: int | None = None, window_seconds: int | None = None) -> None:
    limit = limit or int(os.getenv("RATE_LIMIT_" + scope.upper().replace("-", "_") + "_LIMIT", "10"))
    window_seconds = window_seconds or int(os.getenv("RATE_LIMIT_" + scope.upper().replace("-", "_") + "_WINDOW_SECONDS", "60"))
    digest = hashlib.sha256(f"{scope}:{subject}".encode()).hexdigest()
    now = time.monotonic()
    with _lock:
        if len(_buckets) > _MAX_BUCKETS:
            cutoff = now - window_seconds
            for key in list(_buckets):
                if not _buckets[key] or _buckets[key][-1] <= cutoff:
                    _buckets.pop(key, None)
        bucket = [stamp for stamp in _buckets.get(digest, []) if stamp > now - window_seconds]
        if len(bucket) >= limit:
            _buckets[digest] = bucket
            raise HTTPException(status_code=429, detail="Too many requests. Please retry later.")
        bucket.append(now)
        _buckets[digest] = bucket


def reset() -> None:
    with _lock:
        _buckets.clear()
