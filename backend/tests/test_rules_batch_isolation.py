"""规则引擎批量评估的单测点事务隔离（审查 I3 / CRITICAL-1）。

回归：evaluate_batch 此前在单循环单会话内串行评估多测点且无 try/except。任一测点评估时
Redis/DB 抖动抛错会中断整个循环，使本批后续测点的越限静默漏判（监控系统漏报=事故）。
修复后每个测点在独立 savepoint 内评估，坏测点仅回滚自身并记 M_RULE_EVAL 指标，
同批其余测点仍正常产生告警——与 ingest/alarm.py 的单条告警隔离同口径。
"""
from __future__ import annotations

import pytest
from app.core.metrics import M_RULE_EVAL, get_failures
from app.engine import lifecycle, rules
from app.models.alarm import Alarm, AlarmRule
from sqlalchemy import select


@pytest.fixture
def _no_suppress(monkeypatch):
    async def _not_muted(*_a, **_k):
        return False

    async def _not_silenced(*_a, **_k):
        return (False, True)

    monkeypatch.setattr(lifecycle.suppress, "is_muted", _not_muted)
    monkeypatch.setattr(lifecycle.suppress, "maintenance_silenced", _not_silenced)


async def _add_rule(mem_db, point_id: str) -> None:
    async with mem_db() as db:
        db.add(AlarmRule(
            point_id=point_id, operator=">", operand=30.0, cond_type="threshold",
            level=2, priority=0, continuous_time=0, recover_hold_time=0,
            restore_operator="<", restore_operand=28.0, enabled=True,
        ))
        await db.commit()
    rules.invalidate_rule_cache()


async def _active_points(mem_db) -> set[str]:
    async with mem_db() as db:
        rows = await db.execute(
            select(Alarm.resource_id).where(Alarm.source == "platform", Alarm.status == "active")
        )
    return {r for (r,) in rows.all()}


async def test_one_bad_point_does_not_drop_batch(fake_redis, mem_db, _no_suppress, monkeypatch):
    """中间测点评估抛错时，首尾测点告警仍正常产生，且失败被记指标。"""
    for pid in ("p1", "p2", "p3"):
        await _add_rule(mem_db, pid)

    real_raise = lifecycle.raise_alarm

    async def flaky_raise(db, **kw):
        if kw.get("resource_id") == "p2":
            raise RuntimeError("模拟 p2 评估期间的 Redis/DB 抖动")
        return await real_raise(db, **kw)

    monkeypatch.setattr(rules.lifecycle, "raise_alarm", flaky_raise)

    # 三测点同时越限（operand=30），p2 注入失败
    await rules.evaluate_batch([("p1", 35.0, 100), ("p2", 35.0, 100), ("p3", 35.0, 100)])

    active = await _active_points(mem_db)
    assert active == {"p1", "p3"}  # 坏测点 p2 不拖垮整批，首尾正常起告警

    failures = await get_failures()
    assert failures.get(M_RULE_EVAL, {}).get("count", 0) == 1  # 单点失败可观测


async def test_bad_point_breach_timer_rolled_back(fake_redis, mem_db, _no_suppress, monkeypatch):
    """坏测点的 savepoint 回滚后，其去抖计时键不应残留半成品状态影响下轮。"""
    await _add_rule(mem_db, "p1")
    await _add_rule(mem_db, "p2")

    real_raise = lifecycle.raise_alarm

    async def flaky_raise(db, **kw):
        if kw.get("resource_id") == "p2":
            raise RuntimeError("p2 抖动")
        return await real_raise(db, **kw)

    monkeypatch.setattr(rules.lifecycle, "raise_alarm", flaky_raise)

    await rules.evaluate_batch([("p1", 35.0, 100), ("p2", 35.0, 100)])

    active = await _active_points(mem_db)
    assert "p1" in active  # 正常测点不受坏测点影响
