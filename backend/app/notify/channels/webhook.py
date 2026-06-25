"""Webhook 渠道：POST 告警 JSON 到配置的 url。

config：url（必填）、headers（可选 dict）、token（敏感，作为 Authorization Bearer）。
"""
from __future__ import annotations

from typing import Any

from app.notify.channels.base import (
    ChannelError,
    NotifyMessage,
    http_post_json,
    raise_for_business_error,
)


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
        body = await http_post_json(config.get("url", ""), payload, _headers(config))
        # 审查 S1/HIGH-1：与其余渠道一致校验「HTTP 200 但业务码失败」，避免限流/拦截
        # 被静默记成 sent（通知静默失败=告警未送达）。
        raise_for_business_error(body, channel="Webhook")
        return config.get("url", "")

    async def test(self, config: dict[str, Any]) -> None:
        if not config.get("url"):
            raise ChannelError("缺少 url")
        body = await http_post_json(
            config["url"], {"trigger": "test", "content": "[连通测试]"}, _headers(config)
        )
        raise_for_business_error(body, channel="Webhook")
