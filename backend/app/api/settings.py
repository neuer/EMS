"""EMS 设置与连接状态路由。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.core.constants import REDIS_EMS_CONN, ConnState
from app.core.crypto import encrypt
from app.core.db import get_db
from app.core.redis import redis_client
from app.core.security import Role
from app.ems.connection import restart_connection_manager
from app.models.system import EmsConfig
from app.models.user import User
from app.schemas.common import ok
from app.schemas.settings import EmsConfigOutput, EmsConfigUpdate, EmsStatusOutput

router = APIRouter(prefix="/settings", tags=["系统设置"])


@router.get("/ems")
async def get_ems_config(
    _: User = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    cfg = await db.get(EmsConfig, 1)
    if cfg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "EMS 配置不存在")
    return ok(
        EmsConfigOutput(
            base_url=cfg.base_url,
            username=cfg.username,
            password_masked="********",
            recv_ip=cfg.recv_ip,
            recv_port=cfg.recv_port,
            version_str=cfg.version_str,
            sync_interval_s=cfg.sync_interval_s,
            subscribe_data=cfg.subscribe_data,
            subscribe_alarm=cfg.subscribe_alarm,
            deadband_enabled=cfg.deadband_enabled,
        ).model_dump()
    )


@router.put("/ems")
async def update_ems_config(
    body: EmsConfigUpdate,
    _: User = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    cfg = await db.get(EmsConfig, 1)
    if cfg is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "EMS 配置不存在")

    data = body.model_dump(exclude_none=True)
    password = data.pop("password", None)
    for key, value in data.items():
        setattr(cfg, key, value)
    if password:
        cfg.password_enc = encrypt(password)  # 红线：凭据加密入库
    await db.commit()

    # 配置变更后重启连接管理使其生效
    await restart_connection_manager()
    return ok({"restarted": True})


@router.get("/ems/status")
async def get_ems_status(
    _: User = Depends(require_role(Role.OPERATOR)),
) -> dict[str, object]:
    raw = await redis_client.hgetall(REDIS_EMS_CONN)

    def _int(key: str) -> int | None:
        v = raw.get(key)
        return int(v) if v not in (None, "") else None

    state_raw = raw.get("state")
    state = ConnState(state_raw) if state_raw in set(ConnState) else ConnState.OFFLINE
    return ok(
        EmsStatusOutput(
            state=state,
            last_heart=_int("last_heart"),
            last_push=_int("last_push"),
            token_ok=raw.get("token_ok") == "1",
            reconnects=_int("reconnects") or 0,
        ).model_dump()
    )
