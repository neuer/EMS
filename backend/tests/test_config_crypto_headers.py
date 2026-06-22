"""渠道 config headers 值级加密/脱敏（审查 C4）。

回归：webhook 等渠道 headers 中的 Authorization/X-Api-Key 等凭据此前既不加密入库也不脱敏返回。
"""
from __future__ import annotations

from app.core.constants import CHANNEL_SECRET_MASK
from app.notify.config_crypto import (
    apply_config_update,
    decrypt_config,
    encrypt_config,
    mask_config,
)


async def test_headers_encrypt_decrypt_roundtrip():
    cfg = {"url": "http://x", "headers": {"Authorization": "Bearer secret123", "X-Trace": "abc"}}
    enc = encrypt_config(cfg)
    assert enc["headers"]["Authorization"] != "Bearer secret123"  # 已加密入库
    dec = await decrypt_config(enc)
    assert dec["headers"]["Authorization"] == "Bearer secret123"  # 使用前还原
    assert dec["headers"]["X-Trace"] == "abc"
    assert dec["url"] == "http://x"


def test_headers_masked_on_read():
    cfg = {"url": "http://x", "headers": {"Authorization": "Bearer secret123"}}
    masked = mask_config(cfg)
    assert masked["headers"]["Authorization"] == CHANNEL_SECRET_MASK
    assert masked["url"] == "http://x"  # 非敏感字段不脱敏


def test_headers_update_preserves_masked():
    old = encrypt_config({"headers": {"Authorization": "Bearer secret123"}})
    # 前端回传掩码占位 → 保留原密文（视为未修改）
    merged = apply_config_update(old, {"headers": {"Authorization": CHANNEL_SECRET_MASK}})
    assert merged["headers"]["Authorization"] == old["headers"]["Authorization"]


def test_headers_update_with_new_value_encrypts():
    old = encrypt_config({"headers": {"Authorization": "Bearer old"}})
    merged = apply_config_update(old, {"headers": {"Authorization": "Bearer new"}})
    assert merged["headers"]["Authorization"] not in ("Bearer new", old["headers"]["Authorization"])
