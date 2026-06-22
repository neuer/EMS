"""语音外呼渠道：POST 到外呼网关（电话播报）。

config：gateway_url（必填）、secret（敏感，可选）。
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


class VoiceAdapter:
    type = "voice"
    broadcast = False  # 点对点：需接收人手机号

    async def send(
        self, config: dict[str, Any], recipient: dict[str, Any], message: NotifyMessage
    ) -> str:
        phone = recipient.get("phone")
        if not phone:
            raise ChannelSkip("接收人无手机号")
        payload = {"phone": phone, "content": message.content, "secret": config.get("secret", "")}
        body = await http_post_json(config.get("gateway_url", ""), payload)
        raise_for_business_error(body, channel="语音")  # 200+code!=0 视为失败
        return phone

    async def test(self, config: dict[str, Any]) -> None:
        if not config.get("gateway_url"):
            raise ChannelError("缺少 gateway_url")
        await http_post_json(
            config["gateway_url"], {"phone": "00000000000", "content": "[连通测试]", "test": True}
        )
