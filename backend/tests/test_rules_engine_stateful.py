"""规则引擎有状态行为测试（红线 #7 平台侧，审查 2.1）。

覆盖此前零行为级测试的核心：去抖、恢复保持、起/自动恢复、同点多档取最高。
用 fake_redis（去抖计时）+ mem_db（告警表）+ 旁路抑制。
"""
from __future__ import annotations

import pytest
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


def _spec(rule_id=1, continuous_time=0, recover_hold_time=0) -> rules.RuleSpec:
    return rules.RuleSpec(
        id=rule_id, point_id="p1", level=2, priority=0, operator=">", operand=30.0,
        operand_min=None, operand_max=None, cond_type="threshold",
        restore_operator="<", restore_operand=28.0,
        continuous_time=continuous_time, recover_hold_time=recover_hold_time,
        content_tpl=None, suggest=None,
    )


async def test_debounced_breach_needs_continuous_time(fake_redis):
    spec = _spec(continuous_time=10)
    assert await rules._debounced_breach(spec, ts=0) is False  # 首次越限仅计时
    assert await rules._debounced_breach(spec, ts=5) is False  # 未满 10s
    assert await rules._debounced_breach(spec, ts=10) is True  # 满足去抖确认


async def test_debounced_breach_zero_is_immediate(fake_redis):
    assert await rules._debounced_breach(_spec(continuous_time=0), ts=0) is True


async def test_hold_recovered_needs_hold_time(fake_redis):
    spec = _spec(recover_hold_time=10)
    assert await rules._hold_recovered(spec, ts=0) is False
    assert await rules._hold_recovered(spec, ts=10) is True


async def _add_rule(mem_db, **over) -> None:
    base = dict(
        point_id="p1", operator=">", operand=30.0, cond_type="threshold", level=2, priority=0,
        continuous_time=0, recover_hold_time=0, restore_operator="<", restore_operand=28.0,
        enabled=True,
    )
    base.update(over)
    async with mem_db() as db:
        db.add(AlarmRule(**base))
        await db.commit()
    rules.invalidate_rule_cache()


async def _active_platform(mem_db) -> list[Alarm]:
    async with mem_db() as db:
        rows = await db.execute(
            select(Alarm).where(Alarm.source == "platform", Alarm.status == "active")
        )
        return list(rows.scalars().all())


async def test_evaluate_raises_then_auto_recovers(fake_redis, mem_db, _no_suppress):
    await _add_rule(mem_db)
    await rules.evaluate("p1", 35.0, ts=100)
    assert len(await _active_platform(mem_db)) == 1  # 越限起告警

    await rules.evaluate("p1", 24.0, ts=110)
    assert len(await _active_platform(mem_db)) == 0  # 满足恢复条件 → 自动恢复


async def test_evaluate_debounce_delays_raise(fake_redis, mem_db, _no_suppress):
    await _add_rule(mem_db, continuous_time=30)
    await rules.evaluate("p1", 35.0, ts=0)
    assert len(await _active_platform(mem_db)) == 0  # 去抖中，未起

    await rules.evaluate("p1", 35.0, ts=30)
    assert len(await _active_platform(mem_db)) == 1  # 持续满足 → 起


async def test_evaluate_multi_tier_takes_highest(fake_redis, mem_db, _no_suppress):
    await _add_rule(mem_db, level=2, operand=30.0)
    await _add_rule(mem_db, level=1, operand=40.0)  # 更严重档
    await rules.evaluate("p1", 45.0, ts=100)  # 同时命中两档
    active = await _active_platform(mem_db)
    assert len(active) == 1
    assert active[0].level == 1  # 取最高（level 越小越严重）
