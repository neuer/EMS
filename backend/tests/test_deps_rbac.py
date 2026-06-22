"""RBAC 守卫强制执行测试（红线 #9/#11：访问控制在后端执行）。

审查 H3：此前仅测纯函数 role_satisfies（判定逻辑），而 require_role/get_current_user 的
强制执行（401/403）零覆盖——比较方向写反或漏判 enabled=False 会静默放行而测试全绿。
这里直接调用守卫，用桩 db/user，离线确定性、无需拉起 app。
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import jwt
import pytest
from app.api.deps import get_current_user, require_role
from app.core.config import settings
from app.core.security import Role, create_access_token
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession


class _Result:
    def __init__(self, user: object | None) -> None:
        self._user = user

    def scalar_one_or_none(self) -> object | None:
        return self._user


class _FakeDB:
    """桩 DB：execute 恒返回预置用户（或 None）。"""

    def __init__(self, user: object | None) -> None:
        self._user = user

    async def execute(self, _stmt: Any) -> _Result:
        return _Result(self._user)


def _user(*, role: str = "operator", enabled: bool = True, username: str = "u") -> Any:
    return SimpleNamespace(role=role, enabled=enabled, username=username)


# ---- require_role：角色等级强制 ----
@pytest.mark.parametrize(
    ("actual", "minimum", "ok"),
    [
        ("admin", Role.ADMIN, True),
        ("operator", Role.OPERATOR, True),
        ("readonly", Role.READONLY, True),
        ("operator", Role.ADMIN, False),  # operator 不足 admin
        ("readonly", Role.OPERATOR, False),  # readonly 不足 operator
        ("admin", Role.OPERATOR, True),  # 高于要求亦通过
    ],
)
async def test_require_role_enforces_minimum(actual: str, minimum: str, ok: bool) -> None:
    guard = require_role(minimum)
    current = _user(role=actual)
    if ok:
        assert await guard(cast("Any", current)) is current
    else:
        with pytest.raises(HTTPException) as ei:
            await guard(cast("Any", current))
        assert ei.value.status_code == 403


# ---- get_current_user：401 各分支 ----
async def test_missing_authorization_header() -> None:
    with pytest.raises(HTTPException) as ei:
        await get_current_user(authorization=None, db=cast(AsyncSession, _FakeDB(None)))
    assert ei.value.status_code == 401


async def test_non_bearer_scheme() -> None:
    with pytest.raises(HTTPException) as ei:
        await get_current_user(authorization="Basic abc", db=cast(AsyncSession, _FakeDB(None)))
    assert ei.value.status_code == 401


async def test_invalid_token() -> None:
    with pytest.raises(HTTPException) as ei:
        await get_current_user(
            authorization="Bearer not-a-real-jwt", db=cast(AsyncSession, _FakeDB(None))
        )
    assert ei.value.status_code == 401


async def test_token_subject_not_str() -> None:
    """sub 非字符串（畸形/伪造令牌）→ 401。"""
    bad = jwt.encode(
        {"sub": 123, "role": "admin", "exp": datetime.now(UTC) + timedelta(minutes=5)},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    with pytest.raises(HTTPException) as ei:
        await get_current_user(authorization=f"Bearer {bad}", db=cast(AsyncSession, _FakeDB(None)))
    assert ei.value.status_code == 401


async def test_unknown_user() -> None:
    token = create_access_token("ghost", "operator")
    with pytest.raises(HTTPException) as ei:
        await get_current_user(
            authorization=f"Bearer {token}", db=cast(AsyncSession, _FakeDB(None))
        )
    assert ei.value.status_code == 401


async def test_disabled_user_rejected() -> None:
    """已禁用账户即使持有效令牌也必须 401（红线：降级/禁用即时生效）。"""
    token = create_access_token("alice", "operator")
    disabled = _user(enabled=False, username="alice")
    with pytest.raises(HTTPException) as ei:
        await get_current_user(
            authorization=f"Bearer {token}", db=cast(AsyncSession, _FakeDB(disabled))
        )
    assert ei.value.status_code == 401


async def test_valid_user_returned() -> None:
    token = create_access_token("alice", "operator")
    ok = _user(enabled=True, username="alice")
    got = await get_current_user(
        authorization=f"Bearer {token}", db=cast(AsyncSession, _FakeDB(ok))
    )
    assert got is ok
