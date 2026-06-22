"""通知发送幂等去重（审查 I1）。

回归：至少一次投递（pending 重投/worker 重复消费）此前无幂等保护会重复外呼/发短信。
"""
from __future__ import annotations

from app.notify import dispatcher
from app.notify.channels.base import NotifyMessage


def _msg(trigger: str = "raise") -> NotifyMessage:
    return NotifyMessage(
        subject="s", content="c", level=2, trigger=trigger, resource_id="r", alarm_id=1,
    )


async def test_dedup_reserve_blocks_duplicate(fake_redis):
    msg = _msg()
    assert await dispatcher._dedup_reserve(msg, 10, "alice") is True  # 首次预留成功
    assert await dispatcher._dedup_reserve(msg, 10, "alice") is False  # 重复跳过
    assert await dispatcher._dedup_reserve(msg, 10, "bob") is True  # 不同接收人独立
    assert await dispatcher._dedup_reserve(msg, 11, "alice") is True  # 不同渠道独立


async def test_digest_not_deduped(fake_redis):
    msg = _msg(trigger="digest")
    # 摘要按窗口聚合，不参与逐条去重
    assert await dispatcher._dedup_reserve(msg, 10, "alice") is True
    assert await dispatcher._dedup_reserve(msg, 10, "alice") is True
