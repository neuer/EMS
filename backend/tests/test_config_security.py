"""配置安全 fail-fast 测试（红线 #9，对应审查 S3）。

非开发环境若沿用内置默认密钥/口令，Settings 构造必须失败。
通过显式传入哨兵默认值（init kwargs 优先级最高，覆盖 .env/OS env）保证离线确定性。
"""
from __future__ import annotations

import pytest
from app.core.config import (
    _DEFAULT_ADMIN_PASSWORD,
    _DEFAULT_EMS_PASSWORD,
    _DEFAULT_ENCRYPTION_KEY,
    _DEFAULT_JWT_SECRET,
    Settings,
)
from pydantic import ValidationError

_SECURE_JWT = "a-real-long-secret-value-32bytes-min"
_SECURE_ENC = "different-from-placeholder-key-value"
_SECURE_ADMIN = "S0me-Strong-Pass"
_SECURE_EMS = "ems-real-pass"


def _build(
    environment: str,
    *,
    jwt_secret: str = _DEFAULT_JWT_SECRET,
    encryption_key: str = _DEFAULT_ENCRYPTION_KEY,
    default_admin_password: str = _DEFAULT_ADMIN_PASSWORD,
    ems_password: str = _DEFAULT_EMS_PASSWORD,
) -> Settings:
    """显式关键字构造，避免 .env/OS env 干扰（init kwargs 优先级最高）。"""
    return Settings(
        environment=environment,
        jwt_secret=jwt_secret,
        encryption_key=encryption_key,
        default_admin_password=default_admin_password,
        ems_password=ems_password,
    )


def test_dev_allows_defaults():
    s = _build("development")
    assert s.jwt_secret == _DEFAULT_JWT_SECRET  # 开发环境允许默认值，不抛错


def test_production_rejects_all_defaults():
    with pytest.raises(ValidationError) as exc:
        _build("production")
    msg = str(exc.value)
    for key in ("JWT_SECRET", "ENCRYPTION_KEY", "DEFAULT_ADMIN_PASSWORD", "EMS_PASSWORD"):
        assert key in msg


def test_production_rejects_partial_default():
    with pytest.raises(ValidationError) as exc:
        _build(
            "production",
            encryption_key=_SECURE_ENC,
            default_admin_password=_SECURE_ADMIN,
            ems_password=_SECURE_EMS,
        )  # 仅 jwt_secret 仍为默认
    assert "JWT_SECRET" in str(exc.value)
    assert "EMS_PASSWORD" not in str(exc.value)


def test_production_passes_when_all_overridden():
    s = _build(
        "production",
        jwt_secret=_SECURE_JWT,
        encryption_key=_SECURE_ENC,
        default_admin_password=_SECURE_ADMIN,
        ems_password=_SECURE_EMS,
    )
    assert s.jwt_secret == _SECURE_JWT
