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


async def test_threshold_event_type_dropped(fake_redis, mem_db):
    """红线 #7：event_type=2（过高，阈值类）必须丢弃，不入库。"""
    processed = await alarm.handle_alarm_push({"alarms": [_raise("g-thresh", 2)]})
    assert processed == 0


async def test_device_event_type_accepted_and_deduped(fake_redis, mem_db, _no_suppress):
    """event_type=0（通信中断）纳入；相同 guid 再来一次被去重。"""
    first = await alarm.handle_alarm_push({"alarms": [_raise("g-comm", 0)]})
    assert first == 1
    dup = await alarm.handle_alarm_push({"alarms": [_raise("g-comm", 0)]})
    assert dup == 0  # guid 去重
