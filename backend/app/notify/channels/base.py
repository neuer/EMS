"""渠道适配器基类、消息模型与共用 HTTP 工具。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.constants import NOTIFY_HTTP_CONNECT_S, NOTIFY_HTTP_READ_S

# 红线 #20：外部 HTTP 显式区分连接/读取超时（write/pool 复用读/连接超时）。
_NOTIFY_TIMEOUT = httpx.Timeout(
    connect=NOTIFY_HTTP_CONNECT_S,
    read=NOTIFY_HTTP_READ_S,
    write=NOTIFY_HTTP_READ_S,
    pool=NOTIFY_HTTP_CONNECT_S,
)


class ChannelError(Exception):
    """发送失败（可重试）。"""


class ChannelSkip(Exception):
    """接收人缺少该渠道地址，跳过（不重试、不记失败）。"""


@dataclass(frozen=True)
class NotifyMessage:
    """渠道无关的通知消息。"""

    subject: str
    content: str
    level: int
    trigger: str  # raise|recover|digest
    resource_id: str
    alarm_id: int | None = None
    merge_count: int = 1


class ChannelAdapter(Protocol):
    type: str
    # 群发型渠道（钉钉/企微/webhook 群机器人）按 webhook_url 投递、不依赖接收人地址；
    # 分发器据此在「路由无接收组」时仍投递一次，避免整条通知静默丢失（审查 H1）。
    broadcast: bool

    async def send(
        self, config: dict[str, Any], recipient: dict[str, Any], message: NotifyMessage
    ) -> str:
        """发送；返回实际投递地址。失败抛 ChannelError，无地址抛 ChannelSkip。"""
        ...

    async def test(self, config: dict[str, Any]) -> None:
        """连通性测试；失败抛 ChannelError。"""
        ...


async def http_post_json(
    url: str, payload: dict[str, Any], headers: dict[str, str] | None = None
) -> dict[str, Any]:
    """共用 HTTP POST（红线 #20：连接/读取超时）。非 2xx 抛 ChannelError。

    返回解析后的响应 body（dict；非 JSON 时返回 {}），供调用方校验「HTTP 200 但
    业务码失败」的情形（审查 S1）。
    """
    if not url:
        raise ChannelError("渠道未配置 url")
    try:
        async with httpx.AsyncClient(timeout=_NOTIFY_TIMEOUT) as client:
            resp = await client.post(url, json=payload, headers=headers or {})
    except httpx.HTTPError as exc:
        raise ChannelError(f"HTTP 调用失败: {exc}") from exc
    if resp.status_code >= 300:
        raise ChannelError(f"网关返回 {resp.status_code}: {resp.text[:200]}")
    try:
        body = resp.json()
    except (ValueError, TypeError):
        return {}
    return body if isinstance(body, dict) else {}


# 业务成功标志取值（钉钉/企微 errcode=0；通用 code=0；字符串 "0"/"ok"/"success"）
_BUSINESS_OK_VALUES: frozenset[object] = frozenset({0, "0", "ok", "OK", "success", "SUCCESS"})


def raise_for_business_error(body: dict[str, Any], *, channel: str) -> None:
    """校验「HTTP 2xx 但业务码失败」（审查 S1：避免把限流/拦截/欠费记成 sent）。

    仅在响应里出现公认的业务码字段时才判定，避免对无该约定的网关误报：
    - errcode（钉钉/企业微信）、code（通用）：非成功值即失败；
    - success=false：显式失败。
    """
    if not isinstance(body, dict):
        return
    for field in ("errcode", "code"):
        if field in body and body[field] not in _BUSINESS_OK_VALUES:
            detail = body.get("errmsg") or body.get("msg") or body.get("message") or ""
            raise ChannelError(f"{channel}网关业务失败 {field}={body[field]} {detail}".strip())
    if body.get("success") is False:
        detail = body.get("errmsg") or body.get("msg") or body.get("message") or ""
        raise ChannelError(f"{channel}网关返回 success=false {detail}".strip())
