"""EMS 设备级告警接入。

红线 #7（混合告警源）：
- 仅纳入 event_type ∈ {0 通信中断, 21 故障, 30 停止采集}（source=ems 入库）。
- 其余阈值类（2 过高 / 3 不正常 / 4 过低 等）默认丢弃（由平台规则引擎负责），并按 guid 去重。

msg_type：0 产生 / 1 恢复 / 2 受理 / 3 确认 —— 决定取哪个子结构。
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    ALARM_SOURCE_EMS,
    EMS_ALARM_ACCEPT_TYPES,
    EMS_MSG_ACCEPT,
    EMS_MSG_CONFIRM,
    EMS_MSG_RAISE,
    EMS_MSG_RECOVER,
    RESOURCE_KIND_DEVICE,
)
from app.core.db import AsyncSessionLocal
from app.core.logging import get_logger
from app.core.metrics import M_ALARM_UNMATCHED, record_failure
from app.engine import lifecycle
from app.engine.lifecycle import OPEN_STATUSES
from app.models.alarm import Alarm

logger = get_logger("engine")


def _to_int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def _find_by_guid(db: AsyncSession, guid: str | None, *, open_only: bool) -> Alarm | None:
    if not guid:
        return None
    stmt = select(Alarm).where(Alarm.guid == guid)
    if open_only:
        stmt = stmt.where(Alarm.status.in_(OPEN_STATUSES))
    stmt = stmt.order_by(Alarm.id.desc()).limit(1)
    return (await db.execute(stmt)).scalar_one_or_none()


async def _handle_raise(db: AsyncSession, a: dict[str, Any]) -> bool:
    ev = a.get("event_alarm") or {}
    event_type = _to_int(ev.get("event_type"))
    # 红线 #7：仅纳通信中断/故障/停采，其余阈值类丢弃
    if event_type not in EMS_ALARM_ACCEPT_TYPES:
        logger.info(
            "丢弃非纳入类 EMS 告警（阈值类由平台引擎负责）",
            extra={"extra_fields": {"event_type": event_type}},
        )
        return False
    guid = a.get("guid")
    # 去重：同 guid 已入库则跳过
    if await _find_by_guid(db, guid, open_only=False) is not None:
        logger.info("EMS 告警去重（guid 已存在）", extra={"extra_fields": {"guid": guid}})
        return False
    resource_id = a.get("resource_id")
    if not resource_id:
        return False
    # EMS 告警以 guid 为身份：merge_id 用 guid，保证不同 guid 不互相合并、
    # 同 guid 由上游去重拦截；从而受理/确认/恢复均可按 guid 精确定位。
    # 回退：guid 缺失时退用 event_type 作为 merge_id（极少见，仅保证有非空合并键）。
    alarm = await lifecycle.raise_alarm(
        db,
        source=ALARM_SOURCE_EMS,
        resource_id=resource_id,
        resource_kind=RESOURCE_KIND_DEVICE,
        level=_to_int(ev.get("event_level"), 5) or 5,
        merge_id=guid or event_type,
        event_type=event_type,
        value=_to_float(ev.get("event_snapshot")),
        content=ev.get("content"),
        suggest=ev.get("event_suggest"),
        guid=guid,
    )
    return alarm is not None


async def _handle_recover(db: AsyncSession, a: dict[str, Any]) -> bool:
    alarm = await _find_by_guid(db, a.get("guid"), open_only=True)
    if alarm is None:
        # 审查 I7：收到恢复但本地无对应 open 告警（首发丢失/guid 不匹配）此前静默丢弃，
        # 会留下永不消除的幽灵告警。改为记 warning + 指标，使其可追溯。
        await _log_unmatched("recover", a.get("guid"))
        return False
    rec = a.get("event_recover") or {}
    await lifecycle.recover_alarm(db, alarm, desc=rec.get("recover_des") or "EMS 恢复")
    return True


async def _log_unmatched(kind: str, guid: str | None) -> None:
    """EMS 回写未匹配到 open 告警的统一可观测（审查 I7）。"""
    logger.warning(
        "EMS 告警回写未匹配到 open 告警",
        extra={"extra_fields": {"kind": kind, "guid": guid}},
    )
    await record_failure(M_ALARM_UNMATCHED, error=f"{kind}:{guid}")


async def _handle_manual(db: AsyncSession, a: dict[str, Any], msg_type: int) -> bool:
    """EMS 侧受理/确认回写（系统来源，operator_id 留空）。"""
    alarm = await _find_by_guid(db, a.get("guid"), open_only=True)
    if alarm is None:
        await _log_unmatched("accept/confirm", a.get("guid"))
        return False
    try:
        if msg_type == EMS_MSG_ACCEPT:
            note = (a.get("event_accept") or {}).get("accept_des")
            await lifecycle.accept_alarm(db, alarm, user_id=0, note=note)
        else:  # EMS_MSG_CONFIRM
            note = (a.get("event_confirm") or {}).get("confirm_des")
            await lifecycle.confirm_alarm(db, alarm, user_id=0, note=note)
    except ValueError:
        return False  # 非法状态转移，忽略
    return True


async def handle_alarm_push(data: dict[str, Any]) -> int:
    """处理一轮告警推送，返回实际处理（入库/变更）的条数。"""
    alarms = data.get("alarms") or []
    processed = 0
    async with AsyncSessionLocal() as db:
        for a in alarms:
            if not isinstance(a, dict):
                continue
            raw_msg = _to_int(a.get("msg_type"))
            msg_type = EMS_MSG_RAISE if raw_msg is None else raw_msg
            try:
                if msg_type == EMS_MSG_RAISE:
                    handled = await _handle_raise(db, a)
                elif msg_type == EMS_MSG_RECOVER:
                    handled = await _handle_recover(db, a)
                elif msg_type in (EMS_MSG_ACCEPT, EMS_MSG_CONFIRM):
                    handled = await _handle_manual(db, a, msg_type)
                else:
                    handled = False
            except Exception as exc:
                logger.error("处理单条 EMS 告警失败", extra={"extra_fields": {"error": str(exc)}})
                handled = False
            if handled:
                processed += 1
        await db.commit()
        await lifecycle.publish_pending(db)
    return processed
