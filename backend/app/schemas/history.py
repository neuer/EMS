"""历史趋势查询输入/输出模型（与持久化模型分离，红线 #5.5）。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.core.constants import HISTORY_RAW_MAX_SPAN_S, OFFLINE_MAX_POINTS

Agg = Literal["raw", "5min", "auto"]


class HistoryQuery(BaseModel):
    """历史查询入参；start/end 为 Unix 秒。"""

    # 审查 I3：测点数上限与平台测点规模一致，避免一次请求百测点×数月原始行拖垮 DB。
    point_ids: list[str] = Field(
        ..., min_length=1, max_length=OFFLINE_MAX_POINTS, description="测点 resource_id 列表"
    )
    start: int = Field(..., description="起始时间 Unix 秒")
    end: int = Field(..., description="结束时间 Unix 秒")
    agg: Agg = Field("auto", description="raw|5min|auto，auto 按范围自动选层")

    @model_validator(mode="after")
    def _check_range(self) -> HistoryQuery:
        if self.end <= self.start:
            raise ValueError("end 必须大于 start")
        # 审查 I3：显式 raw 层强制跨度 ≤1 天（大跨度应走 auto/5min 降采样层），
        # 防止原始层被超大范围查询放大。
        if self.agg == "raw" and self.end - self.start > HISTORY_RAW_MAX_SPAN_S:
            raise ValueError("raw 层单次跨度不得超过 1 天，请改用 agg=auto 或 5min")
        return self


class RawSample(BaseModel):
    """原始层样本点。"""

    ts: int  # Unix 秒
    value: float | None = None


class AggSample(BaseModel):
    """5min 降采样层样本点。"""

    ts: int  # 桶起始 Unix 秒
    avg: float | None = None
    min: float | None = None
    max: float | None = None
    count: int = 0


class HistorySeries(BaseModel):
    """单测点序列。layer 标注实际命中的存储层。"""

    point_id: str
    layer: Literal["raw", "5min"]
    raw: list[RawSample] | None = None
    agg: list[AggSample] | None = None

    @model_validator(mode="after")
    def _check_layer_consistency(self) -> HistorySeries:
        # 审查 M3：layer 与有效字段必须一致，避免可表示的非法状态（raw 层却填了 agg 等）。
        if self.layer == "raw" and self.agg is not None:
            raise ValueError("layer=raw 时不应提供 agg")
        if self.layer == "5min" and self.raw is not None:
            raise ValueError("layer=5min 时不应提供 raw")
        return self


class HistoryResult(BaseModel):
    layer: Literal["raw", "5min"]
    start: int
    end: int
    series: list[HistorySeries]
