"""通知配置输入/输出模型。

审查 H2：渠道 config 此前为 `dict[str, Any]`（同踩「禁 typing.Any」与「凭据脱敏靠运行时」两条
红线）。改为按 ChannelType 的判别联合（discriminated union）——Input 强制各渠道必填结构字段，
Output 通过类型化的 *Out 模型承载已脱敏值，消除 Any 并使脱敏成为类型边界的一部分。
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

ChannelType = Literal["sms", "email", "dingtalk", "wecom", "voice", "webhook"]


# ---------------- 渠道 config 判别联合 ----------------
# 各渠道 config 的结构化模型。敏感字段（secret/token/smtp_password 等）为明文入参，
# 由 config_crypto.encrypt_config 在落库前加密；读出时 mask_config 脱敏。
# `type` 为判别字段，序列化时排除（exclude=True），避免污染存储 config 与对外输出。
class _ChannelConfigBase(BaseModel):
    # extra=ignore：前端为自由 JSON 编辑器，容忍管理员附加的额外键，避免误伤
    model_config = ConfigDict(extra="ignore")


class SmsConfig(_ChannelConfigBase):
    type: Literal["sms"] = Field("sms", exclude=True)
    gateway_url: str
    sign: str | None = None
    account: str | None = None
    secret: str | None = None


class EmailConfig(_ChannelConfigBase):
    type: Literal["email"] = Field("email", exclude=True)
    smtp_host: str
    smtp_port: int = 25
    username: str | None = None
    from_addr: str | None = None
    use_tls: bool = False
    smtp_password: str | None = None


class DingtalkConfig(_ChannelConfigBase):
    type: Literal["dingtalk"] = Field("dingtalk", exclude=True)
    webhook_url: str
    secret: str | None = None


class WecomConfig(_ChannelConfigBase):
    type: Literal["wecom"] = Field("wecom", exclude=True)
    webhook_url: str
    secret: str | None = None


class VoiceConfig(_ChannelConfigBase):
    type: Literal["voice"] = Field("voice", exclude=True)
    gateway_url: str
    secret: str | None = None


class WebhookConfig(_ChannelConfigBase):
    type: Literal["webhook"] = Field("webhook", exclude=True)
    url: str
    headers: dict[str, str] | None = None
    token: str | None = None


ChannelConfig = Annotated[
    SmsConfig | EmailConfig | DingtalkConfig | WecomConfig | VoiceConfig | WebhookConfig,
    Field(discriminator="type"),
]


def _inject_discriminator(data: Any) -> Any:
    """把外层 type 注入 config，使判别联合无需客户端在 config 内重复 type（审查 H2）。"""
    if isinstance(data, dict):
        cfg = data.get("config")
        typ = data.get("type")
        if isinstance(cfg, dict) and typ is not None and "type" not in cfg:
            return {**data, "config": {**cfg, "type": typ}}
    return data


class ChannelInput(BaseModel):
    type: ChannelType
    name: str
    config: ChannelConfig
    enabled: bool = True

    @model_validator(mode="before")
    @classmethod
    def _prepare(cls, data: Any) -> Any:
        return _inject_discriminator(data)

    def config_for_storage(self) -> dict[str, object]:
        """转存储用 dict（判别字段 type 已 exclude），敏感字段为明文供 encrypt_config 加密。"""
        return self.config.model_dump()


class ChannelUpdate(BaseModel):
    # 部分更新：config 保持松散（管理员可只改部分键），由 apply_config_update 合并；
    # 用 dict[str, object] 而非 Any 仍满足「禁 typing.Any」。
    name: str | None = None
    config: dict[str, object] | None = None
    enabled: bool | None = None


# ---- Output：类型化的已脱敏 config（secret 字段为掩码串或 None，绝不含明文/密文）----
class SmsConfigOut(_ChannelConfigBase):
    type: Literal["sms"] = Field("sms", exclude=True)
    gateway_url: str | None = None
    sign: str | None = None
    account: str | None = None
    secret: str | None = None


class EmailConfigOut(_ChannelConfigBase):
    type: Literal["email"] = Field("email", exclude=True)
    smtp_host: str | None = None
    smtp_port: int | None = None
    username: str | None = None
    from_addr: str | None = None
    use_tls: bool | None = None
    smtp_password: str | None = None


class DingtalkConfigOut(_ChannelConfigBase):
    type: Literal["dingtalk"] = Field("dingtalk", exclude=True)
    webhook_url: str | None = None
    secret: str | None = None


class WecomConfigOut(_ChannelConfigBase):
    type: Literal["wecom"] = Field("wecom", exclude=True)
    webhook_url: str | None = None
    secret: str | None = None


class VoiceConfigOut(_ChannelConfigBase):
    type: Literal["voice"] = Field("voice", exclude=True)
    gateway_url: str | None = None
    secret: str | None = None


class WebhookConfigOut(_ChannelConfigBase):
    type: Literal["webhook"] = Field("webhook", exclude=True)
    url: str | None = None
    headers: dict[str, str] | None = None
    token: str | None = None


_OUT_MODELS: dict[str, type[_ChannelConfigBase]] = {
    "sms": SmsConfigOut,
    "email": EmailConfigOut,
    "dingtalk": DingtalkConfigOut,
    "wecom": WecomConfigOut,
    "voice": VoiceConfigOut,
    "webhook": WebhookConfigOut,
}

ChannelConfigOut = (
    SmsConfigOut | EmailConfigOut | DingtalkConfigOut | WecomConfigOut
    | VoiceConfigOut | WebhookConfigOut
)


def build_channel_config_out(channel_type: str, masked: dict[str, object]) -> ChannelConfigOut:
    """从已脱敏的 dict 构造类型化 Output config（未知类型回退 webhook 形态以保证可序列化）。"""
    model = _OUT_MODELS.get(channel_type, WebhookConfigOut)
    return cast("ChannelConfigOut", model.model_validate(masked))


class ChannelOutput(BaseModel):
    id: int
    type: str
    name: str
    config: ChannelConfigOut  # 已脱敏；类型层不承载明文/密文
    enabled: bool


def has_contact(
    phone: str | None, email: str | None, dingtalk_id: str | None, wecom_id: str | None
) -> bool:
    """接收人是否至少有一种联系方式（创建校验与更新校验共用，审查 M3/M4）。"""
    return any([phone, email, dingtalk_id, wecom_id])


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
        if not has_contact(self.phone, self.email, self.dingtalk_id, self.wecom_id):
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
