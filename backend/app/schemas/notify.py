"""通知配置输入/输出模型。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

ChannelType = Literal["sms", "email", "dingtalk", "wecom", "voice", "webhook"]


class ChannelInput(BaseModel):
    type: ChannelType
    name: str
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class ChannelUpdate(BaseModel):
    name: str | None = None
    config: dict[str, Any] | None = None
    enabled: bool | None = None


class ChannelOutput(BaseModel):
    id: int
    type: str
    name: str
    config: dict[str, Any]  # 敏感字段已脱敏
    enabled: bool


class RecipientInput(BaseModel):
    name: str
    phone: str | None = None
    email: str | None = None
    dingtalk_id: str | None = None
    wecom_id: str | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def _require_one_contact(self) -> RecipientInput:
        # 审查 M4：避免创建四项联系方式全空、无法触达的接收人（通知时被静默跳过）
        if not any([self.phone, self.email, self.dingtalk_id, self.wecom_id]):
            raise ValueError("接收人至少需要一种联系方式（phone/email/dingtalk_id/wecom_id）")
        return self


class RecipientUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    dingtalk_id: str | None = None
    wecom_id: str | None = None
    enabled: bool | None = None


class RecipientOutput(BaseModel):
    id: int
    name: str
    phone: str | None = None
    email: str | None = None
    dingtalk_id: str | None = None
    wecom_id: str | None = None
    enabled: bool


class GroupInput(BaseModel):
    name: str
    member_ids: list[int] = Field(default_factory=list)


class GroupOutput(BaseModel):
    id: int
    name: str
    member_ids: list[int] = Field(default_factory=list)


class RouteInput(BaseModel):
    level: int = Field(..., ge=1, le=5)
    channel_ids: list[int] = Field(default_factory=list)
    group_ids: list[int] = Field(default_factory=list)
    notify_on_recover: bool = True
    enabled: bool = True


class RouteUpdate(BaseModel):
    level: int | None = Field(None, ge=1, le=5)
    channel_ids: list[int] | None = None
    group_ids: list[int] | None = None
    notify_on_recover: bool | None = None
    enabled: bool | None = None


class RouteOutput(BaseModel):
    id: int
    level: int
    channel_ids: list[int]
    group_ids: list[int]
    notify_on_recover: bool
    enabled: bool


class NotifyLogOutput(BaseModel):
    id: int
    alarm_id: int | None = None
    channel_id: int | None = None
    recipient: str | None = None
    trigger: str | None = None
    status: str
    error: str | None = None
    retry_count: int
    sent_at: datetime
