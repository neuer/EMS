"""EMS 告警接入测试（审查 I7 + 红线 #7 复核）。

- 未匹配到 open 告警的 recover/accept/confirm → 记指标，不静默丢弃。
- 红线 #7：阈值类 event_type 被丢弃；仅 {0,21,30} 纳入。
"""
from __future__ import annotations

import pytest
from app.core import metrics
from app.engine import lifecycle
from app.ingest import alarm


@pytest.fixture
def _no_suppress(monkeypatch):
    """旁路抑制检查（Mute/Maintenance 模型含 PG ARRAY，不在内存库建表）。"""
    async def _not_muted(*_a, **_k):
        return False

    async def _not_silenced(*_a, **_k):
        return (False, True)

    monkeypatch.setattr(lifecycle.suppress, "is_muted", _not_muted)
    monkeypatch.setattr(lifecycle.suppress, "maintenance_silenced", _not_silenced)


def _recover(guid: str) -> dict:
    return {
        "guid": guid,
        "msg_type": 1,
        "event_recover": {"recover_time": 1, "recover_des": "ok"},
    }


def _raise(guid: str, event_type: int) -> dict:
    return {
        "guid": guid,
        "msg_type": 0,
        "resource_id": "d1",
        "event_alarm": {"event_type": event_type, "event_level": "2", "content": "x"},
    }


async def test_unmatched_recover_records_metric(fake_redis, mem_db):
    processed = await alarm.handle_alarm_push({"alarms": [_recover("no-such-guid")]})
    assert processed == 0
    failures = await metrics.get_failures()
    assert failures.get(metrics.M_ALARM_UNMATCHED, {}).get("count") == 1


@pytest.mark.parametrize("event_type", [2, 3, 4])
async def test_threshold_event_types_dropped(fake_redis, mem_db, event_type):
    """红线 #7：阈值类（2 过高/3 不正常/4 过低）一律丢弃，由平台规则引擎负责。"""
    processed = await alarm.handle_alarm_push(
        {"alarms": [_raise(f"g-thr-{event_type}", event_type)]}
    )
    assert processed == 0


@pytest.mark.parametrize("event_type", [0, 21, 30])
async def test_device_event_types_accepted(fake_redis, mem_db, _no_suppress, event_type):
    """红线 #7：通信中断(0)/故障(21)/停止采集(30) 三类均须纳入入库——
    此前仅测了 0，21/30 被误改为不纳入也不会被发现。"""
    processed = await alarm.handle_alarm_push(
        {"alarms": [_raise(f"g-{event_type}", event_type)]}
    )
    assert processed == 1


async def test_event_type_dedup(fake_redis, mem_db, _no_suppress):
    """同 guid 再来一次被去重。"""
    first = await alarm.handle_alarm_push({"alarms": [_raise("g-comm", 0)]})
    assert first == 1
    dup = await alarm.handle_alarm_push({"alarms": [_raise("g-comm", 0)]})
    assert dup == 0  # guid 去重


async def test_accepted_and_threshold_mixed_batch(fake_redis, mem_db, _no_suppress):
    """混批：故障(21) 与阈值类(4) 同时到达，只纳入 21。"""
    processed = await alarm.handle_alarm_push(
        {"alarms": [_raise("g-fault", 21), _raise("g-low", 4)]}
    )
    assert processed == 1
