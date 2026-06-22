"""渠道 config 判别联合校验与脱敏 Output 测试（审查 H2，离线确定性）。

验证：Input 按 type 强制必填结构字段（webhook 缺 url → 422）；config_for_storage 不含判别
字段 type；Output 经 mask_config 后不含明文/密文，且类型化序列化不泄露 type。
"""
from __future__ import annotations

import pytest
from app.core.constants import CHANNEL_SECRET_MASK
from app.notify.config_crypto import encrypt_config, mask_config
from app.schemas.notify import (
    ChannelInput,
    ChannelOutput,
    build_channel_config_out,
)
from pydantic import ValidationError


def test_webhook_requires_url() -> None:
    with pytest.raises(ValidationError):
        ChannelInput.model_validate(
            {"type": "webhook", "name": "w", "config": {"token": "t"}}  # 缺 url
        )


def test_sms_requires_gateway_url() -> None:
    with pytest.raises(ValidationError):
        ChannelInput.model_validate({"type": "sms", "name": "s", "config": {"sign": "X"}})


def test_valid_config_storage_excludes_discriminator() -> None:
    ch = ChannelInput.model_validate(
        {
            "type": "sms",
            "name": "短信",
            "config": {"gateway_url": "http://sms.local", "secret": "s3cr3t", "sign": "DCIM"},
        }
    )
    stored = ch.config_for_storage()
    assert "type" not in stored  # 判别字段不入存储
    assert stored["gateway_url"] == "http://sms.local"
    assert stored["secret"] == "s3cr3t"  # 明文供 encrypt_config 加密


def test_extra_keys_tolerated() -> None:
    """前端自由 JSON 编辑器：附加未知键应被容忍（extra=ignore），不报错。"""
    ch = ChannelInput.model_validate(
        {
            "type": "webhook",
            "name": "w",
            "config": {"url": "http://hook", "extra_field": "x"},
        }
    )
    stored = ch.config_for_storage()
    assert stored["url"] == "http://hook"
    assert "extra_field" not in stored  # 未声明字段被忽略，不进入存储


def test_output_masks_secret_and_excludes_type() -> None:
    # 模拟存储态（secret 已加密），经 mask_config 脱敏后构造 Output
    stored = encrypt_config({"webhook_url": "http://dt", "secret": "real-secret"})
    masked = mask_config(stored)
    out = ChannelOutput(
        id=1,
        type="dingtalk",
        name="钉钉",
        config=build_channel_config_out("dingtalk", masked),
        enabled=True,
    ).model_dump()
    cfg = out["config"]
    assert cfg["secret"] == CHANNEL_SECRET_MASK  # 脱敏，不泄露明文/密文
    assert "real-secret" not in str(cfg)
    assert "type" not in cfg  # 判别字段不对外暴露
    assert cfg["webhook_url"] == "http://dt"
