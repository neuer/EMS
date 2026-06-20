"""规则引擎：多档静态阈值 + 区间 + 去抖 + 自动恢复 + 同点多档取最高。

数据流：采集层把测点值喂入 evaluate() → 命中阈值（去抖确认）→ 委托 lifecycle 起告警；
值恢复（满足恢复条件且保持 recover_hold）→ 自动恢复。

红线 #7：阈值/逻辑类告警由本引擎负责（source=platform）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    ALARM_SOURCE_PLATFORM,
    REDIS_RULE_BREACH,
    REDIS_RULE_RECOVER,
    RESOURCE_KIND_POINT,
    RULE_TIMER_TTL,
)
from app.core.db import AsyncSessionLocal
from app.core.logging import get_logger
from app.core.redis import redis_client
from app.engine import lifecycle
from app.engine.lifecycle import OPEN_STATUSES
from app.models.alarm import Alarm, AlarmRule
from app.schemas.rule import CondType, Operator

logger = get_logger("engine")


@dataclass(frozen=True)
class RuleSpec:
    """会话无关的规则快照（供内存缓存与纯函数评估）。"""

    id: int
    point_id: str
    level: int
    priority: int
    operator: Operator
    operand: float | None
    operand_min: float | None
    operand_max: float | None
    cond_type: CondType
    restore_operator: Operator | None
    restore_operand: float | None
    continuous_time: int
    recover_hold_time: int
    content_tpl: str | None
    suggest: str | None


# ---- 纯函数（可离线单测）----
def compare(value: float, op: str, operand: float | None) -> bool:
    """单目比较：> < = <> <= >=。operand 缺失返回 False。"""
    if operand is None:
        return False
    if op == ">":
        return value > operand
    if op == "<":
        return value < operand
    if op == ">=":
        return value >= operand
    if op == "<=":
        return value <= operand
    if op == "=":
        return value == operand
    if op == "<>":
        return value != operand
    return False


def eval_condition(value: float, spec: RuleSpec) -> bool:
    """触发条件评估。range：operand_min ≤ value ≤ operand_max 命中。"""
    if spec.cond_type == "range":
        lo, hi = spec.operand_min, spec.operand_max
        if lo is None or hi is None:
            return False
        return lo <= value <= hi
    return compare(value, spec.operator, spec.operand)


def eval_restore(value: float, spec: RuleSpec) -> bool:
    """恢复条件：显式 restore_* 优先，否则取「不再满足触发条件」。"""
    if spec.restore_operator and spec.restore_operand is not None:
        return compare(value, spec.restore_operator, spec.restore_operand)
    return not eval_condition(value, spec)


def highest(specs: list[RuleSpec]) -> RuleSpec | None:
    """同点多档取最高：level 越小越严重；同级取 priority 大者。"""
    if not specs:
        return None
    return min(specs, key=lambda r: (r.level, -r.priority))


def platform_event_type(operator: str) -> int:
    """平台阈值告警的 event_type 映射（供分类/统计）。"""
    if operator in (">", ">="):
        return 2  # 过高
    if operator in ("<", "<="):
        return 4  # 过低
    return 3  # 不正常值


def render_content(spec: RuleSpec, point_id: str, value: float) -> str:
    if spec.content_tpl:
        try:
            return spec.content_tpl.format(point_id=point_id, value=value)
        except (KeyError, IndexError, ValueError):
            return spec.content_tpl
    return f"测点 {point_id} 触发规则#{spec.id}，当前值 {value}"


# ---- 规则缓存 ----
class RuleCache:
    """启用规则的内存缓存（按 point_id 分组）；CRUD 后失效，并带 TTL 兜底。"""

    def __init__(self, ttl: int = 30) -> None:
        self._by_point: dict[str, list[RuleSpec]] = {}
        self._loaded_at: float = 0.0
        self._ttl = ttl

    def invalidate(self) -> None:
        self._loaded_at = 0.0

    async def _reload(self, db: AsyncSession) -> None:
        rows = (
            await db.execute(select(AlarmRule).where(AlarmRule.enabled.is_(True)))
        ).scalars().all()
        by_point: dict[str, list[RuleSpec]] = {}
        for r in rows:
            by_point.setdefault(r.point_id, []).append(
                RuleSpec(
                    id=r.id, point_id=r.point_id, level=r.level, priority=r.priority,
                    # DB 列为 str；取值经创建/更新校验保证合法，构造时 cast 为字面量类型
                    operator=cast(Operator, r.operator), operand=r.operand,
                    operand_min=r.operand_min, operand_max=r.operand_max,
                    cond_type=cast(CondType, r.cond_type),
                    restore_operator=cast("Operator | None", r.restore_operator),
                    restore_operand=r.restore_operand, continuous_time=r.continuous_time,
                    recover_hold_time=r.recover_hold_time,
                    content_tpl=r.content_tpl, suggest=r.suggest,
                )
            )
        self._by_point = by_point
        self._loaded_at = time.time()

    async def get_for_point(self, db: AsyncSession, point_id: str) -> list[RuleSpec]:
        if time.time() - self._loaded_at > self._ttl:
            await self._reload(db)
        return self._by_point.get(point_id, [])


_cache = RuleCache()


def invalidate_rule_cache() -> None:
    """规则 CRUD 后调用，使缓存立即失效。"""
    _cache.invalidate()


# ---- 去抖 / 恢复保持计时（Redis）----
async def _debounced_breach(spec: RuleSpec, ts: int) -> bool:
    """返回越限是否已通过 continuous_time 去抖确认。"""
    if spec.continuous_time <= 0:
        return True
    key = REDIS_RULE_BREACH.format(rule_id=spec.id)
    first = await redis_client.get(key)
    if first is None:
        await redis_client.set(key, ts, ex=RULE_TIMER_TTL)
        return False
    return ts - int(first) >= spec.continuous_time


async def _clear_timer(prefix: str, rule_id: int) -> None:
    await redis_client.delete(prefix.format(rule_id=rule_id))


async def _hold_recovered(spec: RuleSpec, ts: int) -> bool:
    """返回恢复是否已通过 recover_hold_time 保持确认。"""
    if spec.recover_hold_time <= 0:
        return True
    key = REDIS_RULE_RECOVER.format(rule_id=spec.id)
    first = await redis_client.get(key)
    if first is None:
        await redis_client.set(key, ts, ex=RULE_TIMER_TTL)
        return False
    return ts - int(first) >= spec.recover_hold_time


# ---- 评估入口 ----
async def _evaluate_one(
    db: AsyncSession, specs: list[RuleSpec], point_id: str, value: float, ts: int
) -> bool:
    """对单测点评估全部规则，按需起/恢复告警。返回是否有状态变更（不 commit）。"""
    # 1) 计算去抖确认后的越限规则
    breached: list[RuleSpec] = []
    for spec in specs:
        if eval_condition(value, spec):
            if await _debounced_breach(spec, ts):
                breached.append(spec)
        else:
            await _clear_timer(REDIS_RULE_BREACH, spec.id)
    target = highest(breached)

    # 2) 取当前在途的平台告警
    active = (
        await db.execute(
            select(Alarm).where(
                Alarm.source == ALARM_SOURCE_PLATFORM,
                Alarm.resource_id == point_id,
                Alarm.status.in_(OPEN_STATUSES),
            )
        )
    ).scalars().all()
    spec_by_id = {s.id: s for s in specs}

    changed = False
    # 3) 处理在途告警：被更高档取代→升/降档恢复；否则按恢复条件自动恢复
    for al in active:
        if target is not None and al.rule_id == target.id:
            continue  # 目标档已在途，保持
        if target is not None:
            await lifecycle.recover_alarm(db, al, value=value, desc="切换为其他档告警")
            await _clear_timer(REDIS_RULE_RECOVER, al.rule_id or 0)
            changed = True
            continue
        # 无越限：检查恢复条件 + 保持
        spec = spec_by_id.get(al.rule_id or -1)
        if spec is None:
            await lifecycle.recover_alarm(db, al, value=value, desc="规则已停用/删除")
            changed = True
            continue
        if eval_restore(value, spec):
            if await _hold_recovered(spec, ts):
                await lifecycle.recover_alarm(db, al, value=value)
                await _clear_timer(REDIS_RULE_RECOVER, spec.id)
                changed = True
        else:
            await _clear_timer(REDIS_RULE_RECOVER, spec.id)

    # 4) 产生目标档告警（若尚无在途）
    if target is not None and not any(al.rule_id == target.id for al in active):
        await _clear_timer(REDIS_RULE_RECOVER, target.id)
        await lifecycle.raise_alarm(
            db,
            source=ALARM_SOURCE_PLATFORM,
            resource_id=point_id,
            resource_kind=RESOURCE_KIND_POINT,
            level=target.level,
            merge_id=target.id,
            event_type=platform_event_type(target.operator),
            value=value,
            content=render_content(target, point_id, value),
            suggest=target.suggest,
            rule_id=target.id,
        )
        changed = True
    return changed


async def evaluate(point_id: str, value: float | None, ts: int) -> None:
    """对单测点最新值评估全部规则（独立会话）。"""
    if value is None:
        return
    async with AsyncSessionLocal() as db:
        specs = await _cache.get_for_point(db, point_id)
        if not specs:
            return
        if await _evaluate_one(db, specs, point_id, value, ts):
            await db.commit()
            await lifecycle.publish_pending(db)


async def evaluate_batch(items: list[tuple[str, float | None, int]]) -> None:
    """批量评估一轮推送的多测点（单会话，单次提交）。"""
    if not items:
        return
    async with AsyncSessionLocal() as db:
        changed = False
        for point_id, value, ts in items:
            if value is None:
                continue
            specs = await _cache.get_for_point(db, point_id)
            if not specs:
                continue
            if await _evaluate_one(db, specs, point_id, value, ts):
                changed = True
        if changed:
            await db.commit()
            await lifecycle.publish_pending(db)
