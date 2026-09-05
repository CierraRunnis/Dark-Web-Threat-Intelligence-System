from __future__ import annotations

import os
import time
from typing import Protocol


class StateStore(Protocol):
    def claim_seed_slot(self, site_name: str, ttl_seconds: int) -> bool:
        ...

    def claim_detail(self, site_name: str, target_url: str, ttl_seconds: int) -> bool:
        ...


class InMemoryStateStore:
    def __init__(self) -> None:
        self._claims: dict[str, float] = {}

    def _claim(self, key: str, ttl_seconds: int) -> bool:
        now = time.monotonic()
        expires_at = self._claims.get(key, 0.0)
        if expires_at > now:
            return False
        self._claims[key] = now + max(ttl_seconds, 1)
        return True

    def claim_seed_slot(self, site_name: str, ttl_seconds: int) -> bool:
        return self._claim(f"seed:{site_name}", ttl_seconds)

    def claim_detail(self, site_name: str, target_url: str, ttl_seconds: int) -> bool:
        return self._claim(f"detail:{site_name}:{target_url}", ttl_seconds)


class RedisStateStore:
    def __init__(self, redis_url: str | None = None) -> None:
        self._redis_url = redis_url or os.environ.get("REDIS_URL", "redis://127.0.0.1:6379/0")
        try:
            import redis
        except ImportError as exc:
            raise RuntimeError("redis package is required for Redis-backed queue state") from exc
        self._client = redis.Redis.from_url(self._redis_url, decode_responses=True)

    def _claim(self, key: str, ttl_seconds: int) -> bool:
        return bool(self._client.set(key, "1", nx=True, ex=max(ttl_seconds, 1)))

    def claim_seed_slot(self, site_name: str, ttl_seconds: int) -> bool:
        return self._claim(f"darkweb:seed:{site_name}", ttl_seconds)

    def claim_detail(self, site_name: str, target_url: str, ttl_seconds: int) -> bool:
        return self._claim(f"darkweb:detail:{site_name}:{target_url}", ttl_seconds)


def get_state_store(prefer_redis: bool) -> StateStore:
    if prefer_redis:
        return RedisStateStore()
    return InMemoryStateStore()
