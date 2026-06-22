"""告警/规则 CHECK 约束测试（审查 M4，离线确定性）。

DB 作为封闭域最后防线：绕过 Pydantic 直接构造非法 status/source/operator/cond_type 的 ORM 对象
落库时必须被拒。mem_db 经 create_all 在 sqlite 带上同样的 CHECK，sqlite 会强制执行。
"""
from __future__ import annotations

import pytest
from app.models.alarm import Alarm, AlarmRule
from sqlalchemy.exc import IntegrityError


async def _insert(sessionmaker, obj) -> None:
    async with sessionmaker() as db:
        db.add(obj)
        await db.commit()


async def test_invalid_alarm_status_rejected(mem_db) -> None:
    bad = Alarm(source="platform", resource_id="d1", resource_kind=3, level=2, status="bogus")
    with pytest.raises(IntegrityError):
        await _insert(mem_db, bad)


async def test_invalid_alarm_source_rejected(mem_db) -> None:
    bad = Alarm(source="weird", resource_id="d1", resource_kind=3, level=2, status="active")
    with pytest.raises(IntegrityError):
        await _insert(mem_db, bad)


async def test_invalid_resource_kind_rejected(mem_db) -> None:
    bad = Alarm(source="ems", resource_id="d1", resource_kind=9, level=2, status="active")
    with pytest.raises(IntegrityError):
        await _insert(mem_db, bad)


async def test_invalid_rule_operator_rejected(mem_db) -> None:
    bad = AlarmRule(point_id="p1", operator="!!", cond_type="threshold", operand=1.0, level=2)
    with pytest.raises(IntegrityError):
        await _insert(mem_db, bad)


async def test_invalid_cond_type_rejected(mem_db) -> None:
    bad = AlarmRule(point_id="p1", operator=">", cond_type="weird", operand=1.0, level=2)
    with pytest.raises(IntegrityError):
        await _insert(mem_db, bad)


async def test_valid_alarm_and_rule_pass(mem_db) -> None:
    await _insert(
        mem_db,
        Alarm(source="ems", resource_id="d1", resource_kind=2, level=1, status="recovered"),
    )
    await _insert(
        mem_db,
        AlarmRule(point_id="p1", operator=">=", cond_type="range",
                  operand_min=1.0, operand_max=2.0, level=3),
    )
