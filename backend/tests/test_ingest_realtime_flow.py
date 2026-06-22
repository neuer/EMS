"""实时主链路端到端集成（审查 T1 + C3）。

覆盖此前零行为级测试的平台核心数据流：EMS 推数据 → 写 Redis 最新值 → 脏数据计数 →
喂规则引擎 evaluate_batch → 产生越限告警（mock README 的主验收路径）。
同时回归 C3：脏 save_time 不得使整批规则评估崩溃/被跳过。
用 fake_redis + mem_db + 旁路抑制；point_history/device_status 不在内存库，旁路落库。
"""
from __future__ import annotations

import pytest
from app.core.constants import REDIS_POINT_LATEST
from app.core.metrics import M_INGEST_PARSE_DROP, get_failures
from app.engine import lifecycle, rules
from app.ingest import realtime
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


async def test_realtime_flow_raises_alarm_counts_drops(
    fake_redis, mem_db, _no_suppress, monkeypatch
):
    # point_history/device_status 表不在内存库；旁路落库，专注实时→规则主链路
    async def _noop_persist(*_a, **_k):
        return None

    monkeypatch.setattr(realtime, "_persist", _noop_persist)
    await _add_rule(mem_db)  # p1 > 30 → level 2

    data = {
        "period": 1700000000,
        "devices": [
            {
                "resource_id": "dev1",
                "status": 1,
                "points": [
                    {"resource_id": "p1", "real_value": "35.0", "save_time": "1700000000"},
                    {"resource_id": "p2", "real_value": "abc", "save_time": "1700000000"},
                    {"resource_id": "p1b", "real_value": "99.0", "save_time": "xyz"},
                ],
            }
        ],
    }
    # C3：含脏 save_time 的批不得抛异常
    await realtime.handle_data_push(data)

    # 1) p1 越限 → 产生平台告警（经 evaluate_batch；脏 save_time 的 p1b 未拖垮该评估）
    async with mem_db() as db:
        active = (
            await db.execute(
                select(Alarm).where(Alarm.source == "platform", Alarm.status == "active")
            )
        ).scalars().all()
    assert len(active) == 1
    assert active[0].resource_id == "p1"

    # 2) 最新值写入 Redis
    latest = await fake_redis.hgetall(REDIS_POINT_LATEST.format(point_id="p1"))
    assert latest.get("value") == "35.0"
    assert latest.get("save_time") == "1700000000"

    # 3) 脏数据（p2 解析失败值 + p1b 脏时间戳）计入丢弃指标
    failures = await get_failures()
    assert failures.get(M_INGEST_PARSE_DROP, {}).get("count", 0) >= 1
