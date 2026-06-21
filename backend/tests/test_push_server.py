"""EMS 推送接收端点契约测试（红线 #2，审查 E3）。

验证 /north/online_data_push、/north/online_alarm_push 固定 ack、处理异常仍 ack 且记指标、
脏 body 解包。直接调用端点函数（注入桩 Request），避免拉起含 EMS 连接的 app lifespan。
"""
from __future__ import annotations

from typing import Any, cast

from app.core import metrics
from app.ems import push_server
from fastapi import Request

_ACK = {"error_code": 0, "error_msg": "ok", "data": {"status": True}}


class _Req:
    """最小桩 Request：json() 返回预置 body 或抛错（模拟脏 body）。"""

    def __init__(self, body: Any, *, raise_on_json: bool = False) -> None:
        self._body = body
        self._raise = raise_on_json

    async def json(self) -> Any:
        if self._raise:
            raise ValueError("invalid json")
        return self._body


async def test_data_push_returns_fixed_ack(fake_redis, monkeypatch) -> None:
    captured: dict[str, Any] = {}

    async def _handle(data: dict[str, Any]) -> int:
        captured["data"] = data
        return 3

    monkeypatch.setattr(push_server, "handle_data_push", _handle)
    resp = await push_server.online_data_push(cast(Request, _Req({"data": {"points": []}})))
    assert resp == _ACK  # 固定 ack
    assert captured["data"] == {"points": []}  # _read_data 正确解包 data


async def test_data_push_acks_and_records_metric_on_failure(fake_redis, monkeypatch) -> None:
    async def _boom(_data: dict[str, Any]) -> int:
        raise RuntimeError("handler boom")

    monkeypatch.setattr(push_server, "handle_data_push", _boom)
    resp = await push_server.online_data_push(cast(Request, _Req({"data": {}})))
    assert resp == _ACK  # 处理失败仍 ack，避免 EMS 重试风暴
    failures = await metrics.get_failures()
    assert failures.get(metrics.M_INGEST_PUSH_HANDLE, {}).get("count") == 1  # 失败可观测


async def test_alarm_push_returns_fixed_ack(fake_redis, monkeypatch) -> None:
    async def _handle(_data: dict[str, Any]) -> int:
        return 1

    monkeypatch.setattr(push_server, "handle_alarm_push", _handle)
    resp = await push_server.online_alarm_push(cast(Request, _Req({"data": {"alarms": []}})))
    assert resp == _ACK


async def test_dirty_body_is_tolerated(fake_redis, monkeypatch) -> None:
    """json() 抛错时 _read_data 回退空 dict，仍正常 ack（不 500）。"""
    seen: dict[str, Any] = {}

    async def _handle(data: dict[str, Any]) -> int:
        seen["data"] = data
        return 0

    monkeypatch.setattr(push_server, "handle_data_push", _handle)
    resp = await push_server.online_data_push(cast(Request, _Req(None, raise_on_json=True)))
    assert resp == _ACK
    assert seen["data"] == {}  # 脏 body → 空 data
