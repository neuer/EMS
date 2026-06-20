"""告警中心输入/输出模型。"""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.core.constants import AlarmSource, AlarmStatus, ResourceKind


class AlarmOutput(BaseModel):
    id: int
    source: AlarmSource
    guid: str | None = None
    rule_id: int | None = None
    resource_id: str
    resource_kind: ResourceKind
    event_type: int | None = None  # 跨源语义不同：EMS={0,21,30}，平台={2,3,4}，保留 int
    level: int
    status: AlarmStatus
    trigger_value: float | None = None
    content: str | None = None
    suggest: str | None = None
    masked: bool
    silenced_reason: str | None = None
    merge_count: int
    triggered_at: datetime
    accepted_at: datetime | None = None
    confirmed_at: datetime | None = None
    recovered_at: datetime | None = None


class AlarmEventOutput(BaseModel):
    id: int
    event: str
    operator_id: int | None = None
    note: str | None = None
    snapshot: float | None = None
    occurred_at: datetime


class AlarmDetailOutput(AlarmOutput):
    events: list[AlarmEventOutput] = []


class AlarmHistoryQuery(BaseModel):
    start: int = Field(..., description="起始 Unix 秒")
    end: int = Field(..., description="结束 Unix 秒")
    level: int | None = Field(None, ge=1, le=5)
    status: AlarmStatus | None = None
    source: AlarmSource | None = None
    resource_id: str | None = None
    event_type: int | None = None
    masked: bool | None = None
    limit: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0)


class AlarmActionInput(BaseModel):
    note: str | None = None


class AlarmNoteInput(BaseModel):
    note: str = Field(..., min_length=1)
