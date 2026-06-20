"""统一响应包络：平台自身 API 统一 {"code":0,"msg":"ok","data":...}。"""
from __future__ import annotations

from pydantic import BaseModel


class ApiResponse[T](BaseModel):
    code: int = 0
    msg: str = "ok"
    data: T | None = None


def ok(data: object = None) -> dict[str, object]:
    """构造成功响应。"""
    return {"code": 0, "msg": "ok", "data": data}


def fail(code: int, msg: str, data: object = None) -> dict[str, object]:
    """构造错误响应（结构化错误模型）。"""
    return {"code": code, "msg": msg, "data": data}
