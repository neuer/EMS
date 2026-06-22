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


async def test_dirty_body_records_parse_failure_and_acks(fake_redis, monkeypatch) -> None:
    """审查 S1：json() 抛错（畸形 JSON）时不得静默把 {} 喂给 handler——那会让 EMS 报文
    格式漂移导致整批静默丢弃而面板显示正常。应记 parse_failed 指标且不调用 handler，仍 ack。"""
    called = False

    async def _handle(_data: dict[str, Any]) -> int:
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(push_server, "handle_data_push", _handle)
    resp = await push_server.online_data_push(cast(Request, _Req(None, raise_on_json=True)))
    assert resp == _ACK  # 仍 ack，避免 EMS 重试风暴
    assert called is False  # 解析失败不喂空包给 handler
    failures = await metrics.get_failures()
    assert failures.get(metrics.M_INGEST_PUSH_HANDLE, {}).get("count") == 1  # 解析失败可观测


async def test_non_dict_body_records_parse_failure(fake_redis, monkeypatch) -> None:
    """body 解析出非 dict（如裸数组/字符串）同样视为解析失败，记指标且不喂 handler。"""
    called = False

    async def _handle(_data: dict[str, Any]) -> int:
        nonlocal called
        called = True
        return 0

    monkeypatch.setattr(push_server, "handle_alarm_push", _handle)
    resp = await push_server.online_alarm_push(cast(Request, _Req(["not", "a", "dict"])))
    assert resp == _ACK
    assert called is False
    failures = await metrics.get_failures()
    assert failures.get(metrics.M_INGEST_PUSH_HANDLE, {}).get("count") == 1


async def test_legit_empty_body_is_not_a_failure(fake_redis, monkeypatch) -> None:
    """合法空包（dict 但缺 data 键）走正常 0 计数，不计解析失败。"""
    async def _handle(data: dict[str, Any]) -> int:
        assert data == {}
        return 0

    monkeypatch.setattr(push_server, "handle_data_push", _handle)
    resp = await push_server.online_data_push(cast(Request, _Req({})))
    assert resp == _ACK
    failures = await metrics.get_failures()
    assert metrics.M_INGEST_PUSH_HANDLE not in failures  # 合法空包不算失败
