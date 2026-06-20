"""安全模块单元测试（离线、确定性）。"""
import jwt
import pytest
from app.core.security import (
    Role,
    create_access_token,
    decode_access_token,
    hash_password,
    role_satisfies,
    verify_password,
)


def test_password_hash_and_verify() -> None:
    pwd = "P@ssw0rd-动环"
    hashed = hash_password(pwd)
    assert hashed != pwd
    assert verify_password(pwd, hashed) is True
    assert verify_password("wrong", hashed) is False


def test_jwt_roundtrip() -> None:
    token = create_access_token(subject="admin", role=Role.ADMIN)
    payload = decode_access_token(token)
    assert payload["sub"] == "admin"
    assert payload["role"] == "admin"


def test_jwt_invalid_raises() -> None:
    with pytest.raises(jwt.PyJWTError):
        decode_access_token("invalid.token.value")


@pytest.mark.parametrize(
    ("actual", "required", "expected"),
    [
        (Role.ADMIN, Role.OPERATOR, True),
        (Role.OPERATOR, Role.OPERATOR, True),
        (Role.READONLY, Role.OPERATOR, False),
        (Role.OPERATOR, Role.ADMIN, False),
        (Role.READONLY, Role.READONLY, True),
    ],
)
def test_role_satisfies(actual: str, required: str, expected: bool) -> None:
    assert role_satisfies(actual, required) is expected
