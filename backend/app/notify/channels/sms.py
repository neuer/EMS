"""短信渠道：对接内部短信平台（网关/密钥可配）。

config 字段：
- gateway_url：内部短信平台接口地址（必填）
- sign：短信签名（可选）
- account：平台账号（可选）
- secret：平台密钥（敏感，加密存储）
"""
from __future__ import annotations

from typing import Any

from app.notify.channels.base import (
    ChannelError,
    ChannelSkip,
    NotifyMessage,
    http_post_json,
    raise_for_business_error,
)


class SmsAdapter:
    type = "sms"

    async def send(
        self, config: dict[str, Any], recipient: dict[str, Any], message: NotifyMessage
    ) -> str:
        phone = recipient.get("phone")
        if not phone:
            raise ChannelSkip("接收人无手机号")
        payload = {
            "phone": phone,
            "content": message.content,
            "sign": config.get("sign", ""),
            "account": config.get("account", ""),
            "secret": config.get("secret", ""),
        }
        body = await http_post_json(config.get("gateway_url", ""), payload)
        raise_for_business_error(body, channel="短信")  # 200+code!=0(欠费/签名未报备) 视为失败
        return phone

    async def test(self, config: dict[str, Any]) -> None:
        if not config.get("gateway_url"):
            raise ChannelError("缺少 gateway_url")
        payload = {"phone": "00000000000", "content": "[连通测试]", "sign": config.get("sign", ""),
                   "account": config.get("account", ""), "secret": config.get("secret", ""),
                   "test": True}
        await http_post_json(config["gateway_url"], payload)
