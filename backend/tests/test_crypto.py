"""加密模块单元测试（离线、确定性）。"""
import pytest
from app.core import crypto


def test_encrypt_decrypt_roundtrip() -> None:
    plain = "ems-secret-密码-123"
    cipher = crypto.encrypt(plain)
    assert cipher != plain
    assert crypto.decrypt(cipher) == plain


def test_decrypt_invalid_raises() -> None:
    with pytest.raises(ValueError):
        crypto.decrypt("not-a-valid-token")


def test_generate_key_is_usable() -> None:
    key = crypto.generate_key()
    # 生成的密钥应为 44 字符 urlsafe base64
    assert len(key) == 44
