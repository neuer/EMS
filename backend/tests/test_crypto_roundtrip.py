"""对称加密 roundtrip 测试（审查测试质量第 4 节）。

补强原 test_generate_key_is_usable「名不符实、只断言长度」的缺口：
验证 generate_key 产出的密钥可真正 encrypt/decrypt 往返。
"""
from __future__ import annotations

import pytest
from app.core import crypto
from app.core.crypto import decrypt, encrypt, generate_key
from cryptography.fernet import Fernet


def test_encrypt_decrypt_roundtrip():
    secret = "p@ssw0rd-密钥-123"
    token = encrypt(secret)
    assert token != secret  # 密文不等于明文
    assert decrypt(token) == secret


def test_generate_key_is_actually_usable(monkeypatch):
    key = generate_key()
    # 用新生成的 key 实际跑一次往返，而非只断言长度
    monkeypatch.setattr(crypto, "_fernet", lambda: Fernet(key.encode("utf-8")))
    assert decrypt(encrypt("x")) == "x"


def test_decrypt_invalid_raises_value_error():
    with pytest.raises(ValueError):
        decrypt("not-a-valid-token")
