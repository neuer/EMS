"""通知渠道失败语义测试（审查 S1/I6）。

S1：HTTP 200 但业务码失败（钉钉/企微 errcode、通用 code、success=false）必须抛 ChannelError，
而不能被记成 sent。用 respx 离线拦截 httpx，保证无网络确定性。
"""
from __future__ import annotations

import httpx
import pytest
import respx
from app.notify.channels.base import (
    ChannelError,
    NotifyMessage,
    http_post_json,
    raise_for_business_error,
)
from app.notify.channels.dingtalk import DingtalkAdapter
from app.notify.channels.sms import SmsAdapter

_MSG = NotifyMessage(
    subject="[严重告警] x", content="机房温度过高", level=2, trigger="raise", resource_id="p1"
)


def test_raise_for_business_error_flags_errcode():
    with pytest.raises(ChannelError):
        raise_for_business_error({"errcode": 310000, "errmsg": "send too fast"}, channel="钉钉")


def test_raise_for_business_error_passes_success():
    raise_for_business_error({"errcode": 0, "errmsg": "ok"}, channel="钉钉")  # 不抛
    raise_for_business_error({"code": "0"}, channel="x")
    raise_for_business_error({}, channel="x")  # 无业务码字段不误报


def test_raise_for_business_error_flags_success_false():
    with pytest.raises(ChannelError):
        raise_for_business_error({"success": False, "msg": "余额不足"}, channel="短信")


@respx.mock
async def test_http_post_json_returns_body():
    respx.post("http://gw/x").mock(return_value=httpx.Response(200, json={"errcode": 0}))
    body = await http_post_json("http://gw/x", {"a": 1})
    assert body == {"errcode": 0}


@respx.mock
async def test_dingtalk_send_raises_on_business_error():
    """钉钉返回 200 + errcode=310000（限流）→ send 必须抛 ChannelError（不会被记 sent）。"""
    respx.post("http://dingtalk/hook").mock(
        return_value=httpx.Response(200, json={"errcode": 310000, "errmsg": "send too fast"})
    )
    with pytest.raises(ChannelError):
        await DingtalkAdapter().send({"webhook_url": "http://dingtalk/hook"}, {}, _MSG)


@respx.mock
async def test_dingtalk_send_ok():
    respx.post("http://dingtalk/hook").mock(
        return_value=httpx.Response(200, json={"errcode": 0, "errmsg": "ok"})
    )
    addr = await DingtalkAdapter().send({"webhook_url": "http://dingtalk/hook"}, {}, _MSG)
    assert addr == "http://dingtalk/hook"


@respx.mock
async def test_sms_send_raises_on_business_error():
    respx.post("http://sms/gw").mock(
        return_value=httpx.Response(200, json={"code": 1, "msg": "签名未报备"})
    )
    with pytest.raises(ChannelError):
        await SmsAdapter().send({"gateway_url": "http://sms/gw"}, {"phone": "13800000000"}, _MSG)
