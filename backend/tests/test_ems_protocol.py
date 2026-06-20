"""EMS 协议错误码语义测试（红线 #4，审查 2.3）。

纯逻辑、零依赖：error_code 2/106 触发重登重订阅；100 为致命（停止重连）。
回归示例：若有人把 106 从 RELOGIN_CODES 删掉，心跳超时后平台不再重登，
推送链路静默死亡——本测试守护该红线。
"""
from __future__ import annotations

from app.ems.protocol import (
    ERROR_ABNORMAL_TOKEN,
    ERROR_HEART_TIMEOUT,
    ERROR_USER_PASSWORD_WRONG,
    EmsError,
)


def test_token_abnormal_triggers_relogin():
    assert EmsError(ERROR_ABNORMAL_TOKEN, "abnormal token").need_relogin is True


def test_heart_timeout_triggers_relogin():
    assert EmsError(ERROR_HEART_TIMEOUT, "heart timeout").need_relogin is True


def test_credential_error_is_fatal_not_relogin():
    err = EmsError(ERROR_USER_PASSWORD_WRONG, "wrong password")
    assert err.is_fatal is True
    assert err.need_relogin is False


def test_other_business_error_neither():
    err = EmsError(101, "resource not exist")
    assert err.need_relogin is False
    assert err.is_fatal is False
