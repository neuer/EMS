"""渠道 config 敏感字段加解密与脱敏（红线：凭据加密入库、读时脱敏）。

写入：对 CHANNEL_SENSITIVE_KEYS 中的字段值加密；
读取（API 展示）：脱敏为掩码；
使用（适配器发送）：解密还原明文。

审查 C4：webhook 等渠道的 `headers`（任意 dict）可能承载 Authorization/X-Api-Key 等等价凭据，
此前既不加密也不脱敏会明文入库/明文返回。这里对 `headers` 的每个值做值级加密/脱敏/解密，
与顶层敏感键同等对待（视所有 header 值为敏感）。
"""
from __future__ import annotations

from typing import Any

from app.core.constants import CHANNEL_SECRET_MASK, CHANNEL_SENSITIVE_KEYS
from app.core.crypto import decrypt, encrypt
from app.core.logging import get_logger
from app.core.metrics import M_NOTIFY_DECRYPT, record_failure

logger = get_logger("notify")

_HEADERS_KEY = "headers"


def _encrypt_value(v: Any) -> Any:
    """非空字符串且非掩码时加密，否则原样返回（掩码表示未修改）。"""
    if isinstance(v, str) and v and v != CHANNEL_SECRET_MASK:
        return encrypt(v)
    return v


def encrypt_config(config: dict[str, Any]) -> dict[str, Any]:
    """加密敏感字段（值为非空字符串时）。掩码值保持不变（表示未修改）。"""
    out: dict[str, Any] = {}
    for k, v in config.items():
        if k == _HEADERS_KEY and isinstance(v, dict):
            out[k] = {hk: _encrypt_value(hv) for hk, hv in v.items()}
        elif k in CHANNEL_SENSITIVE_KEYS:
            out[k] = _encrypt_value(v)
        else:
            out[k] = v
    return out


def mask_config(config: dict[str, Any]) -> dict[str, Any]:
    """读取展示：敏感字段以掩码替代。"""
    out: dict[str, Any] = {}
    for k, v in config.items():
        if k == _HEADERS_KEY and isinstance(v, dict):
            out[k] = {hk: (CHANNEL_SECRET_MASK if hv else hv) for hk, hv in v.items()}
        elif k in CHANNEL_SENSITIVE_KEYS and v:
            out[k] = CHANNEL_SECRET_MASK
        else:
            out[k] = v
    return out


async def decrypt_config(config: dict[str, Any]) -> dict[str, Any]:
    """使用前还原：解密敏感字段。

    审查 I6/B6：解密失败（密钥轮换/密文损坏/被误存明文）此前静默回退原值并当凭据使用，
    会掩盖配置错误并导致网关鉴权失败方向被带偏。此处显式记错（仅字段名，不含密文/明文）
    并上报 M_NOTIFY_DECRYPT 指标（此前该指标定义却零引用），使 /health 可聚合；仍回退原值
    以让下游发送显式失败（401/业务码失败 → notify_log=failed）。
    """
    out: dict[str, Any] = {}
    for k, v in config.items():
        if k == _HEADERS_KEY and isinstance(v, dict):
            out[k] = {hk: await _decrypt_one(hv, field=f"headers.{hk}") for hk, hv in v.items()}
        elif k in CHANNEL_SENSITIVE_KEYS and isinstance(v, str) and v:
            out[k] = await _decrypt_one(v, field=k)
        else:
            out[k] = v
    return out


async def _decrypt_one(value: Any, *, field: str) -> Any:
    """解密单个敏感值；失败回退原值并记指标（仅字段名，不含密文/明文）。"""
    if not (isinstance(value, str) and value):
        return value
    try:
        return decrypt(value)
    except ValueError:
        logger.error(
            "渠道凭据解密失败，该字段将以原值参与发送并可能导致鉴权失败",
            extra={"extra_fields": {"field": field}},
        )
        await record_failure(M_NOTIFY_DECRYPT, error=f"field={field}")
        return value


def apply_config_update(old: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """更新存量 config：

    - 敏感字段为掩码 → 保留 old 的密文（视为未修改）；
    - 敏感字段有新明文 → 加密后写入（不二次加密 old 密文）；
    - 非敏感字段 → 直接覆盖。
    """
    merged = dict(old)
    for k, v in incoming.items():
        if k == _HEADERS_KEY and isinstance(v, dict):
            old_headers = dict(old.get(_HEADERS_KEY) or {})
            new_headers: dict[str, Any] = {}
            for hk, hv in v.items():
                if isinstance(hv, str) and hv and hv != CHANNEL_SECRET_MASK:
                    new_headers[hk] = encrypt(hv)
                elif hv == CHANNEL_SECRET_MASK:
                    new_headers[hk] = old_headers.get(hk, "")  # 掩码：保留原密文
                else:
                    new_headers[hk] = hv
            merged[k] = new_headers
        elif k in CHANNEL_SENSITIVE_KEYS:
            if isinstance(v, str) and v and v != CHANNEL_SECRET_MASK:
                merged[k] = encrypt(v)
            # 掩码或空：保留原值
        else:
            merged[k] = v
    return merged
