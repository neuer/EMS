"""告警生命周期：状态机 + 事件流 + 起/恢复（集成抑制与防轰炸合并）。

状态机：active → accepted → confirmed → recovered；亦支持产生→恢复直达。
约束：屏蔽/维护窗口内 masked 不误扰（PRD）；同点高频告警按 merge_key 合并计数（防轰炸约定）。
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import (
    ALARM_STATUS_ACCEPTED,
    ALARM_STATUS_ACTIVE,
    ALARM_STATUS_CONFIRMED,
    ALARM_STATUS_RECOVERED,
    ANTI_FLOOD_MERGE_WINDOW_S,
    CHANNEL_ALARM_EVENTS,
    NOTIFY_TRIGGER_RAISE,
    NOTIFY_TRIGGER_RECOVER,
    REDIS_ALARM_MERGE,
    REDIS_NOTIFY_PENDING,
    RESOURCE_KIND_POINT,
)
from app.core.logging import get_logger
from app.core.metrics import M_ALARM_PUBLISH, record_failure
from app.core.redis import redis_client
from app.engine import suppress
from app.models.alarm import Alarm, AlarmEvent

logger = get_logger("engine")

# 未恢复（仍“在途”）的状态集合
OPEN_STATUSES = (ALARM_STATUS_ACTIVE, ALARM_STATUS_ACCEPTED, ALARM_STATUS_CONFIRMED)

# 人工操作的状态转移合法性（pure）。键/值为 AlarmStatus（StrEnum）成员，
# 标注为 str 以便用裸 status 字符串索引（AlarmStatus 是 str 子类）。
_ALLOWED: dict[str, dict[str, str]] = {
    "accept": {
        ALARM_STATUS_ACTIVE: ALARM_STATUS_ACCEPTED,
        ALARM_STATUS_ACCEPTED: ALARM_STATUS_ACCEPTED,
    },
    "confirm": {
        ALARM_STATUS_ACTIVE: ALARM_STATUS_CONFIRMED,
        ALARM_STATUS_ACCEPTED: ALARM_STATUS_CONFIRMED,
        ALARM_STATUS_CONFIRMED: ALARM_STATUS_CONFIRMED,
    },
}


def next_status(current: str, action: str) -> str:
    """人工动作的下一状态（纯函数）。非法转移抛 ValueError。"""
    table = _ALLOWED.get(action)
    if table is None or current not in table:
        raise ValueError(f"非法状态转移：{current} --{action}-->")
    return table[current]


async def _add_event(
    db: AsyncSession,
    alarm_id: int,
    event: str,
    *,
    operator_id: int | None = None,
    note: str | None = None,
    snapshot: float | None = None,
) -> None:
    db.add(
        AlarmEvent(
            alarm_id=alarm_id,
            event=event,
            operator_id=operator_id,
            note=note,
            snapshot=snapshot,
        )
    )


def _queue_event(db: AsyncSession, kind: str, alarm: Alarm) -> None:
    """把通知事件挂到会话上，待 commit 后由 publish_pending 发布到事件总线。

    masked（屏蔽/维护窗口）告警不通知，直接不入队。
    """
    if alarm.masked:
        return
    db.info.setdefault("_notify_events", []).append({
        "kind": kind,
        "alarm_id": alarm.id,
        "level": alarm.level,
        "merge_key": alarm.merge_key,
        "resource_id": alarm.resource_id,
        "content": alarm.content,
    })


async def publish_pending(db: AsyncSession) -> None:
    """commit 之后调用：把本会话累积的通知事件发布到 CHANNEL_ALARM_EVENTS。"""
    events = db.info.pop("_notify_events", None)
    if not events:
        return
    for ev in events:
        try:
            await redis_client.publish(CHANNEL_ALARM_EVENTS, json.dumps(ev, ensure_ascii=False))
        except Exception as exc:
            # 审查 I8/M2：告警已 commit 但事件发布失败 → 该告警不会触发任何通知（静默丢失）。
            # 记指标使其可观测，并把事件入持久化补偿队列由调度器重投，做到「通知不丢」。
            logger.error("发布告警事件失败，入补偿队列待重投",
                         extra={"extra_fields": {"error": str(exc)}})
            await record_failure(M_ALARM_PUBLISH, error=str(exc))
            try:
                await redis_client.rpush(
                    REDIS_NOTIFY_PENDING, json.dumps({**ev, "_attempts": 0}, ensure_ascii=False)
                )
            except Exception as q_exc:  # 入队也失败：仅降级日志，不反向影响主流程
                logger.error("补偿队列入队失败，该通知可能丢失",
                             extra={"extra_fields": {"error": str(q_exc)}})


async def raise_alarm(
    db: AsyncSession,
    *,
    source: str,
    resource_id: str,
    resource_kind: int,
    level: int,
    merge_id: str | int,
    event_type: int | None = None,
    value: float | None = None,
    content: str | None = None,
    suggest: str | None = None,
    rule_id: int | None = None,
    guid: str | None = None,
) -> Alarm | None:
    """产生告警（含抑制判定与防轰炸合并）。返回告警对象；被丢弃时返回 None。

    调用方负责 commit。
    """
    now = datetime.now(UTC)

    # ---- 抑制：屏蔽 + 维护窗口 ----
    masked = False
    silenced_reason: str | None = None
    if resource_kind == RESOURCE_KIND_POINT and await suppress.is_muted(db, resource_id, now):
        masked = True
        silenced_reason = "mute"
    if not masked:
        silenced, should_record = await suppress.maintenance_silenced(
            db, resource_id, resource_kind, now
        )
        if silenced:
            if not should_record:
                logger.info(
                    "维护窗口内丢弃告警",
                    extra={"extra_fields": {"resource_id": resource_id}},
                )
                return None
            masked = True
            silenced_reason = "maintenance"

    # ---- 防轰炸合并 ----
    merge_key = suppress.build_merge_key(source, merge_id, resource_id)
    redis_key = REDIS_ALARM_MERGE.format(merge_key=merge_key)
    latest = (
        await db.execute(
            select(Alarm).where(Alarm.merge_key == merge_key).order_by(Alarm.id.desc()).limit(1)
        )
    ).scalar_one_or_none()

    if latest is not None and latest.status in OPEN_STATUSES:
        # 仍在途：合并计数，不新建、不重复通知
        latest.merge_count += 1
        latest.trigger_value = value
        await _add_event(db, latest.id, "merge", snapshot=value)
        await redis_client.set(redis_key, latest.id, ex=ANTI_FLOOD_MERGE_WINDOW_S)
        _queue_event(db, "merge", latest)
        return latest

    if latest is not None and latest.status == ALARM_STATUS_RECOVERED:
        within = await redis_client.get(redis_key)
        if within is not None:
            # 合并窗口内抖动复发：复活原告警计数合并
            latest.status = ALARM_STATUS_ACTIVE
            latest.merge_count += 1
            latest.trigger_value = value
            latest.recovered_at = None
            latest.recover_desc = None
            latest.masked = masked
            latest.silenced_reason = silenced_reason
            await _add_event(db, latest.id, "merge", snapshot=value)
            await redis_client.set(redis_key, latest.id, ex=ANTI_FLOOD_MERGE_WINDOW_S)
            _queue_event(db, "merge", latest)
            return latest

    # ---- 新建告警 ----
    alarm = Alarm(
        source=source,
        guid=guid,
        rule_id=rule_id,
        resource_id=resource_id,
        resource_kind=resource_kind,
        event_type=event_type,
        level=level,
        status=ALARM_STATUS_ACTIVE,
        trigger_value=value,
        content=content,
        suggest=suggest,
        masked=masked,
        silenced_reason=silenced_reason,
        merge_key=merge_key,
        merge_count=1,
        triggered_at=now,
    )
    db.add(alarm)
    await db.flush()
    await _add_event(db, alarm.id, "raise", snapshot=value)
    await redis_client.set(redis_key, alarm.id, ex=ANTI_FLOOD_MERGE_WINDOW_S)
    _queue_event(db, NOTIFY_TRIGGER_RAISE, alarm)
    logger.info(
        "产生告警",
        extra={"extra_fields": {
            "id": alarm.id, "source": source, "resource_id": resource_id,
            "level": level, "masked": masked,
        }},
    )
    return alarm


async def recover_alarm(
    db: AsyncSession, alarm: Alarm, *, value: float | None = None, desc: str = "自动恢复"
) -> None:
    """恢复告警（产生→恢复直达亦走此路径）。调用方负责 commit。"""
    if alarm.status == ALARM_STATUS_RECOVERED:
        return
    alarm.status = ALARM_STATUS_RECOVERED
    alarm.recovered_at = datetime.now(UTC)
    alarm.recover_desc = desc
    await _add_event(db, alarm.id, "recover", snapshot=value, note=desc)
    _queue_event(db, NOTIFY_TRIGGER_RECOVER, alarm)
    logger.info("告警恢复", extra={"extra_fields": {"id": alarm.id, "desc": desc}})


async def accept_alarm(db: AsyncSession, alarm: Alarm, *, user_id: int, note: str | None) -> None:
    alarm.status = next_status(alarm.status, "accept")
    alarm.accepted_at = datetime.now(UTC)
    alarm.accepted_by = user_id
    alarm.accept_note = note
    await _add_event(db, alarm.id, "accept", operator_id=user_id, note=note)


async def confirm_alarm(db: AsyncSession, alarm: Alarm, *, user_id: int, note: str | None) -> None:
    alarm.status = next_status(alarm.status, "confirm")
    alarm.confirmed_at = datetime.now(UTC)
    alarm.confirmed_by = user_id
    alarm.confirm_note = note
    await _add_event(db, alarm.id, "confirm", operator_id=user_id, note=note)


async def add_note(db: AsyncSession, alarm: Alarm, *, user_id: int, note: str) -> None:
    await _add_event(db, alarm.id, "note", operator_id=user_id, note=note)
