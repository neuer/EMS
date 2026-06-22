"""钉钉群机器人渠道：POST text 消息到 webhook_url。

config：webhook_url（必填）、secret（敏感，加签可选，简化为透传 content）。
"""
from __future__ import annotations

from typing import Any

from app.notify.channels.base import (
    ChannelError,
    NotifyMessage,
    http_post_json,
    raise_for_business_error,
)


class DingtalkAdapter:
    type = "dingtalk"
    broadcast = True  # 群机器人：按 webhook_url 投递，不依赖接收人地址

    async def send(
        self, config: dict[str, Any], recipient: dict[str, Any], message: NotifyMessage
    ) -> str:
        text = f"{message.subject}\n{message.content}"
        payload = {"msgtype": "text", "text": {"content": text}}
        body = await http_post_json(config.get("webhook_url", ""), payload)
        raise_for_business_error(body, channel="钉钉")  # 200+errcode!=0(限流/拦截) 视为失败
        return config.get("webhook_url", "")

    async def test(self, config: dict[str, Any]) -> None:
        if not config.get("webhook_url"):
            raise ChannelError("缺少 webhook_url")
        body = await http_post_json(
            config["webhook_url"], {"msgtype": "text", "text": {"content": "[连通测试]"}}
        )
        raise_for_business_error(body, channel="钉钉")
