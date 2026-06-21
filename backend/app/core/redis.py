"""Redis 客户端：最新值 / 状态 / Pub-Sub / 分布式锁的统一入口。"""
from __future__ import annotations

import redis.asyncio as aioredis
from redis.exceptions import WatchError

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


async def release_lock_if_owner(key: str, token: str) -> bool:
    """比对持有者 token 后原子删除锁（compare-and-delete），返回是否删除。

    审查 B1/C3：锁中途过期被他人重新持有时，无条件 delete 会误删他人的锁。此处用 WATCH
    事务实现原子比对删除，兼容 fakeredis（不依赖 Lua eval）。自身异常吞为 False。
    """
    try:
        async with redis_client.pipeline() as pipe:
            while True:
                try:
                    await pipe.watch(key)
                    if await pipe.get(key) != token:
                        await pipe.unwatch()
                        return False
                    pipe.multi()
                    pipe.delete(key)
                    await pipe.execute()
                    return True
                except WatchError:
                    continue
    except Exception:
        return False


async def check_redis() -> bool:
    """健康检查：PING。"""
    try:
        return bool(await redis_client.ping())
    except Exception:
        return False
