"""接收人更新联系方式再校验测试（审查 M3，离线确定性）。

update_recipient 部分更新若清空唯一联系方式，必须 422，避免不可触达的接收人被静默跳过。
用桩 db 与 recipient，避免依赖含 PG 类型的 notify 模型与真实 DB。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest
from app.api.notify import update_recipient
from app.models.user import User
from app.schemas.notify import RecipientUpdate, has_contact
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

_USER = cast(User, SimpleNamespace(role="admin"))


class _DB:
    def __init__(self, recipient: object) -> None:
        self._r = recipient
        self.committed = False

    async def get(self, _model: Any, _id: Any) -> object:
        return self._r

    async def commit(self) -> None:
        self.committed = True

    async def refresh(self, _obj: Any) -> None:
        return None


def _recipient(**kw: Any) -> Any:
    base = {
        "id": 1, "name": "oncall", "phone": "138", "email": None,
        "dingtalk_id": None, "wecom_id": None, "enabled": True,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_has_contact() -> None:
    assert has_contact("138", None, None, None) is True
    assert has_contact(None, None, None, None) is False
    assert has_contact("", "", None, None) is False  # 空串视为无联系方式


async def test_clearing_only_contact_rejected() -> None:
    r = _recipient(phone="138")
    db = _DB(r)
    with pytest.raises(HTTPException) as ei:
        await update_recipient(1, RecipientUpdate(phone=""), _USER, cast(AsyncSession, db))
    assert ei.value.status_code == 422
    assert db.committed is False  # 校验失败不提交


async def test_update_keeping_contact_ok() -> None:
    r = _recipient(phone="138")
    db = _DB(r)
    await update_recipient(1, RecipientUpdate(name="新名"), _USER, cast(AsyncSession, db))
    assert db.committed is True
    assert r.name == "新名"
    assert r.phone == "138"  # 原联系方式保留


async def test_switching_contact_ok() -> None:
    """清空手机号但同时提供邮箱 → 仍可触达，允许。"""
    r = _recipient(phone="138", email=None)
    db = _DB(r)
    await update_recipient(
        1, RecipientUpdate(phone="", email="a@b.com"), _USER, cast(AsyncSession, db)
    )
    assert db.committed is True
    assert r.email == "a@b.com"
