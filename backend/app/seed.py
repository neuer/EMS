"""首次启动数据初始化：创建默认管理员（幂等）。"""
from __future__ import annotations

from sqlalchemy import select

from app.core.config import settings
from app.core.crypto import encrypt
from app.core.db import AsyncSessionLocal
from app.core.logging import get_logger
from app.core.security import Role, hash_password
from app.models.system import EmsConfig
from app.models.user import User

logger = get_logger("seed")


async def seed_default_admin() -> None:
    """若不存在任何用户，则创建默认管理员。"""
    async with AsyncSessionLocal() as db:
        exists = (await db.execute(select(User.id).limit(1))).first()
        if exists is not None:
            return
        admin = User(
            username=settings.default_admin_username,
            password_hash=hash_password(settings.default_admin_password),
            role=Role.ADMIN,
            display_name="系统管理员",
            enabled=True,
        )
        db.add(admin)
        await db.commit()
        logger.info(
            "已创建默认管理员",
            extra={"extra_fields": {"username": settings.default_admin_username}},
        )


async def seed_ems_config() -> None:
    """若不存在 EMS 配置，则用 .env 默认值创建（密码加密入库）。"""
    async with AsyncSessionLocal() as db:
        cfg = await db.get(EmsConfig, 1)
        if cfg is not None:
            return
        cfg = EmsConfig(
            id=1,
            base_url=settings.ems_base_url,
            username=settings.ems_username,
            password_enc=encrypt(settings.ems_password),
            recv_ip=settings.ems_recv_ip,
            recv_port=settings.ems_recv_port,
            version_str=settings.ems_version,
        )
        db.add(cfg)
        await db.commit()
        logger.info(
            "已创建默认 EMS 配置",
            extra={"extra_fields": {"base_url": settings.ems_base_url}},
        )
