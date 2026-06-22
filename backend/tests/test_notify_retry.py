"""告警事件发布失败补偿测试（审查 M2，离线确定性）。

publish_pending 发布失败 → 事件入补偿队列；retry_pending_events 重投成功后队列清空，
避免「告警已 commit 但通知永久丢失」。
"""
from __future__ import annotations

import json

from app.core.constants import CHANNEL_ALARM_EVENTS, REDIS_NOTIFY_PENDING
from app.engine import lifecycle
from app.notify import dispatcher


class _StubSession:
    """最小桩 session：仅承载 db.info 供 publish_pending 读取累积事件。"""

    def __init__(self, events: list[dict]) -> None:
        self.info = {"_notify_events": events}


async def test_publish_failure_enqueues_then_retry_drains(fake_redis, monkeypatch) -> None:
    ev = {"kind": "raise", "alarm_id": 7, "level": 2, "merge_key": "m", "resource_id": "d1"}

    # 1) 发布失败 → 入补偿队列
    async def _boom(*_a, **_k):
        raise RuntimeError("redis publish down")

    monkeypatch.setattr(lifecycle.redis_client, "publish", _boom)
    await lifecycle.publish_pending(_StubSession([dict(ev)]))  # type: ignore[arg-type]
    assert await fake_redis.llen(REDIS_NOTIFY_PENDING) == 1

    # 2) 通道恢复 → retry_pending_events 重投成功，队列清空
    published: list[str] = []

    async def _ok(channel, data):
        assert channel == CHANNEL_ALARM_EVENTS
        published.append(data)

    monkeypatch.setattr(dispatcher.redis_client, "publish", _ok)
    sent = await dispatcher.retry_pending_events()
    assert sent == 1
    assert await fake_redis.llen(REDIS_NOTIFY_PENDING) == 0
    # 重投载荷不含内部计数字段
    assert "_attempts" not in json.loads(published[0])


async def test_retry_requeues_on_repeated_failure(fake_redis, monkeypatch) -> None:
    await fake_redis.rpush(
        REDIS_NOTIFY_PENDING, json.dumps({"kind": "raise", "alarm_id": 1, "_attempts": 0})
    )

    async def _boom(*_a, **_k):
        raise RuntimeError("still down")

    monkeypatch.setattr(dispatcher.redis_client, "publish", _boom)
    sent = await dispatcher.retry_pending_events()
    assert sent == 0
    # 仍失败 → 回队（尝试次数 +1），不丢
    assert await fake_redis.llen(REDIS_NOTIFY_PENDING) == 1
    requeued = json.loads(await fake_redis.lindex(REDIS_NOTIFY_PENDING, 0))
    assert requeued["_attempts"] == 1
