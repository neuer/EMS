"""配置同步相关输出模型。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class SyncResultOutput(BaseModel):
    added: int
    changed: int
    inactivated: int
    spaces: int
    devices: int
    points: int


class SyncLogOutput(BaseModel):
    id: int
    kind: str
    started_at: datetime
    finished_at: datetime | None = None
    added: int | None = None
    changed: int | None = None
    inactivated: int | None = None
    detail: str | None = None
    success: bool | None = None
