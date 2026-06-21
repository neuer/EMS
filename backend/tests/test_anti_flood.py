"""防轰炸合并行为测试（开发约定「防轰炸/去抖/恢复」，审查 E4）。

此前 lifecycle.raise_alarm 的合并/抖动复发路径无直接断言。验证：
- 同 merge_key 在途时合并计数不新建；
- recovered 且合并窗口内复发 → 复活原告警。
用 fake_redis（合并窗口标记）+ mem_db（告警表）+ 旁路抑制。
"""
from __future__ import annotations

import pytest
from app.engine import lifecycle
from app.models.alarm import Alarm
from sqlalchemy import func, select


@pytest.fixture
def _no_suppress(monkeypatch):
    async def _not_muted(*_a, **_k):
        return False

    async def _not_silenced(*_a, **_k):
        return (False, True)

    monkeypatch.setattr(lifecycle.suppress, "is_muted", _not_muted)
    monkeypatch.setattr(lifecycle.suppress, "maintenance_silenced", _not_silenced)


async def _raise(db, value: float):
    return await lifecycle.raise_alarm(
        db, source="platform", resource_id="p1", resource_kind=3, level=2,
        merge_id=1, value=value, content="温度过高",
    )


async def _count(mem_db) -> int:
    async with mem_db() as db:
        return (await db.execute(select(func.count()).select_from(Alarm))).scalar_one()


async def test_merge_while_open_increments_count_no_new_alarm(fake_redis, mem_db, _no_suppress):
    async with mem_db() as db:
        a1 = await _raise(db, 35.0)
        await db.commit()
        a2 = await _raise(db, 36.0)
        await db.commit()
        assert a1 is not None and a2 is not None
        first_id = a1.id
    assert a2.id == first_id  # 合并到同一告警
    assert a2.merge_count == 2  # 计数累加
    assert await _count(mem_db) == 1  # 未新建第二条


async def test_recovered_then_revive_within_window(fake_redis, mem_db, _no_suppress):
    async with mem_db() as db:
        a1 = await _raise(db, 35.0)
        await db.commit()
        assert a1 is not None
        await lifecycle.recover_alarm(db, a1, value=20.0)
        await db.commit()
        # 合并窗口标记仍在（raise 时 set，recover 不清）→ 抖动复发应复活原告警
        a2 = await _raise(db, 37.0)
        await db.commit()
        assert a2 is not None
        first_id = a1.id
    assert a2.id == first_id  # 复活同一告警，非新建
    assert a2.status == "active"  # 由 recovered 复活为 active
    assert a2.recovered_at is None  # 复活清除恢复时刻
    assert a2.merge_count == 2
    assert await _count(mem_db) == 1
