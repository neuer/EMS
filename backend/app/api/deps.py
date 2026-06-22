"""API 依赖：当前用户解析与 RBAC 角色守卫。

红线：访问控制在后端执行；前端仅做显隐。
"""
from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import IDEMPOTENCY_TTL_S, REDIS_IDEMPOTENCY
from app.core.db import get_db
from app.core.redis import redis_client
from app.core.security import decode_access_token, role_satisfies
from app.models.user import User


async def require_idempotency(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> None:
    """写操作幂等守卫（红线 §18）：携带 Idempotency-Key 时用 Redis SETNX 预留键，
    短窗口内重复键直接 409，避免重复执行副作用（如重复触发报表邮件、重复建记录）。
    预留式去重，非完整响应重放；未携带 Key 时放行（向后兼容）。
    """
    if not idempotency_key:
        return
    reserved = await redis_client.set(
        REDIS_IDEMPOTENCY.format(key=idempotency_key), "1", nx=True, ex=IDEMPOTENCY_TTL_S
    )
    if not reserved:
        raise HTTPException(status.HTTP_409_CONFLICT, "重复请求（Idempotency-Key 已使用）")


async def get_current_user(
    authorization: Annotated[str | None, Header()] = None,
    db: AsyncSession = Depends(get_db),
) -> User:
    """从 Bearer Token 解析当前用户。"""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "缺少或非法的 Authorization 头")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_access_token(token)
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "令牌无效或已过期") from exc

    username = payload.get("sub")
    if not isinstance(username, str):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "令牌缺少主体")

    user = (
        await db.execute(select(User).where(User.username == username))
    ).scalar_one_or_none()
    if user is None or not user.enabled:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在或已禁用")
    return user


def require_role(
    minimum: str,
) -> Callable[[User], Coroutine[None, None, User]]:
    """生成「最低角色」守卫依赖，例如 require_role(Role.OPERATOR)。"""

    async def _guard(current: User = Depends(get_current_user)) -> User:
        if not role_satisfies(current.role, minimum):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "权限不足")
        return current

    return _guard
