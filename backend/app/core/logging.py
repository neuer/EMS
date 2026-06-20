"""结构化日志：JSON 格式输出，按模块分类（采集/规则/通知/同步等）。

红线对应：
- 结构化字段 JSON，禁止拼接不可解析的长字符串。
- 日志按模块分类：通过 get_logger("ingest"/"engine"/"notify"/"sync" ...) 区分。
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

from app.core.config import settings

_CONFIGURED = False


class JsonFormatter(logging.Formatter):
    """将日志记录序列化为单行 JSON。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }
        # 透传额外结构化字段（如 request_id），保持可解析
        for key, value in getattr(record, "extra_fields", {}).items():
            payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging() -> None:
    """初始化根日志处理器（幂等）。"""
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level.upper())
    _CONFIGURED = True


def get_logger(module: str) -> logging.Logger:
    """获取按模块命名的 logger，例如 get_logger("sync")。"""
    setup_logging()
    return logging.getLogger(module)
