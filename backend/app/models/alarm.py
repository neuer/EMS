"""告警相关 ORM：预警规则 / 告警主记录 / 生命周期事件流。

映射 02 DDL 的 alarm_rules / alarms / alarm_events；结构以迁移 0001 为事实源。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import AlarmSource, AlarmStatus, ResourceKind
from app.core.db import Base

# 审查 M4：状态/来源/操作符等封闭域此前仅靠注释，DB 层无约束。下列 CHECK 让 DB 成为最后防线，
# 拦截绕过 Pydantic 的非法写入（迁移/回补/内部 service 直接构造）。取值复用枚举/Literal 防漂移。
_OPERATORS = (">", "<", "=", "<>", "<=", ">=")
_COND_TYPES = ("threshold", "range")


def _sql_in(column: str, values: tuple[object, ...]) -> str:
    items = ", ".join(f"'{v}'" if isinstance(v, str) else str(int(v)) for v in values)  # type: ignore[arg-type]
    return f"{column} IN ({items})"


class AlarmRule(Base):
    __tablename__ = "alarm_rules"
    __table_args__ = (
        CheckConstraint(_sql_in("operator", _OPERATORS), name="ck_alarm_rules_operator"),
        CheckConstraint(
            f"restore_operator IS NULL OR {_sql_in('restore_operator', _OPERATORS)}",
            name="ck_alarm_rules_restore_operator",
        ),
        CheckConstraint(_sql_in("cond_type", _COND_TYPES), name="ck_alarm_rules_cond_type"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    point_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 触发条件
    operator: Mapped[str] = mapped_column(String(4), nullable=False)  # > < = <> <= >=
    operand: Mapped[float | None] = mapped_column(Float, nullable=True)
    operand_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    operand_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    cond_type: Mapped[str] = mapped_column(String(16), nullable=False, default="threshold")
    # 恢复条件
    restore_operator: Mapped[str | None] = mapped_column(String(4), nullable=True)
    restore_operand: Mapped[float | None] = mapped_column(Float, nullable=True)
    # 去抖与恢复
    continuous_time: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    recover_hold_time: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 分级与多档
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 1紧急..5提示
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    content_tpl: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggest: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Alarm(Base):
    __tablename__ = "alarms"
    __table_args__ = (
        CheckConstraint(_sql_in("source", tuple(AlarmSource)), name="ck_alarms_source"),
        CheckConstraint(_sql_in("status", tuple(AlarmStatus)), name="ck_alarms_status"),
        CheckConstraint(
            _sql_in("resource_kind", tuple(ResourceKind)), name="ck_alarms_resource_kind"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # platform | ems
    guid: Mapped[str | None] = mapped_column(String(80), nullable=True)
    rule_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("alarm_rules.id"), nullable=True
    )
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_kind: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 3测点 2设备
    event_type: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    trigger_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggest: Mapped[str | None] = mapped_column(Text, nullable=True)
    masked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    silenced_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 防轰炸
    merge_key: Mapped[str | None] = mapped_column(String(160), nullable=True)
    merge_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # 时间与处理
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    accept_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    confirm_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    recovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recover_desc: Mapped[str | None] = mapped_column(Text, nullable=True)


class AlarmEvent(Base):
    __tablename__ = "alarm_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    alarm_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("alarms.id", ondelete="CASCADE"), nullable=False
    )
    # event: raise|accept|confirm|recover|note|merge
    event: Mapped[str] = mapped_column(String(16), nullable=False)
    operator_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot: Mapped[float | None] = mapped_column(Float, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
