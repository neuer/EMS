"""Schema 不变量与枚举契约稳定性测试（审查 S3/M3/M4）。"""
from __future__ import annotations

import pytest
from app.core.constants import AlarmSource, AlarmStatus, ResourceKind
from app.schemas.alarm import AlarmOutput
from app.schemas.history import AggSample, HistorySeries, RawSample
from app.schemas.notify import RecipientInput
from pydantic import ValidationError


def test_recipient_requires_a_contact():
    with pytest.raises(ValidationError):
        RecipientInput(name="无联系方式")
    RecipientInput(name="ok", email="a@b.c")  # 有一个即可


def test_history_series_layer_consistency():
    with pytest.raises(ValidationError):
        HistorySeries(point_id="p", layer="raw", agg=[AggSample(ts=0)])
    with pytest.raises(ValidationError):
        HistorySeries(point_id="p", layer="5min", raw=[RawSample(ts=0)])
    HistorySeries(point_id="p", layer="raw", raw=[RawSample(ts=0)])  # ok


def test_alarm_enum_json_contract_stable():
    """枚举字段 model_dump(mode=json) 仍输出历史字符串/整数值（契约不变）。"""
    out = AlarmOutput(
        id=1, source=AlarmSource.PLATFORM, resource_id="p1",
        resource_kind=ResourceKind.POINT, level=2, status=AlarmStatus.ACTIVE,
        masked=False, merge_count=1, triggered_at="2026-06-20T00:00:00Z",  # type: ignore[arg-type]
    )
    dumped = out.model_dump(mode="json")
    assert dumped["source"] == "platform"
    assert dumped["status"] == "active"
    assert dumped["resource_kind"] == 3


def test_alarm_output_coerces_db_strings():
    """从 DB 取出的裸字符串/整数可被枚举字段接受（model_validate）。"""
    out = AlarmOutput.model_validate({
        "id": 1, "source": "ems", "resource_id": "d1", "resource_kind": 2,
        "level": 2, "status": "recovered", "masked": False, "merge_count": 1,
        "triggered_at": "2026-06-20T00:00:00Z",
    })
    assert out.source is AlarmSource.EMS
    assert out.status is AlarmStatus.RECOVERED
