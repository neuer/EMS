"""对称加密：用于 EMS 凭据等敏感字段加密入库（红线：凭据加密、不裸奔）。

使用 Fernet（AES-128-CBC + HMAC）。密钥来自 settings.encryption_key。
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _fernet() -> Fernet:
    # encryption_key 必须为 urlsafe base64 的 32 字节密钥
    return Fernet(settings.encryption_key.encode("utf-8"))


def encrypt(plaintext: str) -> str:
    """加密明文，返回可入库的密文字符串。"""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(ciphertext: str) -> str:
    """解密密文。无法解密时抛出 ValueError。"""
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("无法解密：密文无效或密钥不匹配") from exc


def generate_key() -> str:
    """生成一个新的 Fernet 密钥（用于初始化 .env）。"""
    return Fernet.generate_key().decode("utf-8")
