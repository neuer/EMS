"""配置同步：全量拉取空间/设备/测点 → upsert → 增量比对（新增/变更/inactive）。

红线 #8：EMS 同步对象只读镜像；别名等增强写 asset_meta（本 Sprint 不动）。
失效对象置 is_active=false，不物理删除，保留历史关联。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import AsyncSessionLocal
from app.core.logging import get_logger
from app.ems.client import EmsClient
from app.models.asset import Device, Point, Space
from app.models.system import SyncLog

logger = get_logger("sync")


@dataclass
class SyncResult:
    added: int = 0
    changed: int = 0
    inactivated: int = 0
    spaces: int = 0
    devices: int = 0
    points: int = 0

    def merge(self, other: SyncResult) -> None:
        self.added += other.added
        self.changed += other.changed
        self.inactivated += other.inactivated


def _to_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _map_space(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "resource_id": raw["resource_id"],
        "name": raw.get("name") or raw["resource_id"],
        "parent_id": raw.get("parent_id") or None,
        "location": raw.get("location"),
        "space_type": _to_int(raw.get("space_type")),
    }


def _map_device(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "resource_id": raw["resource_id"],
        "name": raw.get("name") or raw["resource_id"],
        "device_type": raw.get("device_type"),
        "parent_id": raw.get("parent_id") or None,
        "location": raw.get("location"),
        "link": raw.get("link"),
    }


def _map_point(raw: dict[str, Any], device_id: str) -> dict[str, Any]:
    event_rules = raw.get("event_rules")
    if isinstance(event_rules, list):
        raw_rules = "\n".join(str(r) for r in event_rules)
    else:
        raw_rules = str(event_rules) if event_rules else None
    return {
        "resource_id": raw["resource_id"],
        "name": raw.get("name") or raw["resource_id"],
        "device_id": device_id,
        "spot_type": _to_int(raw.get("spot_type")),
        "unit": raw.get("unit"),
        "mapper": raw.get("mapper"),
        "access": raw.get("access"),
        "raw_filter": raw.get("filter"),
        "raw_event_rules": raw_rules,
    }


async def _upsert(
    db: AsyncSession, model: type, rows: list[dict[str, Any]], incoming_ids: set[str]
) -> SyncResult:
    """对一类对象做 upsert + 失效标记，并统计新增/变更/失效。"""
    result = SyncResult()
    if rows:
        # 现存 id（用于区分新增/变更）
        existing = set(
            (await db.execute(select(model.resource_id))).scalars().all()
        )
        now = datetime.now(UTC)
        update_cols = {k for k in rows[0] if k != "resource_id"}
        for row in rows:
            row["is_active"] = True
            row["synced_at"] = now
            stmt = pg_insert(model.__table__).values(**row)
            stmt = stmt.on_conflict_do_update(
                index_elements=["resource_id"],
                set_={c: stmt.excluded[c] for c in (update_cols | {"is_active", "synced_at"})},
            )
            await db.execute(stmt)
            if row["resource_id"] in existing:
                result.changed += 1
            else:
                result.added += 1

    # 库里 active 集合
    stale = (
        await db.execute(
            select(model.resource_id).where(model.is_active.is_(True))
        )
    ).scalars().all()
    # 审查 I5：本次全量为空（疑似 EMS 瞬时故障返回 []）且库内仍有 active → 跳过失活，
    # 避免把整棵资产树一次性置 inactive（前端整体消失、规则因测点失活而失效）。
    if not incoming_ids and stale:
        logger.warning(
            "同步本次全量为空，跳过失活以防误置（疑似上游瞬时故障）",
            extra={"extra_fields": {"model": model.__name__, "active": len(stale)}},
        )
        return result
    to_inactivate = [rid for rid in stale if rid not in incoming_ids]
    if to_inactivate:
        await db.execute(
            update(model)
            .where(model.resource_id.in_(to_inactivate))
            .values(is_active=False)
        )
        result.inactivated += len(to_inactivate)
    return result


async def run_config_sync(client: EmsClient, batch_size: int = 50) -> SyncResult:
    """执行一次全量配置同步，写 sync_log，返回统计。"""
    total = SyncResult()
    async with AsyncSessionLocal() as db:
        log = SyncLog(kind="config")
        db.add(log)
        await db.flush()
        try:
            # 1) 空间
            spaces_raw = await client.get_space_list()
            space_rows = [_map_space(s) for s in spaces_raw if s.get("resource_id")]
            space_ids = {r["resource_id"] for r in space_rows}
            r = await _upsert(db, Space, space_rows, space_ids)
            total.merge(r)
            total.spaces = len(space_rows)

            # 2) 设备
            devices_raw = await client.get_device_list()
            device_rows = [_map_device(d) for d in devices_raw if d.get("resource_id")]
            device_ids = {r["resource_id"] for r in device_rows}
            r = await _upsert(db, Device, device_rows, device_ids)
            total.merge(r)
            total.devices = len(device_rows)

            # 3) 测点：按设备分批 get_spot_list
            all_device_ids = [r["resource_id"] for r in device_rows]
            point_rows: list[dict[str, Any]] = []
            for i in range(0, len(all_device_ids), batch_size):
                batch = all_device_ids[i : i + batch_size]
                spot_devices = await client.get_spot_list(batch)
                for dev in spot_devices:
                    dev_id = dev.get("resource_id")
                    if not dev_id:  # 设备缺 resource_id 时跳过其测点
                        continue
                    for p in dev.get("points") or []:
                        if p.get("resource_id"):
                            point_rows.append(_map_point(p, dev_id))
            point_ids = {r["resource_id"] for r in point_rows}
            r = await _upsert(db, Point, point_rows, point_ids)
            total.merge(r)
            total.points = len(point_rows)

            log.finished_at = datetime.now(UTC)
            log.added = total.added
            log.changed = total.changed
            log.inactivated = total.inactivated
            log.success = True
            log.detail = (
                f"空间={total.spaces} 设备={total.devices} 测点={total.points}"
            )
            await db.commit()
            logger.info(
                "配置同步完成",
                extra={"extra_fields": {
                    "added": total.added, "changed": total.changed,
                    "inactivated": total.inactivated,
                    "spaces": total.spaces, "devices": total.devices, "points": total.points,
                }},
            )
        except Exception as exc:
            log.finished_at = datetime.now(UTC)
            log.success = False
            log.detail = f"同步失败: {exc}"
            await db.commit()
            logger.error("配置同步失败", extra={"extra_fields": {"error": str(exc)}})
            raise
    return total
