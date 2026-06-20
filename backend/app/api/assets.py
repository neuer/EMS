"""资产树/设备/测点/元数据 API（A2）。

只读镜像（spaces/devices/points）+ 元数据增强（asset_meta，红线 #8 不污染源）。
当前值走 Redis（红线：最新值缓存），告警状态来自 alarms 表汇总。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.core.constants import (
    ALARM_STATUS_ACCEPTED,
    ALARM_STATUS_ACTIVE,
    ALARM_STATUS_CONFIRMED,
    REDIS_DEVICE_STATUS,
    REDIS_POINT_LATEST,
    RESOURCE_KIND_DEVICE,
    RESOURCE_KIND_POINT,
    RESOURCE_KIND_SPACE,
)
from app.core.db import get_db
from app.core.redis import redis_client
from app.core.security import Role
from app.models.alarm import Alarm, AlarmRule
from app.models.asset import Device, Point, Space
from app.models.meta import AssetMeta
from app.models.user import User
from app.schemas.asset import (
    AssetMetaInput,
    AssetMetaOutput,
    DeviceDetail,
    DeviceOutput,
    PointDetail,
    PointOutput,
    RuleBrief,
    SpaceNode,
)
from app.schemas.common import ok

router = APIRouter(tags=["资产与元数据"])

_OPEN = (ALARM_STATUS_ACTIVE, ALARM_STATUS_ACCEPTED, ALARM_STATUS_CONFIRMED)


# ---------------- 共用查询 ----------------
async def _meta_map(db: AsyncSession) -> dict[str, AssetMeta]:
    rows = (await db.execute(select(AssetMeta))).scalars().all()
    return {m.resource_id: m for m in rows}


async def _alarm_counts(db: AsyncSession) -> dict[str, tuple[int, int]]:
    """resource_id -> (活动告警数, 最严重级别)。"""
    rows = (
        await db.execute(
            select(Alarm.resource_id, Alarm.level).where(Alarm.status.in_(_OPEN))
        )
    ).all()
    out: dict[str, tuple[int, int]] = {}
    for rid, level in rows:
        cnt, lv = out.get(rid, (0, 99))
        out[rid] = (cnt + 1, min(lv, level))
    return out


async def _point_values(point_ids: list[str]) -> dict[str, tuple[str | None, int | None]]:
    if not point_ids:
        return {}
    pipe = redis_client.pipeline()
    for pid in point_ids:
        pipe.hgetall(REDIS_POINT_LATEST.format(point_id=pid))
    rows = await pipe.execute()
    out: dict[str, tuple[str | None, int | None]] = {}
    for pid, h in zip(point_ids, rows, strict=True):
        if h:
            st = h.get("save_time")
            out[pid] = (h.get("value"), int(st) if st not in (None, "") else None)
        else:
            out[pid] = (None, None)
    return out


async def _device_statuses(device_ids: list[str]) -> dict[str, int | None]:
    if not device_ids:
        return {}
    pipe = redis_client.pipeline()
    for did in device_ids:
        pipe.get(REDIS_DEVICE_STATUS.format(device_id=did))
    rows = await pipe.execute()
    return {
        did: (int(v) if v not in (None, "") else None)
        for did, v in zip(device_ids, rows, strict=True)
    }


def _meta_fields(meta: AssetMeta | None) -> dict[str, Any]:
    if meta is None:
        return {"alias": None, "group_name": None, "importance": None,
                "custom_unit": None, "tags": None}
    return {
        "alias": meta.alias, "group_name": meta.group_name,
        "importance": meta.importance, "custom_unit": meta.custom_unit, "tags": meta.tags,
    }


# ---------------- 空间树 ----------------
@router.get("/tree/spaces")
async def tree_spaces(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    spaces = (await db.execute(select(Space).where(Space.is_active.is_(True)))).scalars().all()
    devices = (await db.execute(select(Device).where(Device.is_active.is_(True)))).scalars().all()
    points = (await db.execute(select(Point).where(Point.is_active.is_(True)))).scalars().all()
    meta = await _meta_map(db)

    space_by_id = {s.resource_id: s for s in spaces}
    dev_space = {d.resource_id: d.parent_id for d in devices}
    pt_device = {p.resource_id: p.device_id for p in points}

    def owner_space(rid: str, kind: int) -> str | None:
        if kind == RESOURCE_KIND_DEVICE:
            return dev_space.get(rid)
        if kind == RESOURCE_KIND_POINT:
            return dev_space.get(pt_device.get(rid, ""), None)
        return rid if kind == RESOURCE_KIND_SPACE else None

    # 汇总活动告警到所属空间并向上传播
    agg_cnt: dict[str, int] = defaultdict(int)
    agg_lvl: dict[str, int] = {}
    alarms = (
        await db.execute(
            select(Alarm.resource_id, Alarm.resource_kind, Alarm.level).where(
                Alarm.status.in_(_OPEN)
            )
        )
    ).all()
    for rid, kind, level in alarms:
        sid = owner_space(rid, kind)
        while sid and sid in space_by_id:
            agg_cnt[sid] += 1
            agg_lvl[sid] = min(agg_lvl.get(sid, 99), level)
            sid = space_by_id[sid].parent_id

    children_by_parent: dict[str | None, list[Space]] = defaultdict(list)
    for s in spaces:
        parent = s.parent_id if s.parent_id in space_by_id else None
        children_by_parent[parent].append(s)

    def build(node: Space) -> SpaceNode:
        m = meta.get(node.resource_id)
        return SpaceNode(
            resource_id=node.resource_id, name=node.name, parent_id=node.parent_id,
            space_type=node.space_type, alias=m.alias if m else None,
            active_alarms=agg_cnt.get(node.resource_id, 0),
            max_level=agg_lvl.get(node.resource_id),
            children=[build(c) for c in children_by_parent.get(node.resource_id, [])],
        )

    roots = [build(s) for s in children_by_parent.get(None, [])]
    return ok([r.model_dump() for r in roots])


@router.get("/spaces/{space_id}/children")
async def space_children(
    space_id: str,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    sub_spaces = (
        await db.execute(
            select(Space).where(Space.parent_id == space_id, Space.is_active.is_(True))
        )
    ).scalars().all()
    devices = (
        await db.execute(
            select(Device).where(Device.parent_id == space_id, Device.is_active.is_(True))
        )
    ).scalars().all()
    meta = await _meta_map(db)
    counts = await _alarm_counts(db)
    statuses = await _device_statuses([d.resource_id for d in devices])
    return ok({
        "spaces": [
            {"resource_id": s.resource_id, "name": s.name, "space_type": s.space_type,
             "alias": (m.alias if (m := meta.get(s.resource_id)) else None)}
            for s in sub_spaces
        ],
        "devices": [_device_dump(d, meta.get(d.resource_id), statuses.get(d.resource_id),
                                  counts.get(d.resource_id, (0, 0))[0]) for d in devices],
    })


def _device_dump(
    d: Device, meta: AssetMeta | None, status_val: int | None, alarms: int
) -> dict[str, Any]:
    mf = _meta_fields(meta)
    return DeviceOutput(
        resource_id=d.resource_id, name=d.name, device_type=d.device_type,
        parent_id=d.parent_id, location=d.location, is_active=d.is_active,
        alias=mf["alias"], group_name=mf["group_name"], status=status_val,
        active_alarms=alarms,
    ).model_dump()


# ---------------- 设备 ----------------
@router.get("/devices")
async def list_devices(
    space: str | None = Query(None),
    group: str | None = Query(None),
    tag: str | None = Query(None),
    keyword: str | None = Query(None),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    stmt = select(Device).where(Device.is_active.is_(True))
    if space:
        stmt = stmt.where(Device.parent_id == space)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(Device.name.ilike(like) | Device.resource_id.ilike(like))
    devices = (await db.execute(stmt.order_by(Device.name))).scalars().all()
    meta = await _meta_map(db)
    counts = await _alarm_counts(db)
    statuses = await _device_statuses([d.resource_id for d in devices])

    out = []
    for d in devices:
        m = meta.get(d.resource_id)
        if group and (m is None or m.group_name != group):
            continue
        if tag and (m is None or not m.tags or tag not in m.tags):
            continue
        out.append(
            _device_dump(d, m, statuses.get(d.resource_id), counts.get(d.resource_id, (0, 0))[0])
        )
    return ok(out)


@router.get("/devices/{device_id}")
async def device_detail(
    device_id: str,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    d = await db.get(Device, device_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "设备不存在")
    points = (
        await db.execute(
            select(Point).where(Point.device_id == device_id, Point.is_active.is_(True))
        )
    ).scalars().all()
    meta = await _meta_map(db)
    counts = await _alarm_counts(db)
    statuses = await _device_statuses([device_id])
    values = await _point_values([p.resource_id for p in points])

    base = _device_dump(
        d, meta.get(device_id), statuses.get(device_id), counts.get(device_id, (0, 0))[0]
    )
    detail = DeviceDetail(**base)
    detail.points = [
        _point_dump(p, meta.get(p.resource_id), values.get(p.resource_id, (None, None)),
                    counts.get(p.resource_id, (0, 0))[0])
        for p in points
    ]
    return ok(detail.model_dump())


# ---------------- 测点 ----------------
def _point_dump(
    p: Point, meta: AssetMeta | None, value: tuple[str | None, int | None], alarms: int
) -> PointOutput:
    mf = _meta_fields(meta)
    return PointOutput(
        resource_id=p.resource_id, name=p.name, device_id=p.device_id, spot_type=p.spot_type,
        unit=mf["custom_unit"] or p.unit, is_active=p.is_active, alias=mf["alias"],
        group_name=mf["group_name"], importance=mf["importance"],
        value=value[0], save_time=value[1], active_alarms=alarms,
    )


@router.get("/points")
async def list_points(
    device: str | None = Query(None),
    space: str | None = Query(None),
    group: str | None = Query(None),
    tag: str | None = Query(None),
    keyword: str | None = Query(None),
    importance: int | None = Query(None),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    stmt = select(Point).where(Point.is_active.is_(True))
    if device:
        stmt = stmt.where(Point.device_id == device)
    if space:
        dev_ids = (
            await db.execute(select(Device.resource_id).where(Device.parent_id == space))
        ).scalars().all()
        stmt = stmt.where(Point.device_id.in_(list(dev_ids) or [""]))
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(Point.name.ilike(like) | Point.resource_id.ilike(like))
    points = (await db.execute(stmt.order_by(Point.name).limit(500))).scalars().all()
    meta = await _meta_map(db)
    counts = await _alarm_counts(db)
    values = await _point_values([p.resource_id for p in points])

    out = []
    for p in points:
        m = meta.get(p.resource_id)
        if group and (m is None or m.group_name != group):
            continue
        if tag and (m is None or not m.tags or tag not in m.tags):
            continue
        if importance is not None and (m is None or m.importance != importance):
            continue
        out.append(
            _point_dump(p, m, values.get(p.resource_id, (None, None)),
                        counts.get(p.resource_id, (0, 0))[0]).model_dump()
        )
    return ok(out)


@router.get("/points/{point_id}")
async def point_detail(
    point_id: str,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    p = await db.get(Point, point_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "测点不存在")
    meta = await db.get(AssetMeta, point_id)
    counts = await _alarm_counts(db)
    values = await _point_values([point_id])
    rules = (
        await db.execute(select(AlarmRule).where(AlarmRule.point_id == point_id))
    ).scalars().all()

    base = _point_dump(p, meta, values.get(point_id, (None, None)), counts.get(point_id, (0, 0))[0])
    detail = PointDetail(**base.model_dump())
    detail.mapper = p.mapper
    detail.access = p.access
    detail.meta = (
        AssetMetaOutput.model_validate(meta, from_attributes=True) if meta else None
    )
    detail.rules = [
        RuleBrief(
            id=r.id, name=r.name, operator=r.operator, operand=r.operand,
            operand_min=r.operand_min, operand_max=r.operand_max, cond_type=r.cond_type,
            level=r.level, enabled=r.enabled,
        )
        for r in rules
    ]
    return ok(detail.model_dump())


# ---------------- 元数据增强 ----------------
@router.get("/assets/{resource_id}/meta")
async def get_meta(
    resource_id: str,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    m = await db.get(AssetMeta, resource_id)
    if m is None:
        return ok(None)
    return ok(AssetMetaOutput.model_validate(m, from_attributes=True).model_dump())


@router.put("/assets/{resource_id}/meta")
async def put_meta(
    resource_id: str,
    body: AssetMetaInput,
    _: User = Depends(require_role(Role.OPERATOR)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    # 推断资产类型（测点/设备/空间）
    kind = RESOURCE_KIND_POINT
    if await db.get(Point, resource_id) is not None:
        kind = RESOURCE_KIND_POINT
    elif await db.get(Device, resource_id) is not None:
        kind = RESOURCE_KIND_DEVICE
    elif await db.get(Space, resource_id) is not None:
        kind = RESOURCE_KIND_SPACE

    values = {"resource_id": resource_id, "asset_kind": kind,
              **body.model_dump(), "updated_at": datetime.now(UTC)}
    stmt = pg_insert(AssetMeta).values(**values)
    update_cols = {k for k in body.model_dump()} | {"asset_kind", "updated_at"}
    stmt = stmt.on_conflict_do_update(
        index_elements=["resource_id"],
        set_={c: stmt.excluded[c] for c in update_cols},
    )
    await db.execute(stmt)
    await db.commit()
    m = await db.get(AssetMeta, resource_id)
    return ok(AssetMetaOutput.model_validate(m, from_attributes=True).model_dump())
