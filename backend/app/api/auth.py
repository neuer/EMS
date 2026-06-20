"""认证路由：登录、当前用户。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.db import get_db
from app.core.security import create_access_token, verify_password
from app.models.user import User
from app.schemas.auth import LoginInput, TokenOutput, UserOutput
from app.schemas.common import ok

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/login")
async def login(body: LoginInput, db: AsyncSession = Depends(get_db)) -> dict[str, object]:
    user = (
        await db.execute(select(User).where(User.username == body.username))
    ).scalar_one_or_none()
    if user is None or not user.enabled or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    token = create_access_token(subject=user.username, role=user.role)
    return ok(
        TokenOutput(
            access_token=token, role=user.role, username=user.username
        ).model_dump()
    )


@router.get("/me")
async def me(current: User = Depends(get_current_user)) -> dict[str, object]:
    return ok(
        UserOutput(
            id=current.id,
            username=current.username,
            role=current.role,
            display_name=current.display_name,
            enabled=current.enabled,
        ).model_dump()
    )
