"""历史查询时间转换纯函数测试（审查 M6/M7，离线确定性）。

红线 #10：共济 Unix 秒 ↔ TIMESTAMPTZ(UTC)。query_history 的 _utc/_epoch 若边界/时区错位，
趋势图数据会系统性偏移，此前一个用例都没有。这里覆盖往返与跨天/跨年边界。

说明（已知缺口）：query_history 的真实 SQL 执行（选层落表、ANY(:ids) 谓词、边界包含性）依赖
Postgres/TimescaleDB，sqlite 桩无法等价验证；用户已确认本轮采用离线纯函数方案，真实 SQL
集成测试需 Postgres 夹具，超出离线确定性门禁，记为已知缺口。
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.history.query import _epoch, _utc


def test_utc_is_timezone_aware_and_utc() -> None:
    dt = _utc(1_700_000_000)
    assert dt.tzinfo is not None
    offset = dt.utcoffset()
    assert offset is not None and offset.total_seconds() == 0  # 始终 UTC，无本地时区偏移


@pytest.mark.parametrize(
    "ts",
    [
        0,  # epoch 原点
        1_700_000_000,  # 普通时刻
        1_704_067_199,  # 2023-12-31T23:59:59Z 跨年边界前一秒
        1_704_067_200,  # 2024-01-01T00:00:00Z 跨年边界
        1_735_689_600,  # 2025-01-01T00:00:00Z
    ],
)
def test_epoch_utc_roundtrip(ts: int) -> None:
    assert _epoch(_utc(ts)) == ts  # 往返无偏移


def test_utc_known_value() -> None:
    # 1700000000 == 2023-11-14T22:13:20Z（固定值，验证无时区漂移）
    assert _utc(1_700_000_000) == datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC)


def test_cross_day_boundary_preserved() -> None:
    midnight = datetime(2024, 6, 1, 0, 0, 0, tzinfo=UTC)
    assert _utc(_epoch(midnight)) == midnight  # 跨天边界不漂移
