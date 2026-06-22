"""实时入库失败可观测测试（审查 S2/M1/M2）。

落库失败必须：记 M_INGEST_PERSIST 指标 + 冻结回补缺口起点（NX），使本批由 offline_value
回补补回，而非静默丢弃并 ack EMS。
"""
from __future__ import annotations

from app.core import metrics
from app.core.constants import (
    REALTIME_FALLBACK_GAP_S,
    REDIS_BACKFILL_GAP_START,
    REDIS_INGEST_LAST_TS,
)
from app.ingest import realtime

_PERIOD = 1_700_000_000


def _push_payload() -> dict:
    return {
        "period": _PERIOD,
        "devices": [
            {
                "resource_id": "d1",
                "status": 1,
                "points": [{"resource_id": "p1", "real_value": "25.0", "save_time": _PERIOD}],
            }
        ],
    }


async def test_persist_failure_records_metric_and_freezes_gap(fake_redis, mem_db, monkeypatch):
    async def _boom(*_a, **_k):
        raise RuntimeError("db write failed")

    monkeypatch.setattr(realtime, "_persist", _boom)

    await realtime.handle_data_push(_push_payload())

    failures = await metrics.get_failures()
    assert failures.get(metrics.M_INGEST_PERSIST, {}).get("count") == 1
    # 审查 S2：无更早有效时刻时，缺口起点取 period - 回退步长，保证 gap_start < period(=last_ts)，
    # 否则 backfill_watch 会因 gap_end<=gap_start 把缺口当空窗口删除、永不回补。
    gap_start = int(await fake_redis.get(REDIS_BACKFILL_GAP_START))
    last_ts = int(await fake_redis.get(REDIS_INGEST_LAST_TS))
    assert gap_start == _PERIOD - REALTIME_FALLBACK_GAP_S
    assert gap_start < last_ts  # 关键不变量：缺口非空，可被回补


async def test_persist_failure_gap_starts_at_prev_last_ts(fake_redis, mem_db, monkeypatch):
    """已有更早的成功推送时刻时，缺口起点取该「本批之前的最后有效时刻」而非回退步长。"""
    prev = _PERIOD - 30
    await fake_redis.set(REDIS_INGEST_LAST_TS, prev)

    async def _boom(*_a, **_k):
        raise RuntimeError("db write failed")

    monkeypatch.setattr(realtime, "_persist", _boom)
    await realtime.handle_data_push(_push_payload())

    gap_start = int(await fake_redis.get(REDIS_BACKFILL_GAP_START))
    assert gap_start == prev  # 取上一批成功时刻，缺口覆盖 [prev, period]
    assert gap_start < _PERIOD


async def test_persist_failure_keeps_existing_earlier_gap(fake_redis, mem_db, monkeypatch):
    """已存在更早缺口时，落库失败不得用 NX 覆盖它。"""
    await fake_redis.set(REDIS_BACKFILL_GAP_START, _PERIOD - 9999)

    async def _boom(*_a, **_k):
        raise RuntimeError("db write failed")

    monkeypatch.setattr(realtime, "_persist", _boom)
    await realtime.handle_data_push(_push_payload())

    assert await fake_redis.get(REDIS_BACKFILL_GAP_START) == str(_PERIOD - 9999)
