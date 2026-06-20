"""用户与角色管理输入/输出模型（管理员）。

红线：密码仅写入（bcrypt 哈希），任何输出都不回传密码或哈希。
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

RoleLiteral = Literal["admin", "operator", "readonly"]


class UserCreateInput(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=6, max_length=128)
    role: RoleLiteral
    display_name: str | None = Field(None, max_length=64)
    enabled: bool = True


class UserUpdateInput(BaseModel):
    """更新可改字段（不含密码，密码走专用重置接口）。"""

    role: RoleLiteral | None = None
    display_name: str | None = Field(None, max_length=64)
    enabled: bool | None = None


class PasswordResetInput(BaseModel):
    password: str = Field(..., min_length=6, max_length=128)


class UserAdminOutput(BaseModel):
    id: int
    username: str
    role: str
    display_name: str | None = None
    enabled: bool
    created_at: datetime
