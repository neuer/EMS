"""EMS 同步对象 ORM：空间 / 设备 / 测点（只读镜像）。

映射 02 DDL 的 spaces / devices / points 表；结构以迁移为事实源。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, SmallInteger, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Space(Base):
    __tablename__ = "spaces"

    resource_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    space_type: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Device(Base):
    __tablename__ = "devices"

    resource_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    device_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    location: Mapped[str | None] = mapped_column(Text, nullable=True)
    link: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Point(Base):
    __tablename__ = "points"

    resource_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    device_id: Mapped[str] = mapped_column(String(64), nullable=False)
    spot_type: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mapper: Mapped[str | None] = mapped_column(Text, nullable=True)
    access: Mapped[str | None] = mapped_column(String(8), nullable=True)
    raw_filter: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_event_rules: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DeviceStatus(Base):
    __tablename__ = "device_status"

    device_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0通信中断 1正常
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
