"""报表统计聚合单元测试（离线、确定性，无 DB/网络）。"""
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.reports.stats import AlarmRow, aggregate_alarms, bucket_label

TZ = ZoneInfo("Asia/Shanghai")


def _dt(y: int, mo: int, d: int, h: int = 0, mi: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


def test_bucket_label_day_week_month() -> None:
    local = datetime(2026, 6, 19, 10, 0, tzinfo=TZ)
    assert bucket_label(local, "day") == "2026-06-19"
    assert bucket_label(local, "month") == "2026-06"
    # 2026-06-19 为 ISO 第 25 周
    assert bucket_label(local, "week") == "2026-W25"


def test_bucket_label_uses_local_timezone() -> None:
    # UTC 2026-06-18 17:00 → 上海 2026-06-19 01:00，应归入 19 日桶
    local = _dt(2026, 6, 18, 17, 0).astimezone(TZ)
    assert bucket_label(local, "day") == "2026-06-19"


def test_aggregate_counts_and_distributions() -> None:
    rows = [
        AlarmRow(_dt(2026, 6, 19, 1), level=1, source="platform", resource_id="p1"),
        AlarmRow(_dt(2026, 6, 19, 2), level=1, source="ems", resource_id="p1", event_type=0),
        AlarmRow(_dt(2026, 6, 20, 3), level=3, source="platform", resource_id="p2"),
    ]
    res = aggregate_alarms(rows, "day", 0, 99, TZ)
    assert res.total == 3
    assert res.by_level == {1: 2, 3: 1}
    assert res.by_source == {"platform": 2, "ems": 1}
    assert res.by_event_type == {0: 1}
    # 两个日期桶，按标签升序
    assert [b.bucket for b in res.buckets] == ["2026-06-19", "2026-06-20"]
    assert res.buckets[0].total == 2
    # Top 资源：p1 出现 2 次居首
    assert res.top_resources[0] == ("p1", 2)


def test_aggregate_mtta_mttr() -> None:
    rows = [
        AlarmRow(
            _dt(2026, 6, 19, 0, 0), level=2, source="platform", resource_id="p1",
            accepted_at=_dt(2026, 6, 19, 0, 2),   # 受理 120s
            recovered_at=_dt(2026, 6, 19, 0, 10),  # 恢复 600s
        ),
        AlarmRow(
            _dt(2026, 6, 19, 0, 0), level=2, source="platform", resource_id="p2",
            accepted_at=_dt(2026, 6, 19, 0, 4),   # 受理 240s
        ),
    ]
    res = aggregate_alarms(rows, "day", 0, 99, TZ)
    # MTTA = (120+240)/2 = 180
    assert res.mtta_seconds == 180.0
    # MTTR 仅一条有恢复 = 600
    assert res.mttr_seconds == 600.0


def test_aggregate_empty() -> None:
    res = aggregate_alarms([], "day", 0, 99, TZ)
    assert res.total == 0
    assert res.buckets == []
    assert res.top_resources == []
    assert res.mtta_seconds is None
    assert res.mttr_seconds is None
