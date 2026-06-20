"""实时数据输出模型。"""
from __future__ import annotations

from pydantic import BaseModel


class PointLatest(BaseModel):
    id: str
    value: str | None = None
    save_time: int | None = None
