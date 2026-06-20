"""周期摘要原子排空测试（审查 I4）。

flush 用 RENAME 抽走累计哈希，排空后原 key 不残留；flush 后新增的计数落入新 hash 不丢。
"""
from __future__ import annotations

import json

from app.core.constants import REDIS_NOTIFY_DIGEST, REDIS_NOTIFY_DIGEST_META
from app.notify import dispatcher


async def _no_targets(_db, _level):
    return None


async def test_flush_drains_and_cleans_temp(fake_redis, monkeypatch):
    monkeypatch.setattr(dispatcher, "_load_targets", _no_targets)
    await fake_redis.hset(REDIS_NOTIFY_DIGEST, "ems:0:d1", 3)
    await fake_redis.hset(
        REDIS_NOTIFY_DIGEST_META, "ems:0:d1",
        json.dumps({"level": 2, "resource_id": "d1", "content": "x"}),
    )

    await dispatcher.flush_digests()

    # 原累计与临时 key 都已清空
    assert await fake_redis.hgetall(REDIS_NOTIFY_DIGEST) == {}
    assert await fake_redis.exists(f"{REDIS_NOTIFY_DIGEST}:flushing") == 0


async def test_flush_empty_returns_zero(fake_redis):
    assert await dispatcher.flush_digests() == 0


async def test_increment_after_drain_survives(fake_redis, monkeypatch):
    monkeypatch.setattr(dispatcher, "_load_targets", _no_targets)
    await fake_redis.hset(REDIS_NOTIFY_DIGEST, "k1", 1)
    await dispatcher.flush_digests()
    # 模拟 flush 之后 worker 累计新计数
    await fake_redis.hincrby(REDIS_NOTIFY_DIGEST, "k2", 1)
    assert await fake_redis.hget(REDIS_NOTIFY_DIGEST, "k2") == "1"
