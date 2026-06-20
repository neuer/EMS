"""抑制（屏蔽/维护窗口）输入/输出模型。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.core.constants import ResourceKind


class MuteInput(BaseModel):
    point_id: str
    reason: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None  # None 表示长期屏蔽


class MuteOutput(BaseModel):
    id: int
    point_id: str
    reason: str | None = None
    start_at: datetime
    end_at: datetime | None = None
    enabled: bool


class MaintenanceInput(BaseModel):
    name: str | None = None
    scope_kind: ResourceKind = Field(..., description="5空间 2设备 3测点")
    scope_ids: list[str] = Field(..., min_length=1)
    start_at: datetime
    end_at: datetime
    record_silenced: bool = True

    @model_validator(mode="after")
    def _check_range(self) -> MaintenanceInput:
        if self.end_at <= self.start_at:
            raise ValueError("end_at 必须大于 start_at")
        return self


class MaintenanceUpdate(BaseModel):
    name: str | None = None
    scope_kind: ResourceKind | None = None
    scope_ids: list[str] | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    record_silenced: bool | None = None


class MaintenanceOutput(BaseModel):
    id: int
    name: str | None = None
    scope_kind: ResourceKind
    scope_ids: list[str]
    start_at: datetime
    end_at: datetime
    record_silenced: bool
