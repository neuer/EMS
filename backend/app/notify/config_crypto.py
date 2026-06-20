"""渠道 config 敏感字段加解密与脱敏（红线：凭据加密入库、读时脱敏）。

写入：对 CHANNEL_SENSITIVE_KEYS 中的字段值加密；
读取（API 展示）：脱敏为掩码；
使用（适配器发送）：解密还原明文。
"""
from __future__ import annotations

from typing import Any

from app.core.constants import CHANNEL_SECRET_MASK, CHANNEL_SENSITIVE_KEYS
from app.core.crypto import decrypt, encrypt
from app.core.logging import get_logger

logger = get_logger("notify")


def encrypt_config(config: dict[str, Any]) -> dict[str, Any]:
    """加密敏感字段（值为非空字符串时）。掩码值保持不变（表示未修改）。"""
    out: dict[str, Any] = {}
    for k, v in config.items():
        if k in CHANNEL_SENSITIVE_KEYS and isinstance(v, str) and v and v != CHANNEL_SECRET_MASK:
            out[k] = encrypt(v)
        else:
            out[k] = v
    return out


def mask_config(config: dict[str, Any]) -> dict[str, Any]:
    """读取展示：敏感字段以掩码替代。"""
    return {
        k: (CHANNEL_SECRET_MASK if (k in CHANNEL_SENSITIVE_KEYS and v) else v)
        for k, v in config.items()
    }


def decrypt_config(config: dict[str, Any]) -> dict[str, Any]:
    """使用前还原：解密敏感字段。

    审查 I6：解密失败（密钥轮换/密文损坏/被误存明文）此前静默回退原值并当凭据使用，
    会掩盖配置错误并导致网关鉴权失败方向被带偏。此处改为显式记错（仅字段名，不含密文/明文），
    使其可观测；仍回退原值以让下游发送显式失败（401/业务码失败 → notify_log=failed）。
    """
    out: dict[str, Any] = {}
    for k, v in config.items():
        if k in CHANNEL_SENSITIVE_KEYS and isinstance(v, str) and v:
            try:
                out[k] = decrypt(v)
            except ValueError:
                out[k] = v
                logger.error(
                    "渠道凭据解密失败，该字段将以原值参与发送并可能导致鉴权失败",
                    extra={"extra_fields": {"field": k}},
                )
        else:
            out[k] = v
    return out


def apply_config_update(old: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """更新存量 config：

    - 敏感字段为掩码 → 保留 old 的密文（视为未修改）；
    - 敏感字段有新明文 → 加密后写入（不二次加密 old 密文）；
    - 非敏感字段 → 直接覆盖。
    """
    merged = dict(old)
    for k, v in incoming.items():
        if k in CHANNEL_SENSITIVE_KEYS:
            if isinstance(v, str) and v and v != CHANNEL_SECRET_MASK:
                merged[k] = encrypt(v)
            # 掩码或空：保留原值
        else:
            merged[k] = v
    return merged
