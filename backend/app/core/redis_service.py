"""Explicit Redis boundary for cache, short-lived coordination, and queues."""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from urllib.parse import urlparse


class RedisUnavailable(RuntimeError):
    pass


class RedisConfigurationError(ValueError):
    pass


def validate_redis_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"redis", "rediss"} or not parsed.hostname:
        raise RedisConfigurationError("REDIS_URL must use redis:// or rediss:// with a hostname")
    return url


class MemoryRedis:
    """Explicit test-only backend; never selected implicitly in production."""
    def __init__(self):
        self.values = {}
        self.lists = {}
        self.expiry = {}

    def _expired(self, key):
        if key in self.expiry and self.expiry[key] <= time.time():
            self.values.pop(key, None); self.expiry.pop(key, None)
            return True
        return False

    def get(self, key):
        self._expired(key)
        return self.values.get(key)

    def set(self, key, value, ex=None, nx=False):
        if nx and self.get(key) is not None:
            return False
        self.values[key] = value
        if ex is not None: self.expiry[key] = time.time() + ex
        return True

    def delete(self, key):
        self.values.pop(key, None); self.expiry.pop(key, None)

    def rpush(self, key, value):
        self.lists.setdefault(key, []).append(value)

    def lpop(self, key):
        values = self.lists.get(key, [])
        return values.pop(0) if values else None

    def ping(self):
        return True

    def lock(self, name, timeout=30, blocking_timeout=2):
        service = self

        class _MemoryLock:
            def acquire(self):
                return service.set(f"lock:{name}", "1", ex=timeout, nx=True)

            def release(self):
                service.delete(f"lock:{name}")

        return _MemoryLock()


class RedisService:
    def __init__(self, url: str | None = None, enabled: bool | None = None, backend=None):
        self.enabled = enabled if enabled is not None else os.getenv("REDIS_ENABLED", "false").lower() in {"1", "true", "yes"}
        self.url = url or os.getenv("REDIS_URL")
        self._client = backend
        if self.enabled:
            if not self.url: raise RedisConfigurationError("REDIS_URL is required when REDIS_ENABLED=true")
            validate_redis_url(self.url)

    def connect(self):
        if not self.enabled: return None
        if self._client is None:
            try:
                import redis
                self._client = redis.Redis.from_url(self.url, decode_responses=True, socket_timeout=2, health_check_interval=30)
            except ImportError as error:
                raise RedisUnavailable("Redis support is not installed") from error
        try:
            self._client.ping()
        except Exception as error:
            raise RedisUnavailable("Redis is unavailable") from error
        return self._client

    def health_check(self) -> dict:
        if not self.enabled: return {"enabled": False, "status": "DISABLED"}
        self.connect()
        return {"enabled": True, "status": "AVAILABLE"}

    def get(self, key):
        client = self.connect()
        return client.get(key) if client else None

    def set(self, key, value, ttl_seconds: int):
        client = self.connect()
        if client: client.set(key, value, ex=ttl_seconds)

    def delete(self, key):
        client = self.connect()
        if client: client.delete(key)

    def get_json(self, key):
        value = self.get(key)
        return json.loads(value) if value else None

    def set_json(self, key, value, ttl_seconds: int):
        self.set(key, json.dumps(value, separators=(",", ":")), ttl_seconds)

    def enqueue(self, queue_name: str, payload: dict):
        client = self.connect()
        if client: client.rpush(queue_name, json.dumps(payload, separators=(",", ":")))

    def dequeue(self, queue_name: str):
        client = self.connect()
        raw = client.lpop(queue_name) if client else None
        return json.loads(raw) if raw else None

    @contextmanager
    def lock(self, name: str, ttl_seconds: int = 30):
        client = self.connect()
        if not client:
            yield None
            return
        lock = client.lock(name, timeout=ttl_seconds, blocking_timeout=2)
        acquired = lock.acquire()
        if not acquired: raise RedisUnavailable("Could not acquire Redis coordination lock")
        try: yield lock
        finally: lock.release()


def test_redis_service(backend=None) -> RedisService:
    return RedisService(enabled=True, url="redis://test.invalid/0", backend=backend or MemoryRedis())
