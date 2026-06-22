"""抑制：测点屏蔽 / 维护窗口静默 / 防轰炸合并键。

开发约定「防轰炸/去抖/恢复」 + PRD「屏蔽/维护窗口内不误扰」（注：红线 #7 指混合告警源，非防轰炸）：
- 屏蔽（point_mute）/维护窗口（maintenance_windows）内的告警标记 masked + silenced_reason，
  不参与通知（Sprint 4），维护窗口可选 record_silenced=False 直接丢弃。
- 合并：同 merge_key 在合并窗口内的高频告警合并计数（lifecycle 使用）。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import RESOURCE_KIND_DEVICE, RESOURCE_KIND_POINT, RESOURCE_KIND_SPACE
from app.models.asset import Device, Point
from app.models.suppress import MaintenanceWindow, PointMute


# ---- 纯函数（可离线单测）----
def within_window(start: datetime | None, end: datetime | None, now: datetime) -> bool:
    """now 是否落在 [start, end] 内；start/end 为 None 视为无界。"""
    if start is not None and now < start:
        return False
    if end is not None and now > end:
        return False
    return True


def build_merge_key(source: str, key_id: str | int, resource_id: str) -> str:
    """防轰炸合并键：来源 + 规则/事件类型 + 资源。"""
    return f"{source}:{key_id}:{resource_id}"


# ---- DB 谓词 ----
async def is_muted(db: AsyncSession, point_id: str, now: datetime) -> bool:
    """测点是否处于屏蔽期。end_at 为 NULL 表示长期屏蔽。"""
    rows = (
        await db.execute(
            select(PointMute.start_at, PointMute.end_at).where(
                PointMute.point_id == point_id, PointMute.enabled.is_(True)
            )
        )
    ).all()
    return any(within_window(s, e, now) for s, e in rows)


async def _resolve_scope_ids(
    db: AsyncSession, resource_id: str, resource_kind: int
) -> dict[int, str]:
    """解析资源在各 scope 维度上的归属 id（用于维护窗口范围匹配）。"""
    cand: dict[int, str] = {}
    if resource_kind == RESOURCE_KIND_POINT:
        cand[RESOURCE_KIND_POINT] = resource_id
        point = await db.get(Point, resource_id)
        if point is not None:
            cand[RESOURCE_KIND_DEVICE] = point.device_id
            dev = await db.get(Device, point.device_id)
            if dev is not None and dev.parent_id:
                cand[RESOURCE_KIND_SPACE] = dev.parent_id
    elif resource_kind == RESOURCE_KIND_DEVICE:
        cand[RESOURCE_KIND_DEVICE] = resource_id
        dev = await db.get(Device, resource_id)
        if dev is not None and dev.parent_id:
            cand[RESOURCE_KIND_SPACE] = dev.parent_id
    else:
        cand[resource_kind] = resource_id
    return cand


async def maintenance_silenced(
    db: AsyncSession, resource_id: str, resource_kind: int, now: datetime
) -> tuple[bool, bool]:
    """资源是否处于维护窗口静默。返回 (silenced, should_record)。

    should_record：匹配窗口中只要有一个 record_silenced=True 即记录为静默告警；
    全部 record_silenced=False 则应直接丢弃。
    """
    cand = await _resolve_scope_ids(db, resource_id, resource_kind)
    # 审查 I10：把生效时间谓词下推到 SQL，仅取当前生效的窗口，避免每条告警全表扫描后在内存过滤。
    # NULL 边界视为无界（与 within_window 一致）；within_window 仍作最终精确判定。
    windows = (
        await db.execute(
            select(
                MaintenanceWindow.scope_kind,
                MaintenanceWindow.scope_ids,
                MaintenanceWindow.start_at,
                MaintenanceWindow.end_at,
                MaintenanceWindow.record_silenced,
            ).where(
                or_(MaintenanceWindow.start_at.is_(None), MaintenanceWindow.start_at <= now),
                or_(MaintenanceWindow.end_at.is_(None), MaintenanceWindow.end_at >= now),
            )
        )
    ).all()
    silenced = False
    should_record = False
    for scope_kind, scope_ids, start, end, record in windows:
        if not within_window(start, end, now):
            continue
        cid = cand.get(scope_kind)
        if cid is not None and cid in (scope_ids or []):
            silenced = True
            should_record = should_record or bool(record)
    return silenced, should_record
