"""安全：密码哈希(bcrypt)、JWT 签发/校验、RBAC 三角色。

红线对应：
- 密码 bcrypt 哈希；登录态 JWT。
- RBAC 三角色：admin / operator / readonly；访问控制在后端执行。
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum

import bcrypt
import jwt

from app.core.config import settings


class Role(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"
    READONLY = "readonly"


# 角色等级：数值越大权限越高，便于「operator+」这类判定
ROLE_LEVEL: dict[str, int] = {
    Role.READONLY: 1,
    Role.OPERATOR: 2,
    Role.ADMIN: 3,
}


def hash_password(plain: str) -> str:
    """bcrypt 哈希密码。"""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """校验密码。"""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str, role: str, expires_minutes: int | None = None) -> str:
    """签发 JWT。subject 为用户名，role 为角色。"""
    expire = datetime.now(UTC) + timedelta(
        minutes=expires_minutes or settings.jwt_expire_minutes
    )
    payload = {"sub": subject, "role": role, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, object]:
    """解码并校验 JWT；失败抛 jwt 异常（由上层转 401）。"""
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


def role_satisfies(actual: str, required: str) -> bool:
    """判断 actual 角色是否满足 required 的最低等级要求。"""
    return ROLE_LEVEL.get(actual, 0) >= ROLE_LEVEL.get(required, 99)
