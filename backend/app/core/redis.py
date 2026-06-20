"""Redis 客户端：最新值 / 状态 / Pub-Sub / 分布式锁的统一入口。"""
from __future__ import annotations

import redis.asyncio as aioredis

from app.core.config import settings

# decode_responses=True：键值以 str 读写，便于最新值缓存与状态读取
redis_client: aioredis.Redis = aioredis.from_url(
    settings.redis_url,
    encoding="utf-8",
    decode_responses=True,
)


async def get_redis() -> aioredis.Redis:
    """FastAPI 依赖：返回全局 Redis 客户端。"""
    return redis_client


async def check_redis() -> bool:
    """健康检查：PING。"""
    try:
        return bool(await redis_client.ping())
    except Exception:
        return False
