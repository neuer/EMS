"""失败可观测指标测试（红线 #10.1）。验证计数累计、最近时刻、读取聚合与自身容错。"""
from __future__ import annotations

from app.core import metrics


async def test_record_failure_counts_and_timestamp(fake_redis):
    await metrics.record_failure(metrics.M_INGEST_PERSIST, error="db down")
    await metrics.record_failure(metrics.M_INGEST_PERSIST)
    await metrics.record_failure(metrics.M_NOTIFY_SEND)

    failures = await metrics.get_failures()
    assert failures[metrics.M_INGEST_PERSIST]["count"] == 2
    assert failures[metrics.M_INGEST_PERSIST]["last_ts"] > 0
    assert failures[metrics.M_NOTIFY_SEND]["count"] == 1


async def test_get_failures_empty(fake_redis):
    assert await metrics.get_failures() == {}


async def test_record_failure_never_raises(monkeypatch):
    """上报自身失败不得抛出（绝不反向影响主流程）。"""
    class _Boom:
        def pipeline(self):
            raise RuntimeError("redis gone")

    monkeypatch.setattr(metrics, "redis_client", _Boom())
    # 不抛即通过
    await metrics.record_failure(metrics.M_RULE_EVAL, error="x")
