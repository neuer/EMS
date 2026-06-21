"""用户与角色管理 API（A0，仅管理员）。

红线对应：
- 访问控制在后端执行（require_role(ADMIN)）；前端仅显隐。
- 密码 bcrypt 哈希入库；任何响应不回传密码或哈希。
- 不变量守卫为纯函数，便于离线确定性单测（见 tests/test_user_rules.py）。
"""
from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.core.constants import REDIS_USER_ADMIN_LOCK
from app.core.db import get_db
from app.core.redis import redis_client, release_lock_if_owner
from app.core.security import Role, hash_password
from app.models.user import User
from app.schemas.common import ok
from app.schemas.user import (
    PasswordResetInput,
    UserAdminOutput,
    UserCreateInput,
    UserUpdateInput,
)

router = APIRouter(prefix="/users", tags=["用户管理"])

_ADMIN_LOCK_TTL = 10  # 秒，兜底防异常未释放


@asynccontextmanager
async def _admin_guard_lock() -> AsyncIterator[None]:
    """串行化「保留至少一个管理员」守卫的读-检查-提交，防 TOCTOU 并发自锁（审查 C3）。

    用唯一 token 持锁、比对释放；获取失败短暂重试，超时返回 409 让客户端重试。
    """
    token = uuid.uuid4().hex
    for _ in range(40):  # 最多约 2s
        if await redis_client.set(REDIS_USER_ADMIN_LOCK, token, nx=True, ex=_ADMIN_LOCK_TTL):
            break
        await asyncio.sleep(0.05)
    else:
        raise HTTPException(status.HTTP_409_CONFLICT, "用户管理操作并发冲突，请重试")
    try:
        yield
    finally:
        await release_lock_if_owner(REDIS_USER_ADMIN_LOCK, token)


# ---------------- 纯函数不变量守卫（可离线单测） ----------------
def will_keep_an_admin(
    enabled_admin_usernames: set[str],
    target_username: str,
    *,
    new_role: str | None = None,
    new_enabled: bool | None = None,
    delete: bool = False,
) -> bool:
    """模拟对 target 的变更后，系统是否仍保留至少一个「启用的管理员」。

    用于防止管理员把唯一的管理员账户删除/降级/禁用导致系统失去管理入口。
    """
    admins = set(enabled_admin_usernames)
    if delete:
        admins.discard(target_username)
        return len(admins) > 0
    # 降级（非 admin）或禁用都会使其失去管理资格
    loses_admin = (new_role is not None and new_role != Role.ADMIN) or (new_enabled is False)
    if loses_admin:
        admins.discard(target_username)
    return len(admins) > 0


def _dump(u: User) -> dict[str, object]:
    return UserAdminOutput.model_validate(u, from_attributes=True).model_dump(mode="json")


async def _enabled_admin_usernames(db: AsyncSession) -> set[str]:
    rows = (
        await db.execute(
            select(User.username).where(User.role == Role.ADMIN, User.enabled.is_(True))
        )
    ).scalars().all()
    return set(rows)


@router.get("")
async def list_users(
    _: User = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    rows = (await db.execute(select(User).order_by(User.id))).scalars().all()
    return ok([_dump(u) for u in rows])


@router.post("")
async def create_user(
    body: UserCreateInput,
    _: User = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    exists = (
        await db.execute(select(User.id).where(User.username == body.username))
    ).first()
    if exists is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名已存在")
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role=body.role,
        display_name=body.display_name,
        enabled=body.enabled,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return ok(_dump(user))


@router.put("/{user_id}")
async def update_user(
    user_id: int,
    body: UserUpdateInput,
    current: User = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")

    # 不可禁用/降级自己（避免误操作自锁）
    if user.id == current.id and (
        body.enabled is False or (body.role is not None and body.role != current.role)
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不可禁用或降级当前登录账户")

    # 审查 C3：守卫与提交在分布式锁内串行，防并发降级/禁用绕过「至少一个管理员」不变量
    async with _admin_guard_lock():
        if user.role == Role.ADMIN and not will_keep_an_admin(
            await _enabled_admin_usernames(db),
            user.username,
            new_role=body.role,
            new_enabled=body.enabled,
        ):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "必须至少保留一个启用的管理员")

        data = body.model_dump(exclude_unset=True)
        for key, value in data.items():
            setattr(user, key, value)
        await db.commit()
    await db.refresh(user)
    return ok(_dump(user))


@router.post("/{user_id}/reset-password")
async def reset_password(
    user_id: int,
    body: PasswordResetInput,
    _: User = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    user.password_hash = hash_password(body.password)
    await db.commit()
    return ok({"reset": user_id})


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    current: User = Depends(require_role(Role.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    if user.id == current.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不可删除当前登录账户")
    # 审查 C3：守卫与删除在分布式锁内串行，防并发删除绕过「至少一个管理员」不变量
    async with _admin_guard_lock():
        if user.role == Role.ADMIN and not will_keep_an_admin(
            await _enabled_admin_usernames(db), user.username, delete=True
        ):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "必须至少保留一个启用的管理员")
        await db.delete(user)
        await db.commit()
    return ok({"deleted": user_id})
