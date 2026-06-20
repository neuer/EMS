"""预警规则 API（A4）。规则 CRUD 后失效规则引擎缓存。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.core.db import get_db
from app.core.security import Role
from app.engine.rules import invalidate_rule_cache
from app.models.alarm import AlarmRule
from app.models.user import User
from app.schemas.common import ok
from app.schemas.rule import RuleInput, RuleOutput, RuleUpdate, check_operands

router = APIRouter(prefix="/rules", tags=["预警规则"])


def _dump(rule: AlarmRule) -> dict[str, object]:
    return RuleOutput.model_validate(rule, from_attributes=True).model_dump(mode="json")


@router.get("")
async def list_rules(
    point_id: str | None = Query(None),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    stmt = select(AlarmRule)
    if point_id:
        stmt = stmt.where(AlarmRule.point_id == point_id)
    stmt = stmt.order_by(AlarmRule.point_id, AlarmRule.level)
    rows = (await db.execute(stmt)).scalars().all()
    return ok([_dump(r) for r in rows])


@router.post("")
async def create_rule(
    body: RuleInput,
    current: User = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    rule = AlarmRule(**body.model_dump(), created_by=current.id)
    db.add(rule)
    await db.commit()
    await db.refresh(rule)
    invalidate_rule_cache()
    return ok(_dump(rule))


@router.put("/{rule_id}")
async def update_rule(
    rule_id: int,
    body: RuleUpdate,
    _: User = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    rule = await db.get(AlarmRule, rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "规则不存在")
    patch = body.model_dump(exclude_none=True)
    # 审查 I2：以「现有值 + 本次补丁」合并后的整体复验操作数一致性，
    # 防止 PATCH 把 range 规则改成 min>max 或缺 min/max 而落库即静默失效。
    merged = {
        "cond_type": patch.get("cond_type", rule.cond_type),
        "operand": patch.get("operand", rule.operand),
        "operand_min": patch.get("operand_min", rule.operand_min),
        "operand_max": patch.get("operand_max", rule.operand_max),
    }
    try:
        check_operands(
            merged["cond_type"], merged["operand"],
            merged["operand_min"], merged["operand_max"],
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    for key, value in patch.items():
        setattr(rule, key, value)
    await db.commit()
    await db.refresh(rule)
    invalidate_rule_cache()
    return ok(_dump(rule))


@router.delete("/{rule_id}")
async def delete_rule(
    rule_id: int,
    _: User = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    rule = await db.get(AlarmRule, rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "规则不存在")
    await db.delete(rule)
    await db.commit()
    invalidate_rule_cache()
    return ok({"deleted": rule_id})
