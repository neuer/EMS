"""认证相关输入/输出模型。"""
from __future__ import annotations

from pydantic import BaseModel


class LoginInput(BaseModel):
    username: str
    password: str


class TokenOutput(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    username: str


class UserOutput(BaseModel):
    id: int
    username: str
    role: str
    display_name: str | None = None
    enabled: bool
