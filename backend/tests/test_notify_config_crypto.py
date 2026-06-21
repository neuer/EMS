"""渠道 config 加解密/脱敏单元测试（离线、确定性）。"""
from app.core.constants import CHANNEL_SECRET_MASK
from app.notify.config_crypto import (
    apply_config_update,
    decrypt_config,
    encrypt_config,
    mask_config,
)


async def test_encrypt_then_decrypt_roundtrip() -> None:
    raw = {"gateway_url": "http://sms.local", "secret": "s3cr3t", "sign": "DCIM"}
    enc = encrypt_config(raw)
    assert enc["secret"] != "s3cr3t"  # 已加密
    assert enc["gateway_url"] == "http://sms.local"  # 非敏感不变
    dec = await decrypt_config(enc)
    assert dec["secret"] == "s3cr3t"


def test_mask_hides_sensitive() -> None:
    enc = encrypt_config({"url": "http://x", "token": "abc"})
    masked = mask_config(enc)
    assert masked["token"] == CHANNEL_SECRET_MASK
    assert masked["url"] == "http://x"


async def test_apply_update_keeps_old_secret_on_mask() -> None:
    old = encrypt_config({"gateway_url": "http://a", "secret": "old"})
    # 掩码表示未修改：保留旧密文；非敏感字段更新
    merged = apply_config_update(old, {"gateway_url": "http://b", "secret": CHANNEL_SECRET_MASK})
    assert merged["gateway_url"] == "http://b"
    assert (await decrypt_config(merged))["secret"] == "old"


async def test_apply_update_replaces_secret_with_new_plaintext() -> None:
    old = encrypt_config({"secret": "old"})
    merged = apply_config_update(old, {"secret": "new"})
    assert (await decrypt_config(merged))["secret"] == "new"
