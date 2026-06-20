"""报表周期计算 / 正文渲染 / cron 解析单元测试（离线、确定性）。"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from app.reports.service import period_for, render_report_text
from app.reports.stats import StatsBucket, StatsResult
from apscheduler.triggers.cron import CronTrigger

TZ = ZoneInfo("Asia/Shanghai")
DAY = 86400


def test_period_daily_is_yesterday_local() -> None:
    now = datetime(2026, 6, 19, 9, 30, tzinfo=TZ)
    start, end = period_for("daily", now)
    start_local = datetime.fromtimestamp(start, tz=TZ)
    assert start_local == datetime(2026, 6, 18, 0, 0, tzinfo=TZ)
    # 闭区间末尾为下一日零点前 1 秒
    assert end == start + DAY - 1


def test_period_weekly_is_prev_iso_week() -> None:
    # 2026-06-19 周五；上一 ISO 周为 2026-06-08(周一) ~ 06-14(周日)
    now = datetime(2026, 6, 19, 9, 0, tzinfo=TZ)
    start, end = period_for("weekly", now)
    start_local = datetime.fromtimestamp(start, tz=TZ)
    assert start_local == datetime(2026, 6, 8, 0, 0, tzinfo=TZ)
    assert end == start + 7 * DAY - 1


def test_period_monthly_is_prev_month() -> None:
    now = datetime(2026, 6, 19, 9, 0, tzinfo=TZ)
    start, end = period_for("monthly", now)
    start_local = datetime.fromtimestamp(start, tz=TZ)
    end_local = datetime.fromtimestamp(end + 1, tz=TZ)
    assert start_local == datetime(2026, 5, 1, 0, 0, tzinfo=TZ)
    assert end_local == datetime(2026, 6, 1, 0, 0, tzinfo=TZ)


def test_period_unknown_type_raises() -> None:
    with pytest.raises(ValueError):
        period_for("yearly", datetime(2026, 6, 19, tzinfo=TZ))


def test_render_report_text_contains_key_sections() -> None:
    stats = StatsResult(
        granularity="day", start=0, end=DAY - 1, total=5,
        by_level={1: 2, 3: 3}, by_source={"platform": 4, "ems": 1},
        by_event_type={0: 1}, buckets=[StatsBucket(bucket="1970-01-01", total=5)],
        top_resources=[("p1", 3), ("p2", 2)],
        mtta_seconds=120.0, mttr_seconds=600.0,
    )
    text = render_report_text(stats, {"p1": "温度1"}, "daily", TZ)
    assert "告警日报" in text
    assert "告警总数：5" in text
    assert "紧急：2" in text
    assert "平台规则：4" in text
    assert "MTTA" in text and "MTTR" in text
    # Top 资源含解析出的名称
    assert "温度1" in text


def test_cron_from_crontab_parses_valid_and_rejects_invalid() -> None:
    # 每日 08:00 触发应可解析
    CronTrigger.from_crontab("0 8 * * *", timezone="Asia/Shanghai")
    with pytest.raises(ValueError):
        CronTrigger.from_crontab("not a cron", timezone="Asia/Shanghai")
