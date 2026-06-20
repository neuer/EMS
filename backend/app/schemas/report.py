"""报表相关输入/输出模型（统计 / 导出 / 定时计划）。

红线 #14：对外响应模型与持久化模型分离——此处为输入/输出 Schema，
持久化用 models.system.ReportSchedule。
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Granularity = Literal["day", "week", "month"]
ReportType = Literal["daily", "weekly", "monthly"]
ExportFormat = Literal["csv", "xlsx"]


# ---- 告警统计 ----
class StatBucket(BaseModel):
    """单个时间桶的告警统计。"""

    bucket: str  # 桶标签，如 2026-06-19 / 2026-W25 / 2026-06
    total: int
    by_level: dict[int, int] = Field(default_factory=dict)
    by_source: dict[str, int] = Field(default_factory=dict)


class TopResource(BaseModel):
    resource_id: str
    name: str | None = None
    count: int


class AlarmStatsResult(BaseModel):
    granularity: Granularity
    start: int
    end: int
    total: int
    by_level: dict[int, int] = Field(default_factory=dict)
    by_source: dict[str, int] = Field(default_factory=dict)
    by_event_type: dict[int, int] = Field(default_factory=dict)
    buckets: list[StatBucket] = Field(default_factory=list)
    top_resources: list[TopResource] = Field(default_factory=list)
    # 处理时效（秒）：平均受理时长 MTTA、平均恢复时长 MTTR
    mtta_seconds: float | None = None
    mttr_seconds: float | None = None


# ---- 定时报表计划 ----
class ReportScheduleInput(BaseModel):
    name: str | None = None
    report_type: ReportType
    cron: str = Field(..., min_length=1, max_length=64)
    group_ids: list[int] = Field(default_factory=list)
    enabled: bool = True


class ReportScheduleUpdate(BaseModel):
    name: str | None = None
    report_type: ReportType | None = None
    cron: str | None = Field(None, min_length=1, max_length=64)
    group_ids: list[int] | None = None
    enabled: bool | None = None


class ReportScheduleOutput(BaseModel):
    id: int
    name: str | None = None
    report_type: str
    cron: str
    group_ids: list[int] = Field(default_factory=list)
    enabled: bool
    next_run: str | None = None  # 下次触发时间（本地时区 ISO），未注册则为 None
