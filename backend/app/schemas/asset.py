"""资产树/设备/测点/元数据 输入输出模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class AssetMetaInput(BaseModel):
    alias: str | None = None
    group_name: str | None = None
    tags: list[str] | None = None
    importance: int | None = Field(None, ge=1, le=5)
    custom_unit: str | None = None
    remark: str | None = None


class AssetMetaOutput(BaseModel):
    resource_id: str
    asset_kind: int
    alias: str | None = None
    group_name: str | None = None
    tags: list[str] | None = None
    importance: int | None = None
    custom_unit: str | None = None
    remark: str | None = None


class SpaceNode(BaseModel):
    resource_id: str
    name: str
    parent_id: str | None = None
    space_type: int | None = None
    alias: str | None = None
    active_alarms: int = 0
    max_level: int | None = None  # 子树内最严重告警级别（1 最严重）
    children: list[SpaceNode] = Field(default_factory=list)


SpaceNode.model_rebuild()


class DeviceOutput(BaseModel):
    resource_id: str
    name: str
    device_type: str | None = None
    parent_id: str | None = None
    location: str | None = None
    is_active: bool
    alias: str | None = None
    group_name: str | None = None
    status: int | None = None  # 0通信中断 1正常（来自 Redis/落库）
    active_alarms: int = 0


class PointOutput(BaseModel):
    resource_id: str
    name: str
    device_id: str
    spot_type: int | None = None
    unit: str | None = None
    is_active: bool
    alias: str | None = None
    group_name: str | None = None
    importance: int | None = None
    value: str | None = None
    save_time: int | None = None
    active_alarms: int = 0


class RuleBrief(BaseModel):
    id: int
    name: str | None = None
    operator: str
    operand: float | None = None
    operand_min: float | None = None
    operand_max: float | None = None
    cond_type: str
    level: int
    enabled: bool


class DeviceDetail(DeviceOutput):
    points: list[PointOutput] = Field(default_factory=list)


class PointDetail(PointOutput):
    mapper: str | None = None
    access: str | None = None
    meta: AssetMetaOutput | None = None
    rules: list[RuleBrief] = Field(default_factory=list)
