"""报表计划 cron 校验（审查 I4）。

回归：cron 此前仅校验长度，非法值落库后 reload 静默跳过 → POST 200 但报表永不运行。
修复后非法 cron 在 schema 层即被拒绝。
"""
from __future__ import annotations

import pytest
from app.schemas.report import ReportScheduleInput, ReportScheduleUpdate
from pydantic import ValidationError


def test_valid_cron_accepted():
    s = ReportScheduleInput(report_type="daily", cron="0 8 * * *")
    assert s.cron == "0 8 * * *"


def test_invalid_cron_rejected():
    with pytest.raises(ValidationError):
        ReportScheduleInput(report_type="daily", cron="不是 cron 表达式")


def test_update_invalid_cron_rejected():
    with pytest.raises(ValidationError):
        ReportScheduleUpdate(cron="99 99 99 99 99")


def test_update_none_cron_allowed():
    u = ReportScheduleUpdate(name="改名", cron=None)
    assert u.cron is None
