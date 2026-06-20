"""EMS 设置相关输入/输出模型。密码读时脱敏、写时加密。"""
from __future__ import annotations

from pydantic import BaseModel

from app.core.constants import ConnState


class EmsConfigOutput(BaseModel):
    base_url: str
    username: str
    password_masked: str  # 脱敏：固定返回掩码，不回传明文
    recv_ip: str
    recv_port: str
    version_str: str
    sync_interval_s: int
    subscribe_data: bool
    subscribe_alarm: bool
    deadband_enabled: bool


class EmsConfigUpdate(BaseModel):
    base_url: str | None = None
    username: str | None = None
    password: str | None = None  # 提供则加密更新；不提供则保留原值
    recv_ip: str | None = None
    recv_port: str | None = None
    version_str: str | None = None
    sync_interval_s: int | None = None
    subscribe_data: bool | None = None
    subscribe_alarm: bool | None = None
    deadband_enabled: bool | None = None


class EmsStatusOutput(BaseModel):
    state: ConnState  # online|offline|connecting
    last_heart: int | None = None
    last_push: int | None = None
    token_ok: bool = False
    reconnects: int = 0
