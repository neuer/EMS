"""通知派发 masked 不发测试（审查 2.5 / 红线「维护窗口内不误扰」）。

masked 告警必须在加载路由之前就被短路，不触发任何渠道发送。
"""
from __future__ import annotations

from datetime import UTC, datetime

from app.models.alarm import Alarm
from app.notify import dispatcher


async def _insert_alarm(mem_db, masked: bool) -> int:
    async with mem_db() as db:
        alarm = Alarm(
            source="platform", resource_id="p1", resource_kind=3, level=2,
            status="active", masked=masked, merge_count=1, triggered_at=datetime.now(UTC),
        )
        db.add(alarm)
        await db.commit()
        await db.refresh(alarm)
        return alarm.id


async def test_masked_alarm_not_dispatched(mem_db, monkeypatch):
    called = {"load": False}

    async def _spy_load(_db, _level):
        called["load"] = True
        return None

    monkeypatch.setattr(dispatcher, "_load_targets", _spy_load)
    alarm_id = await _insert_alarm(mem_db, masked=True)

    await dispatcher.dispatch_alarm(alarm_id, "raise")

    assert called["load"] is False  # masked → 在加载路由前短路，未尝试发送


async def test_unmasked_alarm_loads_targets(mem_db, monkeypatch):
    called = {"load": False}

    async def _spy_load(_db, _level):
        called["load"] = True
        return None  # 无路由 → 不实际发送，但已进入加载

    monkeypatch.setattr(dispatcher, "_load_targets", _spy_load)
    alarm_id = await _insert_alarm(mem_db, masked=False)

    await dispatcher.dispatch_alarm(alarm_id, "raise")

    assert called["load"] is True
