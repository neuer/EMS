"""告警批处理事务隔离（审查 C1）。

回归：一条告警 flush 失败（约束冲突等）此前会污染共享会话，使同批其余高价值告警（0/21/30）
连锁失败、整批丢失。修复后每条告警在独立 savepoint 内处理，坏告警仅回滚自身。
"""
from __future__ import annotations

import pytest
from app.engine import lifecycle
from app.ingest import alarm as alarm_mod
from app.models.alarm import Alarm
from sqlalchemy import select


@pytest.fixture
def _no_suppress(monkeypatch):
    async def _not_muted(*_a, **_k):
        return False

    async def _not_silenced(*_a, **_k):
        return (False, True)

    monkeypatch.setattr(lifecycle.suppress, "is_muted", _not_muted)
    monkeypatch.setattr(lifecycle.suppress, "maintenance_silenced", _not_silenced)


async def test_one_bad_alarm_does_not_drop_batch(fake_redis, mem_db, _no_suppress, monkeypatch):
    real_raise = lifecycle.raise_alarm

    async def flaky_raise(db, **kw):
        # 对 guid="bad" 故意制造真实 flush 失败（source 违反 ck_alarms_source CHECK），
        # 触发会话污染场景；其余委托真实实现。
        if kw.get("guid") == "bad":
            db.add(Alarm(
                source="INVALID", resource_id="x", resource_kind=3,
                level=1, status="active", merge_key="k", merge_count=1,
            ))
            await db.flush()
        return await real_raise(db, **kw)

    monkeypatch.setattr(alarm_mod.lifecycle, "raise_alarm", flaky_raise)

    data = {
        "alarms": [
            {"msg_type": 0, "guid": "bad", "resource_id": "d1",
             "event_alarm": {"event_type": 21, "event_level": 2}},
            {"msg_type": 0, "guid": "good", "resource_id": "d2",
             "event_alarm": {"event_type": 21, "event_level": 2}},
        ]
    }
    processed = await alarm_mod.handle_alarm_push(data)

    async with mem_db() as db:
        good = (await db.execute(select(Alarm).where(Alarm.guid == "good"))).scalars().all()
        bad = (await db.execute(select(Alarm).where(Alarm.guid == "bad"))).scalars().all()
    assert len(good) == 1  # 坏告警不拖垮整批，good 仍入库
    assert len(bad) == 0  # 坏告警自身 savepoint 回滚，未入库
    assert processed == 1
