"""通知相关 ORM：渠道 / 接收人 / 接收组 / 级别路由 / 发送记录。

映射 02 DDL 的 notify_channels / recipients / recipient_groups /
recipient_group_members / notify_routes / notify_logs；结构以迁移 0001 为事实源。
渠道 config 中的敏感字段加密存储（红线：凭据加密、不裸奔）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class NotifyChannel(Base):
    __tablename__ = "notify_channels"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    # type: sms|email|dingtalk|wecom|voice|webhook
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Recipient(Base):
    __tablename__ = "recipients"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dingtalk_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    wecom_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class RecipientGroup(Base):
    __tablename__ = "recipient_groups"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)


class RecipientGroupMember(Base):
    __tablename__ = "recipient_group_members"

    group_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("recipient_groups.id", ondelete="CASCADE"), primary_key=True
    )
    recipient_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("recipients.id", ondelete="CASCADE"), primary_key=True
    )


class NotifyRoute(Base):
    __tablename__ = "notify_routes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    level: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 1-5
    channel_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False)
    group_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger), nullable=False)
    notify_on_recover: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class NotifyLog(Base):
    __tablename__ = "notify_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    alarm_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("alarms.id"), nullable=True
    )
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    recipient: Mapped[str | None] = mapped_column(String(128), nullable=True)
    trigger: Mapped[str | None] = mapped_column(String(16), nullable=True)  # raise|recover|digest
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # sent|failed|retrying
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sent_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
