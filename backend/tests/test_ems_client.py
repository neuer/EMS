"""EMS 协议封装/解析测试（红线 #3，审查 E2）。

此前 client.py 的 _post 包头封装、token 头、error_code 校验、offline_value 畸形回退零覆盖。
用 respx 离线拦截 httpx，验证报文格式与错误码逻辑（事实源只在 client.py / protocol.py）。
"""
from __future__ import annotations

import json

import httpx
import pytest
import respx
from app.ems.client import EmsClient
from app.ems.protocol import EmsError, EmsTransportError

_BASE = "http://ems"


def _client() -> EmsClient:
    return EmsClient(_BASE, "20170714124155")


@respx.mock
async def test_login_sends_header_packet_without_token() -> None:
    route = respx.post(f"{_BASE}/north/login").mock(
        return_value=httpx.Response(200, json={"error_code": 0, "error_msg": "ok",
                                               "data": {"token": "T123"}})
    )
    c = _client()
    token = await c.login("u", "p", "backend", "8000")
    assert token == "T123"
    assert c.token == "T123"
    req = route.calls.last.request
    body = json.loads(req.content)
    assert body["version"] == "20170714124155"  # 包头 version
    assert body["data"]["username"] == "u"  # 包头 data
    assert "token" not in req.headers  # 红线 #3：login 不带 token 头


@respx.mock
async def test_tokened_request_carries_token_header() -> None:
    route = respx.post(f"{_BASE}/north/heart").mock(
        return_value=httpx.Response(200, json={"error_code": 0, "error_msg": "ok", "data": {}})
    )
    c = _client()
    c.token = "TOK"
    await c.heart()
    assert route.calls.last.request.headers["token"] == "TOK"  # 除 login 外带 token


@respx.mock
async def test_business_error_raises_ems_error() -> None:
    respx.post(f"{_BASE}/north/heart").mock(
        return_value=httpx.Response(200, json={"error_code": 2, "error_msg": "abnormal token",
                                               "data": {}})
    )
    c = _client()
    c.token = "TOK"
    with pytest.raises(EmsError) as ei:
        await c.heart()
    assert ei.value.code == 2
    assert ei.value.need_relogin


@respx.mock
async def test_non_200_raises_transport_error() -> None:
    respx.post(f"{_BASE}/north/heart").mock(return_value=httpx.Response(500))
    c = _client()
    c.token = "TOK"
    with pytest.raises(EmsTransportError):
        await c.heart()


@respx.mock
async def test_malformed_error_code_raises_transport_error() -> None:
    """审查 B7：error_code 为畸形非整数 → 归一为 EmsTransportError，不逃逸分类。"""
    respx.post(f"{_BASE}/north/heart").mock(
        return_value=httpx.Response(200, json={"error_code": "oops", "error_msg": "x", "data": {}})
    )
    c = _client()
    c.token = "TOK"
    with pytest.raises(EmsTransportError):
        await c.heart()


@respx.mock
async def test_offline_value_unpacks_list() -> None:
    respx.post(f"{_BASE}/north/offline_value").mock(
        return_value=httpx.Response(200, json={
            "error_code": 0, "error_msg": "ok",
            "data": [{"resource_id": "p1", "data_list": [{"value": 1.0, "time": 100}]}],
        })
    )
    c = _client()
    c.token = "TOK"
    series = await c.offline_value(0, 100, ["p1"], "five")
    assert len(series) == 1
    assert series[0]["resource_id"] == "p1"


@respx.mock
async def test_offline_value_malformed_returns_empty() -> None:
    """error_code=0 但 data 非 list（畸形）→ 按空结果处理，不误判为无数据后续静默。"""
    respx.post(f"{_BASE}/north/offline_value").mock(
        return_value=httpx.Response(200, json={"error_code": 0, "error_msg": "ok",
                                               "data": {"weird": 1}})
    )
    c = _client()
    c.token = "TOK"
    assert await c.offline_value(0, 100, ["p1"], "five") == []
