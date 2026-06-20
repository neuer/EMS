"""实时入库失败可观测测试（审查 S2/M1/M2）。

落库失败必须：记 M_INGEST_PERSIST 指标 + 冻结回补缺口起点（NX），使本批由 offline_value
回补补回，而非静默丢弃并 ack EMS。
"""
from __future__ import annotations

from app.core import metrics
from app.core.constants import REDIS_BACKFILL_GAP_START
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
    # 缺口起点被冻结为该批 period，供 backfill_watch 回补
    assert await fake_redis.get(REDIS_BACKFILL_GAP_START) == str(_PERIOD)


async def test_persist_failure_keeps_existing_earlier_gap(fake_redis, mem_db, monkeypatch):
    """已存在更早缺口时，落库失败不得用 NX 覆盖它。"""
    await fake_redis.set(REDIS_BACKFILL_GAP_START, _PERIOD - 9999)

    async def _boom(*_a, **_k):
        raise RuntimeError("db write failed")

    monkeypatch.setattr(realtime, "_persist", _boom)
    await realtime.handle_data_push(_push_payload())

    assert await fake_redis.get(REDIS_BACKFILL_GAP_START) == str(_PERIOD - 9999)
