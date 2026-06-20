"""预警规则输入/输出模型。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Operator = Literal[">", "<", "=", "<>", "<=", ">="]
CondType = Literal["threshold", "range"]


def check_operands(
    cond_type: str,
    operand: float | None,
    operand_min: float | None,
    operand_max: float | None,
) -> None:
    """规则操作数一致性不变量（创建与更新共用，审查 I2）。违反抛 ValueError。

    - range：必须同时提供 operand_min 与 operand_max 且 min ≤ max；
    - threshold：必须提供 operand。
    否则规则落库即非法，引擎会静默永不触发。
    """
    if cond_type == "range":
        if operand_min is None or operand_max is None:
            raise ValueError("区间规则需提供 operand_min 与 operand_max")
        if operand_min > operand_max:
            raise ValueError("operand_min 不能大于 operand_max")
    elif operand is None:
        raise ValueError("阈值规则需提供 operand")


class RuleInput(BaseModel):
    point_id: str
    name: str | None = None
    enabled: bool = True
    operator: Operator = ">"
    operand: float | None = None
    operand_min: float | None = None
    operand_max: float | None = None
    cond_type: CondType = "threshold"
    restore_operator: Operator | None = None
    restore_operand: float | None = None
    continuous_time: int = Field(0, ge=0)
    recover_hold_time: int = Field(0, ge=0)
    level: int = Field(..., ge=1, le=5)
    priority: int = Field(0, ge=0)
    content_tpl: str | None = None
    suggest: str | None = None

    @model_validator(mode="after")
    def _check_operands(self) -> RuleInput:
        check_operands(self.cond_type, self.operand, self.operand_min, self.operand_max)
        return self


class RuleUpdate(BaseModel):
    name: str | None = None
    enabled: bool | None = None
    operator: Operator | None = None
    operand: float | None = None
    operand_min: float | None = None
    operand_max: float | None = None
    cond_type: CondType | None = None
    restore_operator: Operator | None = None
    restore_operand: float | None = None
    continuous_time: int | None = Field(None, ge=0)
    recover_hold_time: int | None = Field(None, ge=0)
    level: int | None = Field(None, ge=1, le=5)
    priority: int | None = Field(None, ge=0)
    content_tpl: str | None = None
    suggest: str | None = None


class RuleOutput(BaseModel):
    id: int
    point_id: str
    name: str | None = None
    enabled: bool
    operator: str
    operand: float | None = None
    operand_min: float | None = None
    operand_max: float | None = None
    cond_type: str
    restore_operator: str | None = None
    restore_operand: float | None = None
    continuous_time: int
    recover_hold_time: int
    level: int
    priority: int
    content_tpl: str | None = None
    suggest: str | None = None
