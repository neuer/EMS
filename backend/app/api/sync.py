"""配置同步路由：手动立即同步、同步日志。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.core.db import get_db
from app.core.security import Role
from app.ems.connection import get_manager
from app.ems.protocol import EmsError
from app.models.system import SyncLog
from app.models.user import User
from app.schemas.common import ok
from app.schemas.sync import SyncLogOutput, SyncResultOutput

router = APIRouter(tags=["资产同步"])


@router.post("/sync/config")
async def trigger_config_sync(
    _: User = Depends(require_role(Role.ADMIN)),
) -> dict[str, object]:
    manager = get_manager()
    if manager is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "连接管理未启动")
    try:
        result = await manager.manual_sync()
    except EmsError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"同步失败: {exc.msg}") from exc
    return ok(
        SyncResultOutput(
            added=result.added,
            changed=result.changed,
            inactivated=result.inactivated,
            spaces=result.spaces,
            devices=result.devices,
            points=result.points,
        ).model_dump()
    )


@router.get("/sync/log")
async def list_sync_log(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
) -> dict[str, object]:
    rows = (
        await db.execute(
            select(SyncLog).order_by(SyncLog.started_at.desc()).limit(min(limit, 100))
        )
    ).scalars().all()
    return ok(
        [
            SyncLogOutput.model_validate(r, from_attributes=True).model_dump(mode="json")
            for r in rows
        ]
    )
