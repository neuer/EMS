"""系统类 ORM：EMS 连接配置、同步日志。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class EmsConfig(Base):
    """EMS 连接配置（单条，id 固定为 1）。password_enc 加密存储。"""

    __tablename__ = "ems_config"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    password_enc: Mapped[str] = mapped_column(Text, nullable=False)
    recv_ip: Mapped[str] = mapped_column(String(64), nullable=False)
    recv_port: Mapped[str] = mapped_column(String(8), nullable=False)
    version_str: Mapped[str] = mapped_column(String(64), nullable=False)
    sync_interval_s: Mapped[int] = mapped_column(Integer, nullable=False, default=21600)
    subscribe_data: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    subscribe_alarm: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    deadband_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReportSchedule(Base):
    """定时邮件报表计划（映射迁移 0001 的 report_schedules）。

    report_type：日报 daily / 周报 weekly / 月报 monthly；
    cron：标准 5 段 crontab 表达式（APScheduler CronTrigger.from_crontab 解析）；
    group_ids：接收组 id 数组，发送对象为组内成员邮箱（复用通知接收人）。
    """

    __tablename__ = "report_schedules"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    report_type: Mapped[str] = mapped_column(String(16), nullable=False)  # daily|weekly|monthly
    cron: Mapped[str] = mapped_column(String(64), nullable=False)
    group_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SyncLog(Base):
    __tablename__ = "sync_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # config|backfill
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    added: Mapped[int | None] = mapped_column(Integer, default=0)
    changed: Mapped[int | None] = mapped_column(Integer, default=0)
    inactivated: Mapped[int | None] = mapped_column(Integer, default=0)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    success: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
