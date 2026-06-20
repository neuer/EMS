"""规则更新一致性测试（审查 I2）。

PATCH 不得把规则改成「落库即非法、引擎静默永不触发」的状态。
"""
from __future__ import annotations

from typing import cast

import pytest
from app.api.rules import update_rule
from app.models.alarm import AlarmRule
from app.models.user import User
from app.schemas.rule import RuleUpdate, check_operands
from fastapi import HTTPException

_USER = cast(User, object())  # update_rule 不使用鉴权依赖结果


def test_check_operands_threshold_requires_operand():
    with pytest.raises(ValueError):
        check_operands("threshold", None, None, None)
    check_operands("threshold", 30.0, None, None)  # ok


def test_check_operands_range_requires_min_le_max():
    with pytest.raises(ValueError):
        check_operands("range", None, None, None)  # 缺 min/max
    with pytest.raises(ValueError):
        check_operands("range", None, 50.0, 10.0)  # min>max
    check_operands("range", None, 10.0, 50.0)  # ok


async def _make_rule(mem_db, **over) -> int:
    base = dict(
        point_id="p1", operator=">", operand=30.0, cond_type="threshold", level=2, priority=0,
        continuous_time=0, recover_hold_time=0,
    )
    base.update(over)
    async with mem_db() as db:
        rule = AlarmRule(**base)
        db.add(rule)
        await db.commit()
        await db.refresh(rule)
        return rule.id


async def test_update_rule_rejects_inconsistent_patch(mem_db):
    """把 range 规则改成 min>max → 422，不落库。"""
    rid = await _make_rule(
        mem_db, cond_type="range", operand=None, operand_min=10.0, operand_max=50.0
    )
    async with mem_db() as db:
        with pytest.raises(HTTPException) as exc:
            await update_rule(rid, RuleUpdate.model_validate({"operand_min": 99.0}), _USER, db)
        assert exc.value.status_code == 422


async def test_update_rule_accepts_valid_patch(mem_db):
    rid = await _make_rule(mem_db)
    async with mem_db() as db:
        body = RuleUpdate.model_validate({"operand": 45.0, "level": 1})
        result = await update_rule(rid, body, _USER, db)
    assert result["data"]["operand"] == 45.0  # type: ignore[index]
    assert result["data"]["level"] == 1  # type: ignore[index]
