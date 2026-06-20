"""告警中心 API（A5）：活动/历史/详情/受理/确认/备注/统计。"""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.core.constants import ALARM_STATUS_RECOVERED
from app.core.db import get_db
from app.core.security import Role
from app.engine import lifecycle
from app.engine.lifecycle import OPEN_STATUSES
from app.models.alarm import Alarm, AlarmEvent
from app.models.user import User
from app.schemas.alarm import (
    AlarmActionInput,
    AlarmDetailOutput,
    AlarmEventOutput,
    AlarmHistoryQuery,
    AlarmNoteInput,
    AlarmOutput,
)
from app.schemas.common import ok

router = APIRouter(prefix="/alarms", tags=["告警中心"])


def _dump(alarm: Alarm) -> dict[str, object]:
    return AlarmOutput.model_validate(alarm, from_attributes=True).model_dump(mode="json")


@router.get("/active")
async def list_active(
    level: int | None = Query(None, ge=1, le=5),
    event_type: int | None = Query(None),
    source: str | None = Query(None),
    resource_id: str | None = Query(None),
    masked: bool | None = Query(None),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    stmt = select(Alarm).where(Alarm.status.in_(OPEN_STATUSES))
    if level is not None:
        stmt = stmt.where(Alarm.level == level)
    if event_type is not None:
        stmt = stmt.where(Alarm.event_type == event_type)
    if source is not None:
        stmt = stmt.where(Alarm.source == source)
    if resource_id is not None:
        stmt = stmt.where(Alarm.resource_id == resource_id)
    if masked is not None:
        stmt = stmt.where(Alarm.masked.is_(masked))
    stmt = stmt.order_by(Alarm.level, Alarm.triggered_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return ok([_dump(a) for a in rows])


@router.post("/history")
async def query_history(
    body: AlarmHistoryQuery,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    start = datetime.fromtimestamp(body.start, tz=UTC)
    end = datetime.fromtimestamp(body.end, tz=UTC)
    stmt = select(Alarm).where(Alarm.triggered_at >= start, Alarm.triggered_at <= end)
    if body.level is not None:
        stmt = stmt.where(Alarm.level == body.level)
    if body.status is not None:
        stmt = stmt.where(Alarm.status == body.status)
    if body.source is not None:
        stmt = stmt.where(Alarm.source == body.source)
    if body.resource_id is not None:
        stmt = stmt.where(Alarm.resource_id == body.resource_id)
    if body.event_type is not None:
        stmt = stmt.where(Alarm.event_type == body.event_type)
    if body.masked is not None:
        stmt = stmt.where(Alarm.masked.is_(body.masked))
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    stmt = stmt.order_by(Alarm.triggered_at.desc()).limit(body.limit).offset(body.offset)
    rows = (await db.execute(stmt)).scalars().all()
    return ok({"total": total, "items": [_dump(a) for a in rows]})


@router.get("/stats")
async def stats(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    # 活动告警按级别
    by_level_rows = (
        await db.execute(
            select(Alarm.level, func.count())
            .where(Alarm.status.in_(OPEN_STATUSES))
            .group_by(Alarm.level)
        )
    ).all()
    # 全量按状态
    by_status_rows = (
        await db.execute(select(Alarm.status, func.count()).group_by(Alarm.status))
    ).all()
    # 活动按来源
    by_source_rows = (
        await db.execute(
            select(Alarm.source, func.count())
            .where(Alarm.status.in_(OPEN_STATUSES))
            .group_by(Alarm.source)
        )
    ).all()
    active_total = (
        await db.execute(
            select(func.count()).select_from(Alarm).where(Alarm.status.in_(OPEN_STATUSES))
        )
    ).scalar_one()
    return ok({
        "active_total": active_total,
        "by_level": {int(lv): int(c) for lv, c in by_level_rows},
        "by_status": {st: int(c) for st, c in by_status_rows},
        "by_source": {src: int(c) for src, c in by_source_rows},
    })


@router.get("/{alarm_id}")
async def get_detail(
    alarm_id: int,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    alarm = await db.get(Alarm, alarm_id)
    if alarm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "告警不存在")
    events = (
        await db.execute(
            select(AlarmEvent)
            .where(AlarmEvent.alarm_id == alarm_id)
            .order_by(AlarmEvent.occurred_at)
        )
    ).scalars().all()
    detail = AlarmDetailOutput.model_validate(alarm, from_attributes=True)
    detail.events = [
        AlarmEventOutput.model_validate(e, from_attributes=True) for e in events
    ]
    return ok(detail.model_dump(mode="json"))


async def _load_open(db: AsyncSession, alarm_id: int) -> Alarm:
    alarm = await db.get(Alarm, alarm_id)
    if alarm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "告警不存在")
    if alarm.status == ALARM_STATUS_RECOVERED:
        raise HTTPException(status.HTTP_409_CONFLICT, "告警已恢复，不能再操作")
    return alarm


@router.post("/{alarm_id}/accept")
async def accept(
    alarm_id: int,
    body: AlarmActionInput,
    current: User = Depends(require_role(Role.OPERATOR)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    alarm = await _load_open(db, alarm_id)
    try:
        await lifecycle.accept_alarm(db, alarm, user_id=current.id, note=body.note)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.commit()
    await db.refresh(alarm)
    return ok(_dump(alarm))


@router.post("/{alarm_id}/confirm")
async def confirm(
    alarm_id: int,
    body: AlarmActionInput,
    current: User = Depends(require_role(Role.OPERATOR)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    alarm = await _load_open(db, alarm_id)
    try:
        await lifecycle.confirm_alarm(db, alarm, user_id=current.id, note=body.note)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    await db.commit()
    await db.refresh(alarm)
    return ok(_dump(alarm))


@router.post("/{alarm_id}/note")
async def note(
    alarm_id: int,
    body: AlarmNoteInput,
    current: User = Depends(require_role(Role.OPERATOR)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    alarm = await db.get(Alarm, alarm_id)
    if alarm is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "告警不存在")
    await lifecycle.add_note(db, alarm, user_id=current.id, note=body.note)
    await db.commit()
    return ok({"alarm_id": alarm_id})
