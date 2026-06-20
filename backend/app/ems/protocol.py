"""共济协议常量与错误模型（《数据接入标准 V2.23》）。

集中处理：包头格式、error_code 语义、需重登的错误码。
所有对 EMS 的报文格式与错误码逻辑只在此与 client.py 处理（红线要求集中一处）。
"""
from __future__ import annotations

# error_code 语义（HTTP 200 时有效）
ERROR_OK = 0
ERROR_ABNORMAL_PARAM = 1
ERROR_ABNORMAL_TOKEN = 2
ERROR_ABNORMAL_VERSION = 3
ERROR_OTHER = 4
ERROR_UNKNOWN = 5
ERROR_USER_PASSWORD_WRONG = 100
ERROR_RESOURCE_NOT_EXIST = 101
ERROR_TIME_FORMAT = 102
ERROR_ABNORMAL_VALUE = 104
ERROR_HEART_TIMEOUT = 106

# 触发重新登录 + 重订阅的错误码（红线 #4）
RELOGIN_CODES: frozenset[int] = frozenset({ERROR_ABNORMAL_TOKEN, ERROR_HEART_TIMEOUT})

# 登录凭据错误：停止重试
FATAL_CODES: frozenset[int] = frozenset({ERROR_USER_PASSWORD_WRONG})


class EmsError(Exception):
    """EMS 业务错误（error_code != 0）。"""

    def __init__(self, code: int, msg: str) -> None:
        self.code = code
        self.msg = msg
        super().__init__(f"EMS error_code={code} msg={msg}")

    @property
    def need_relogin(self) -> bool:
        return self.code in RELOGIN_CODES

    @property
    def is_fatal(self) -> bool:
        return self.code in FATAL_CODES


class EmsTransportError(Exception):
    """网络/HTTP 层错误（连接失败、超时、非 200 等）。"""
