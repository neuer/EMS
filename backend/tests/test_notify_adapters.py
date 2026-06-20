"""渠道适配器注册与跳过逻辑单元测试（离线、确定性）。"""
import pytest
from app.notify.channels import SUPPORTED_TYPES, ChannelSkip, NotifyMessage, get_adapter


def test_supported_types() -> None:
    assert SUPPORTED_TYPES == {"sms", "email", "dingtalk", "wecom", "voice", "webhook"}
    sms = get_adapter("sms")
    assert sms is not None and sms.type == "sms"
    assert get_adapter("unknown") is None


def test_sms_skip_without_phone() -> None:
    adapter = get_adapter("sms")
    assert adapter is not None
    msg = NotifyMessage(subject="s", content="c", level=2, trigger="raise", resource_id="d")
    with pytest.raises(ChannelSkip):
        # 无 phone → 跳过（在发起 HTTP 前抛出）
        import asyncio

        asyncio.run(adapter.send({"gateway_url": "http://x"}, {"name": "无手机"}, msg))


def test_email_skip_without_email() -> None:
    adapter = get_adapter("email")
    assert adapter is not None
    msg = NotifyMessage(subject="s", content="c", level=2, trigger="raise", resource_id="d")
    with pytest.raises(ChannelSkip):
        import asyncio

        asyncio.run(adapter.send({"smtp_host": "x"}, {"name": "无邮箱"}, msg))
