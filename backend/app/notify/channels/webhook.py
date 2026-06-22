"""Webhook 渠道：POST 告警 JSON 到配置的 url。

config：url（必填）、headers（可选 dict）、token（敏感，作为 Authorization Bearer）。
"""
from __future__ import annotations

from typing import Any

from app.notify.channels.base import ChannelError, NotifyMessage, http_post_json


def _headers(config: dict[str, Any]) -> dict[str, str]:
    headers = dict(config.get("headers") or {})
    token = config.get("token")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


class WebhookAdapter:
    type = "webhook"
    broadcast = True  # 按 url 投递，不依赖接收人地址

    async def send(
        self, config: dict[str, Any], recipient: dict[str, Any], message: NotifyMessage
    ) -> str:
        payload = {
            "alarm_id": message.alarm_id,
            "level": message.level,
            "trigger": message.trigger,
            "resource_id": message.resource_id,
            "subject": message.subject,
            "content": message.content,
            "merge_count": message.merge_count,
        }
        await http_post_json(config.get("url", ""), payload, _headers(config))
        return config.get("url", "")

    async def test(self, config: dict[str, Any]) -> None:
        if not config.get("url"):
            raise ChannelError("缺少 url")
        await http_post_json(
            config["url"], {"trigger": "test", "content": "[连通测试]"}, _headers(config)
        )
