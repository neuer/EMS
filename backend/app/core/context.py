"""请求级上下文（红线 §10：request_id 贯穿前后端、队列）。

ASGI 中间件在请求入口写入 request_id，日志 Formatter 自动注入，
跨异步调用通过 ContextVar 传递，无需逐层透传参数。
"""
from __future__ import annotations

from contextvars import ContextVar

# 当前请求的 request_id；非请求上下文（调度任务/worker）为空串。
_request_id: ContextVar[str] = ContextVar("request_id", default="")


def set_request_id(value: str) -> None:
    _request_id.set(value)


def get_request_id() -> str:
    return _request_id.get()
