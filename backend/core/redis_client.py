"""Redis cache helpers. Every call fails soft: if Redis is down the app still works."""

import json
import logging
from typing import Any

import redis.asyncio as aioredis

from core.config import settings

logger = logging.getLogger(__name__)

_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(
            settings.redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2
        )
    return _client


async def cache_get(key: str) -> Any | None:
    try:
        raw = await get_redis().get(key)
        return json.loads(raw) if raw else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("cache_get failed for %s: %s", key, exc)
        return None


async def cache_set(key: str, value: Any, ttl: int) -> None:
    try:
        await get_redis().set(key, json.dumps(value, default=str), ex=ttl)
    except Exception as exc:  # noqa: BLE001
        logger.debug("cache_set failed for %s: %s", key, exc)


async def ping() -> bool:
    try:
        return bool(await get_redis().ping())
    except Exception:  # noqa: BLE001
        return False


async def close_redis() -> None:
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        except Exception:  # noqa: BLE001
            pass
        _client = None
